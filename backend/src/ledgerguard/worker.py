"""Celery worker application and durable LedgerGuard tasks."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from billiard.exceptions import SoftTimeLimitExceeded  # type: ignore[import-untyped]
from celery import Celery  # type: ignore[import-untyped]
from sqlalchemy.exc import SQLAlchemyError

from ledgerguard import __version__
from ledgerguard.config import get_settings

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

    from ledgerguard.jobs import (
        mark_job_failed,
        mark_job_for_retry,
        process_background_job_once,
    )

    try:
        return process_background_job_once(UUID(job_id)).model_dump(mode="json")
    except SoftTimeLimitExceeded:
        return mark_job_failed(
            UUID(job_id),
            "JOB_TIMEOUT",
            "The worker exceeded the configured processing time limit.",
        ).model_dump(mode="json")
    except SQLAlchemyError:
        if mark_job_for_retry(UUID(job_id)):
            raise task.retry(
                exc=RuntimeError("retryable dependency error"),
                countdown=min(2 ** max(task.request.retries, 0), 30),
            ) from None
        return {
            "job_id": job_id,
            "status": "failed",
            "failure_code": "RETRY_LIMIT_EXCEEDED",
        }
