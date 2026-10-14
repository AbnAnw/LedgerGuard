"""Durable, permission-aware background job orchestration."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ledgerguard.auth import AuthPrincipal, Permission, get_current_principal
from ledgerguard.config import get_settings
from ledgerguard.db import SessionLocal, get_db
from ledgerguard.models import (
    Account,
    AccountStatus,
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobStatus,
    User,
)

TERMINAL_JOB_STATUSES = frozenset(
    {
        BackgroundJobStatus.SUCCEEDED,
        BackgroundJobStatus.FAILED,
        BackgroundJobStatus.CANCELLED,
    }
)


class BackgroundJobResponse(BaseModel):
    job_id: UUID
    kind: BackgroundJobKind
    status: BackgroundJobStatus
    replayed: bool
    progress_current: int
    progress_total: int
    progress_percent: int
    attempt_count: int
    max_attempts: int
    status_message: str | None
    failure_code: str | None
    failure_detail: str | None
    cancellation_requested: bool
    ingestion_batch_id: UUID | None
    reconciliation_run_id: UUID | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


def _job_response(job: BackgroundJob, *, replayed: bool = False) -> BackgroundJobResponse:
    return BackgroundJobResponse(
        job_id=job.id,
        kind=job.kind,
        status=job.status,
        replayed=replayed,
        progress_current=job.progress_current,
        progress_total=job.progress_total,
        progress_percent=(job.progress_current * 100) // job.progress_total,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        status_message=job.status_message,
        failure_code=job.failure_code,
        failure_detail=job.failure_detail,
        cancellation_requested=job.cancellation_requested_at is not None,
        ingestion_batch_id=job.ingestion_batch_id,
        reconciliation_run_id=job.reconciliation_run_id,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _deduplication_key(kind: BackgroundJobKind, scope: dict[str, str]) -> str:
    return _canonical_sha256({"kind": kind.value, "scope": scope})


def _request_hash(payload: dict[str, Any]) -> str:
    return _canonical_sha256(payload)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def publish_background_job(job_id: UUID) -> None:
    """Publish after the durable job commits, using its UUID as the task ID."""

    from ledgerguard.worker import process_background_job

    process_background_job.apply_async(args=[str(job_id)], task_id=str(job_id))


def _publish_or_unavailable(job_id: UUID) -> None:
    try:
        publish_background_job(job_id)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "QUEUE_UNAVAILABLE",
                "message": (
                    "The job is safely queued but the worker broker is unavailable; "
                    "retry the same request."
                ),
            },
        ) from error


def _existing_job_or_conflict(
    db: Session, deduplication_key: str, request_sha256: str
) -> BackgroundJob | None:
    existing = db.scalar(
        select(BackgroundJob).where(BackgroundJob.deduplication_key == deduplication_key)
    )
    if existing is not None and existing.request_sha256 != request_sha256:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "IDEMPOTENCY_KEY_REUSED",
                "message": "The idempotency key was already used for different content.",
            },
        )
    return existing


def _create_or_replay_job(
    db: Session,
    *,
    kind: BackgroundJobKind,
    deduplication_key: str,
    request_sha256: str,
    payload: dict[str, Any],
    principal: AuthPrincipal,
    progress_total: int,
) -> tuple[BackgroundJob, bool]:
    existing = _existing_job_or_conflict(db, deduplication_key, request_sha256)
    if existing is not None:
        if existing.status == BackgroundJobStatus.QUEUED:
            _publish_or_unavailable(existing.id)
        return existing, True

    job_id = uuid4()
    job = BackgroundJob(
        id=job_id,
        kind=kind,
        status=BackgroundJobStatus.QUEUED,
        deduplication_key=deduplication_key,
        request_sha256=request_sha256,
        payload=payload,
        requested_by_user_id=principal.user_id,
        correlation_id=uuid4(),
        celery_task_id=str(job_id),
        progress_current=0,
        progress_total=max(progress_total, 1),
        attempt_count=0,
        max_attempts=get_settings().background_job_max_attempts,
        status_message="Queued for worker delivery.",
        version=1,
    )
    try:
        db.add(job)
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = _existing_job_or_conflict(db, deduplication_key, request_sha256)
        if concurrent is None:
            raise
        if concurrent.status == BackgroundJobStatus.QUEUED:
            _publish_or_unavailable(concurrent.id)
        return concurrent, True

    _publish_or_unavailable(job.id)
    return job, False


def enqueue_ingestion_job(
    db: Session,
    *,
    source_system: str,
    source_account_id: str,
    schema_version: str,
    idempotency_key: str,
    format_name: str,
    records: list[dict[str, Any]] | None,
    csv_content: bytes | None,
    original_filename: str | None,
    principal: AuthPrincipal,
) -> tuple[BackgroundJobResponse, bool]:
    account = db.scalar(
        select(Account).where(
            Account.source_system == source_system,
            Account.source_account_id == source_account_id,
            Account.status == AccountStatus.ACTIVE,
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "ACCOUNT_NOT_FOUND",
                "message": "No active source account matches the batch metadata.",
            },
        )

    payload: dict[str, Any] = {
        "format": format_name,
        "metadata": {
            "schema_version": schema_version,
            "source_system": source_system,
            "source_account_id": source_account_id,
        },
        "idempotency_key": idempotency_key,
        "original_filename": original_filename,
    }
    if format_name == "json":
        payload["records"] = records or []
        progress_total = len(records or [])
    else:
        payload["content_base64"] = base64.b64encode(csv_content or b"").decode("ascii")
        progress_total = 1

    job, replayed = _create_or_replay_job(
        db,
        kind=BackgroundJobKind.TRANSACTION_INGESTION,
        deduplication_key=_deduplication_key(
            BackgroundJobKind.TRANSACTION_INGESTION,
            {"source_system": source_system, "idempotency_key": idempotency_key},
        ),
        request_sha256=_request_hash(payload),
        payload=payload,
        principal=principal,
        progress_total=progress_total,
    )
    return _job_response(job, replayed=replayed), replayed


def enqueue_reconciliation_job(
    db: Session,
    *,
    request_payload: dict[str, Any],
    idempotency_key: str,
    principal: AuthPrincipal,
) -> tuple[BackgroundJobResponse, bool]:
    payload = {"request": request_payload, "idempotency_key": idempotency_key}
    job, replayed = _create_or_replay_job(
        db,
        kind=BackgroundJobKind.RECONCILIATION,
        deduplication_key=_deduplication_key(
            BackgroundJobKind.RECONCILIATION,
            {
                "source_system": str(request_payload["source_system"]),
                "idempotency_key": idempotency_key,
            },
        ),
        request_sha256=_request_hash(payload),
        payload=payload,
        principal=principal,
        progress_total=3,
    )
    return _job_response(job, replayed=replayed), replayed


def _worker_principal(db: Session, job: BackgroundJob) -> AuthPrincipal:
    user = db.get(User, job.requested_by_user_id)
    if user is None:
        raise RuntimeError("Background job requester no longer exists")
    return AuthPrincipal(
        user_id=user.id,
        session_id=job.id,
        email=user.email,
        display_name=user.display_name,
        roles=(),
    )


def _claim_job(db: Session, job_id: UUID) -> tuple[BackgroundJob, dict[str, Any] | None]:
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.id == job_id).with_for_update())
    if job is None:
        raise RuntimeError("Background job does not exist")
    if job.status in TERMINAL_JOB_STATUSES:
        return job, None
    now = datetime.now(UTC)
    if job.cancellation_requested_at is not None:
        job.status = BackgroundJobStatus.CANCELLED
        job.status_message = "Cancelled before worker execution."
        job.finished_at = now
        job.payload = {}
        db.commit()
        return job, None
    if job.status == BackgroundJobStatus.RUNNING:
        # A worker can die after the durable claim but before acknowledgement. A redelivery
        # resumes the retained envelope without consuming another logical retry. Domain-level
        # account locks and idempotency keys serialize a concurrently duplicated delivery.
        return job, dict(job.payload)
    job.status = BackgroundJobStatus.RUNNING
    job.attempt_count += 1
    job.started_at = job.started_at or now
    job.status_message = "Worker accepted the job."
    payload = dict(job.payload)
    db.commit()
    return job, payload


def _cancellation_checkpoint(db: Session, job_id: UUID, message: str) -> bool:
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.id == job_id).with_for_update())
    if job is None:
        raise RuntimeError("Background job does not exist")
    if job.cancellation_requested_at is None:
        return False
    job.status = BackgroundJobStatus.CANCELLED
    job.status_message = message
    job.finished_at = datetime.now(UTC)
    job.payload = {}
    db.commit()
    return True


def _update_progress(db: Session, job_id: UUID, current: int, total: int, message: str) -> None:
    job = db.get(BackgroundJob, job_id)
    if job is None:
        raise RuntimeError("Background job does not exist")
    job.progress_total = max(total, 1)
    job.progress_current = min(current, job.progress_total)
    job.status_message = message
    db.commit()


def _finish_job(
    db: Session,
    job_id: UUID,
    *,
    ingestion_batch_id: UUID | None = None,
    reconciliation_run_id: UUID | None = None,
) -> BackgroundJobResponse:
    job = db.get(BackgroundJob, job_id)
    if job is None:
        raise RuntimeError("Background job does not exist")
    job.status = BackgroundJobStatus.SUCCEEDED
    job.progress_current = job.progress_total
    job.status_message = "Processing completed successfully."
    job.failure_code = None
    job.failure_detail = None
    job.ingestion_batch_id = ingestion_batch_id
    job.reconciliation_run_id = reconciliation_run_id
    job.finished_at = datetime.now(UTC)
    job.payload = {}
    db.commit()
    db.refresh(job)
    return _job_response(job)


def mark_job_failed(job_id: UUID, code: str, detail: str) -> BackgroundJobResponse:
    with SessionLocal() as db:
        job = db.get(BackgroundJob, job_id)
        if job is None:
            raise RuntimeError("Background job does not exist")
        if job.status in TERMINAL_JOB_STATUSES:
            return _job_response(job)
        job.status = BackgroundJobStatus.FAILED
        job.failure_code = code
        job.failure_detail = detail[:500]
        job.status_message = "Processing failed."
        job.finished_at = datetime.now(UTC)
        job.payload = {}
        db.commit()
        db.refresh(job)
        return _job_response(job)


def mark_job_for_retry(job_id: UUID) -> bool:
    with SessionLocal() as db:
        job = db.get(BackgroundJob, job_id)
        if job is None:
            raise RuntimeError("Background job does not exist")
        if job.attempt_count >= job.max_attempts:
            job.status = BackgroundJobStatus.FAILED
            job.failure_code = "RETRY_LIMIT_EXCEEDED"
            job.failure_detail = "The retry limit was reached after a transient processing failure."
            job.status_message = "Processing failed after bounded retries."
            job.finished_at = datetime.now(UTC)
            job.payload = {}
            db.commit()
            return False
        job.status = BackgroundJobStatus.QUEUED
        job.failure_code = "RETRYABLE_DEPENDENCY_ERROR"
        job.failure_detail = "A transient dependency failure will be retried."
        job.status_message = "Waiting for bounded retry."
        db.commit()
        return True


def process_background_job_once(
    job_id: UUID, session_factory: Callable[[], Session] = SessionLocal
) -> BackgroundJobResponse:
    """Run one delivery. Terminal or concurrent duplicate deliveries are no-ops."""

    with session_factory() as claim_db:
        job, payload = _claim_job(claim_db, job_id)
        if payload is None:
            return _job_response(job)
        principal = _worker_principal(claim_db, job)
        kind = job.kind

    try:
        if kind == BackgroundJobKind.TRANSACTION_INGESTION:
            from ledgerguard.ingestion import (
                IngestionBatchMetadata,
                ingest_transactions,
                parse_csv_records,
            )

            if payload["format"] == "csv":
                records = parse_csv_records(base64.b64decode(payload["content_base64"]))
            else:
                records = list(payload["records"])
            with session_factory() as progress_db:
                _update_progress(
                    progress_db, job_id, 0, len(records), "Input parsed; validating rows."
                )
            with session_factory() as cancel_db:
                if _cancellation_checkpoint(
                    cancel_db, job_id, "Cancelled after parsing and before financial processing."
                ):
                    cancelled_job = cancel_db.get(BackgroundJob, job_id)
                    if cancelled_job is None:
                        raise RuntimeError("Background job does not exist")
                    return _job_response(cancelled_job)
            metadata = IngestionBatchMetadata.model_validate(payload["metadata"])
            with session_factory() as operation_db:
                ingestion_result = ingest_transactions(
                    operation_db,
                    metadata,
                    records,
                    principal,
                    str(payload["idempotency_key"]),
                    payload.get("original_filename"),
                )
            with session_factory() as finish_db:
                return _finish_job(finish_db, job_id, ingestion_batch_id=ingestion_result.batch_id)

        from ledgerguard.reconciliation import ReconciliationRunRequest, execute_reconciliation

        with session_factory() as progress_db:
            _update_progress(progress_db, job_id, 1, 3, "Request validated; loading facts.")
        with session_factory() as cancel_db:
            if _cancellation_checkpoint(
                cancel_db, job_id, "Cancelled before reconciliation processing."
            ):
                cancelled_job = cancel_db.get(BackgroundJob, job_id)
                if cancelled_job is None:
                    raise RuntimeError("Background job does not exist")
                return _job_response(cancelled_job)
        request = ReconciliationRunRequest.model_validate(payload["request"])
        with session_factory() as operation_db:
            reconciliation_result = execute_reconciliation(operation_db, request, principal)
        with session_factory() as progress_db:
            _update_progress(progress_db, job_id, 2, 3, "Evidence persisted; finalizing job.")
        with session_factory() as finish_db:
            return _finish_job(
                finish_db,
                job_id,
                reconciliation_run_id=reconciliation_result.run_id,
            )
    except SQLAlchemyError:
        raise
    except (HTTPException, ValidationError, ValueError) as error:
        code = "JOB_INPUT_REJECTED"
        detail = "The queued input failed deterministic validation."
        if isinstance(error, HTTPException) and isinstance(error.detail, dict):
            code = str(error.detail.get("code", code))[:80]
            detail = str(error.detail.get("message", detail))[:500]
        return mark_job_failed(job_id, code, detail)
    except Exception:
        return mark_job_failed(
            job_id,
            "JOB_EXECUTION_FAILED",
            "The worker could not complete processing; inspect correlated structured logs.",
        )


def _can_read_job(principal: AuthPrincipal, job: BackgroundJob) -> bool:
    if "administrator" in principal.roles:
        return True
    if job.kind == BackgroundJobKind.RECONCILIATION:
        return Permission.RECONCILIATION_READ in principal.permissions
    return (
        job.requested_by_user_id == principal.user_id
        and Permission.INGESTION_WRITE in principal.permissions
    )


def _can_cancel_job(principal: AuthPrincipal, job: BackgroundJob) -> bool:
    if "administrator" in principal.roles:
        return True
    if job.requested_by_user_id != principal.user_id:
        return False
    permission = (
        Permission.RECONCILIATION_WRITE
        if job.kind == BackgroundJobKind.RECONCILIATION
        else Permission.INGESTION_WRITE
    )
    return permission in principal.permissions


router = APIRouter(prefix="/api/v1/jobs", tags=["background jobs"])


@router.get("/{job_id}", response_model=BackgroundJobResponse)
def read_background_job(
    job_id: UUID,
    principal: Annotated[AuthPrincipal, Depends(get_current_principal)],
    db: Annotated[Session, Depends(get_db)],
) -> BackgroundJobResponse:
    job = db.get(BackgroundJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if not _can_read_job(principal, job):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
    return _job_response(job)


@router.post(
    "/{job_id}/cancel", response_model=BackgroundJobResponse, status_code=status.HTTP_202_ACCEPTED
)
def cancel_background_job(
    job_id: UUID,
    response: Response,
    principal: Annotated[AuthPrincipal, Depends(get_current_principal)],
    db: Annotated[Session, Depends(get_db)],
) -> BackgroundJobResponse:
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.id == job_id).with_for_update())
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if not _can_cancel_job(principal, job):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
    if job.status in TERMINAL_JOB_STATUSES:
        response.status_code = status.HTTP_200_OK
        return _job_response(job)

    job.cancellation_requested_at = datetime.now(UTC)
    if job.status == BackgroundJobStatus.QUEUED:
        job.status = BackgroundJobStatus.CANCELLED
        job.status_message = "Cancelled before worker execution."
        job.finished_at = datetime.now(UTC)
        job.payload = {}
    else:
        job.status_message = "Cancellation requested; waiting for a safe worker checkpoint."
    db.commit()
    db.refresh(job)
    return _job_response(job)
