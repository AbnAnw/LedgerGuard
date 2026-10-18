"""Celery worker application and durable LedgerGuard tasks."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from billiard.exceptions import SoftTimeLimitExceeded  # type: ignore[import-untyped]
from celery import Celery  # type: ignore[import-untyped]
from opentelemetry import trace
from sqlalchemy.exc import SQLAlchemyError

from ledgerguard import __version__
from ledgerguard.config import get_settings
from ledgerguard.observability import configure_observability, job_span, log_event

settings = get_settings()

celery_app = Celery(
    "ledgerguard",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    enable_utc=True,
    timezone="UTC",
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_redirect_stdouts=False,
)


@celery_app.task(name="ledgerguard.worker.ping")  # type: ignore[misc]
def ping() -> dict[str, str]:
    """Return deterministic worker build metadata without external side effects."""

    return {
        "status": "ok",
        "service": "ledgerguard-worker",
        "version": __version__,
        "checked_at": datetime.now(UTC).isoformat(),
    }


@celery_app.task(  # type: ignore[misc]
    bind=True,
    name="ledgerguard.worker.process_background_job",
    max_retries=settings.background_job_max_attempts - 1,
    soft_time_limit=settings.background_job_soft_time_limit_seconds,
    time_limit=settings.background_job_hard_time_limit_seconds,
)
def process_background_job(task: Any, job_id: str) -> dict[str, object]:
    """Process one durable job; PostgreSQL state makes redelivery safe."""

    configure_observability("ledgerguard-worker")

    from ledgerguard.jobs import (
        get_job_observability_context,
        mark_job_failed,
        mark_job_for_retry,
        process_background_job_once,
    )

    parsed_job_id = UUID(job_id)
    try:
        correlation_id, kind, carrier = get_job_observability_context(parsed_job_id)
    except SQLAlchemyError:
        log_event(
            "job.context.unavailable",
            "Worker could not load durable job context; applying bounded retry policy.",
            level=30,
            service="ledgerguard-worker",
            job_id=job_id,
        )
        if mark_job_for_retry(parsed_job_id):
            raise task.retry(
                exc=RuntimeError("retryable dependency error"),
                countdown=min(2 ** max(task.request.retries, 0), 30),
            ) from None
        return {
            "job_id": job_id,
            "status": "failed",
            "failure_code": "RETRY_LIMIT_EXCEEDED",
        }
    with job_span(
        job_id=parsed_job_id,
        correlation_id=correlation_id,
        kind=kind,
        carrier=carrier,
    ) as span:
        log_event(
            "job.started",
            "Worker started durable background job.",
            service="ledgerguard-worker",
            job_kind=kind,
            job_status="running",
        )
        try:
            result = process_background_job_once(parsed_job_id).model_dump(mode="json")
        except SoftTimeLimitExceeded:
            result = mark_job_failed(
                parsed_job_id,
                "JOB_TIMEOUT",
                "The worker exceeded the configured processing time limit.",
            ).model_dump(mode="json")
        except SQLAlchemyError:
            if mark_job_for_retry(parsed_job_id):
                span.set_attribute("ledgerguard.job.status", "retrying")
                span.set_status(trace.Status(trace.StatusCode.ERROR, "retryable dependency error"))
                raise task.retry(
                    exc=RuntimeError("retryable dependency error"),
                    countdown=min(2 ** max(task.request.retries, 0), 30),
                ) from None
            result = {
                "job_id": job_id,
                "status": "failed",
                "failure_code": "RETRY_LIMIT_EXCEEDED",
            }
        status_value = str(result["status"])
        span.set_attribute("ledgerguard.job.status", status_value)
        if status_value == "failed":
            failure_code = str(result.get("failure_code") or "unknown")
            span.set_attribute("ledgerguard.job.failure_code", failure_code)
            span.set_status(trace.Status(trace.StatusCode.ERROR, failure_code))
        return result
