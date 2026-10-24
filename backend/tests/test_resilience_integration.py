"""Opt-in Day 17 resilience checks against the real PostgreSQL schema."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, func, select
from sqlalchemy.exc import OperationalError

from ledgerguard.auth import AuthPrincipal
from ledgerguard.db import SessionLocal
from ledgerguard.ingestion import IngestionBatchMetadata, ingest_transactions
from ledgerguard.jobs import process_background_job_once
from ledgerguard.models import (
    Account,
    AccountStatus,
    AccountType,
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobStatus,
    FinancialTransaction,
    IngestionBatch,
    IngestionRecord,
    User,
)

RUN_INTEGRATION = os.getenv("LEDGERGUARD_RUN_INTEGRATION") == "1"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not RUN_INTEGRATION,
        reason="set LEDGERGUARD_RUN_INTEGRATION=1 inside the Docker Compose stack",
    ),
]


def _principal(user: User) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=user.id,
        session_id=uuid4(),
        email=user.email,
        display_name=user.display_name,
        roles=("operations_analyst",),
    )


def _record(source_record_id: str) -> dict[str, str]:
    return {
        "source_record_id": source_record_id,
        "source_reference": f"REF-{source_record_id}",
        "amount": "17.000001",
        "currency": "AUD",
        "direction": "debit",
        "status": "posted",
        "occurred_at": "2026-01-17T00:00:00Z",
    }


def _create_account(source_account_id: str) -> tuple[UUID, User]:
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.email == "analyst@ledgerguard.invalid"))
        assert user is not None
        account = Account(
            source_system="synthetic-resilience",
            source_account_id=source_account_id,
            display_name=f"Synthetic resilience {source_account_id}",
            account_type=AccountType.MERCHANT,
            default_currency="AUD",
            status=AccountStatus.ACTIVE,
            version=1,
        )
        db.add(account)
        db.flush()
        account_id = account.id
        db.expunge(user)
    return account_id, user


def _cleanup(account_id: UUID, job_id: UUID | None = None) -> None:
    with SessionLocal.begin() as db:
        batch_ids = list(
            db.scalars(
                select(IngestionBatch.id)
                .join(FinancialTransaction, FinancialTransaction.batch_id == IngestionBatch.id)
                .where(FinancialTransaction.account_id == account_id)
            )
        )
        if batch_ids:
            db.execute(delete(IngestionRecord).where(IngestionRecord.batch_id.in_(batch_ids)))
            db.execute(
                delete(FinancialTransaction).where(FinancialTransaction.account_id == account_id)
            )
            if job_id is not None:
                job = db.get(BackgroundJob, job_id)
                if job is not None:
                    job.ingestion_batch_id = None
                    db.flush()
            db.execute(delete(IngestionBatch).where(IngestionBatch.id.in_(batch_ids)))
        if job_id is not None:
            db.execute(delete(BackgroundJob).where(BackgroundJob.id == job_id))
        db.execute(delete(Account).where(Account.id == account_id))


def test_duplicate_delivery_creates_one_batch_and_one_financial_fact() -> None:
    suffix = uuid4().hex[:12].upper()
    source_account_id = f"DUPLICATE-{suffix}"
    source_record_id = f"DUP-{suffix}"
    account_id, user = _create_account(source_account_id)
    job_id = uuid4()
    try:
        with SessionLocal.begin() as db:
            db.add(
                BackgroundJob(
                    id=job_id,
                    kind=BackgroundJobKind.TRANSACTION_INGESTION,
                    status=BackgroundJobStatus.QUEUED,
                    deduplication_key=uuid4().hex + uuid4().hex,
                    request_sha256=uuid4().hex + uuid4().hex,
                    payload={
                        "format": "json",
                        "metadata": {
                            "schema_version": "1.0",
                            "source_system": "synthetic-resilience",
                            "source_account_id": source_account_id,
                        },
                        "records": [_record(source_record_id)],
                        "idempotency_key": f"duplicate-{suffix}",
                        "original_filename": None,
                    },
                    requested_by_user_id=user.id,
                    correlation_id=uuid4(),
                    celery_task_id=str(job_id),
                    progress_current=0,
                    progress_total=1,
                    attempt_count=0,
                    max_attempts=3,
                    status_message="Queued for duplicate-delivery drill.",
                    version=1,
                )
            )

        first = process_background_job_once(job_id)
        second = process_background_job_once(job_id)

        assert first.status is BackgroundJobStatus.SUCCEEDED
        assert second.status is BackgroundJobStatus.SUCCEEDED
        assert second.ingestion_batch_id == first.ingestion_batch_id
        with SessionLocal() as db:
            batch_count = db.scalar(
                select(func.count())
                .select_from(IngestionBatch)
                .where(IngestionBatch.id == first.ingestion_batch_id)
            )
            transaction_count = db.scalar(
                select(func.count())
                .select_from(FinancialTransaction)
                .where(FinancialTransaction.account_id == account_id)
            )
        assert batch_count == 1
        assert transaction_count == 1
    finally:
        _cleanup(account_id, job_id)


def test_partial_database_failure_rolls_back_all_ingestion_writes() -> None:
    suffix = uuid4().hex[:12].upper()
    source_account_id = f"PARTIAL-{suffix}"
    source_record_id = f"PART-{suffix}"
    account_id, user = _create_account(source_account_id)
    idempotency_key = f"partial-{suffix}"

    def fail_before_commit(_session: object) -> None:
        raise OperationalError(
            "synthetic failure after flush and before commit", {}, RuntimeError("day-17 drill")
        )

    try:
        with SessionLocal() as db:
            event.listen(db, "before_commit", fail_before_commit, once=True)
            with pytest.raises(OperationalError):
                ingest_transactions(
                    db,
                    IngestionBatchMetadata(
                        schema_version="1.0",
                        source_system="synthetic-resilience",
                        source_account_id=source_account_id,
                    ),
                    [_record(source_record_id)],
                    _principal(user),
                    idempotency_key,
                )

        with SessionLocal() as db:
            batch_count = db.scalar(
                select(func.count())
                .select_from(IngestionBatch)
                .where(IngestionBatch.idempotency_key == idempotency_key)
            )
            transaction_count = db.scalar(
                select(func.count())
                .select_from(FinancialTransaction)
                .where(FinancialTransaction.account_id == account_id)
            )
        assert batch_count == 0
        assert transaction_count == 0
    finally:
        _cleanup(account_id)
