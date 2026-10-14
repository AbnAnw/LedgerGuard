from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ledgerguard.auth import AuthPrincipal, get_current_principal
from ledgerguard.db import get_db
from ledgerguard.jobs import (
    _claim_job,
    _existing_job_or_conflict,
    _job_response,
    cancel_background_job,
    mark_job_for_retry,
    process_background_job_once,
)
from ledgerguard.main import app
from ledgerguard.models import BackgroundJob, BackgroundJobKind, BackgroundJobStatus

NOW = datetime(2026, 10, 14, 4, 0, tzinfo=UTC)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def principal(role: str, *, user_id: UUID | None = None) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=user_id or uuid4(),
        session_id=uuid4(),
        email=f"{role}@ledgerguard.invalid",
        display_name=f"Synthetic {role}",
        roles=(role,),
    )


def job(
    *,
    kind: BackgroundJobKind = BackgroundJobKind.RECONCILIATION,
    status: BackgroundJobStatus = BackgroundJobStatus.QUEUED,
    requested_by_user_id: UUID | None = None,
) -> BackgroundJob:
    return BackgroundJob(
        id=uuid4(),
        kind=kind,
        status=status,
        deduplication_key="a" * 64,
        request_sha256="b" * 64,
        payload={"synthetic": True},
        requested_by_user_id=requested_by_user_id or uuid4(),
        correlation_id=uuid4(),
        celery_task_id=str(uuid4()),
        progress_current=0,
        progress_total=4,
        attempt_count=0,
        max_attempts=3,
        status_message="Queued for worker delivery.",
        created_at=NOW,
        version=1,
    )


def test_job_response_reports_bounded_integer_progress() -> None:
    queued = job()
    queued.progress_current = 3

    response = _job_response(queued)

    assert response.progress_percent == 75
    assert response.failure_detail is None
    assert response.cancellation_requested is False


def test_changed_request_for_same_deduplication_key_is_rejected() -> None:
    existing = job()
    db = MagicMock(spec=Session)
    db.scalar.return_value = existing

    with pytest.raises(HTTPException) as error:
        _existing_job_or_conflict(db, existing.deduplication_key, "c" * 64)

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_claim_moves_queued_job_to_running_and_redelivery_can_resume() -> None:
    queued = job()
    db = MagicMock(spec=Session)
    db.scalar.return_value = queued

    claimed, payload = _claim_job(db, queued.id)

    assert payload == {"synthetic": True}
    assert claimed.status == BackgroundJobStatus.RUNNING
    assert claimed.attempt_count == 1
    assert claimed.started_at is not None
    db.commit.assert_called_once()

    duplicate, duplicate_payload = _claim_job(db, queued.id)
    assert duplicate is queued
    assert duplicate_payload == {"synthetic": True}
    assert queued.attempt_count == 1
    assert db.commit.call_count == 1


def test_claim_honours_queued_cancellation_before_execution() -> None:
    queued = job()
    queued.cancellation_requested_at = NOW
    db = MagicMock(spec=Session)
    db.scalar.return_value = queued

    claimed, payload = _claim_job(db, queued.id)

    assert payload is None
    assert claimed.status == BackgroundJobStatus.CANCELLED
    assert claimed.finished_at is not None
    assert claimed.payload == {}


@pytest.mark.parametrize("role", ["administrator", "operations_analyst", "auditor"])
def test_authorized_roles_can_read_reconciliation_job(role: str, client: TestClient) -> None:
    stored = job()
    db = MagicMock(spec=Session)
    db.get.return_value = stored
    app.dependency_overrides[get_current_principal] = lambda: principal(role)
    app.dependency_overrides[get_db] = lambda: db

    response = client.get(f"/api/v1/jobs/{stored.id}")

    assert response.status_code == 200
    assert response.json()["job_id"] == str(stored.id)


def test_auditor_cannot_cancel_reconciliation_job(client: TestClient) -> None:
    stored = job()
    db = MagicMock(spec=Session)
    db.scalar.return_value = stored
    app.dependency_overrides[get_current_principal] = lambda: principal("auditor")
    app.dependency_overrides[get_db] = lambda: db

    response = client.post(f"/api/v1/jobs/{stored.id}/cancel")

    assert response.status_code == 403
    db.commit.assert_not_called()


def test_owner_can_cancel_queued_job_without_terminating_worker_process(
    client: TestClient,
) -> None:
    owner_id = uuid4()
    stored = job(requested_by_user_id=owner_id)
    db = MagicMock(spec=Session)
    db.scalar.return_value = stored
    app.dependency_overrides[get_current_principal] = lambda: principal(
        "operations_analyst", user_id=owner_id
    )
    app.dependency_overrides[get_db] = lambda: db

    response = client.post(f"/api/v1/jobs/{stored.id}/cancel")

    assert response.status_code == 202
    assert response.json()["status"] == "cancelled"
    assert stored.payload == {}
    db.commit.assert_called_once()


def test_terminal_cancel_is_idempotent_and_returns_http_200() -> None:
    owner = principal("operations_analyst")
    stored = job(status=BackgroundJobStatus.SUCCEEDED, requested_by_user_id=owner.user_id)
    stored.progress_current = stored.progress_total
    stored.finished_at = NOW
    db = MagicMock(spec=Session)
    db.scalar.return_value = stored
    response = SimpleNamespace(status_code=202)

    result = cancel_background_job(stored.id, response, owner, db)

    assert response.status_code == 200
    assert result.status == BackgroundJobStatus.SUCCEEDED
    db.commit.assert_not_called()


def test_duplicate_terminal_delivery_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = job(status=BackgroundJobStatus.SUCCEEDED)
    stored.progress_current = stored.progress_total
    stored.finished_at = NOW
    database = MagicMock(spec=Session)
    context = MagicMock()
    context.__enter__.return_value = database
    context.__exit__.return_value = False
    session_factory = MagicMock(return_value=context)
    monkeypatch.setattr("ledgerguard.jobs._claim_job", lambda _db, _id: (stored, None))

    result = process_background_job_once(stored.id, session_factory)

    assert result.status == BackgroundJobStatus.SUCCEEDED
    assert session_factory.call_count == 1


def test_transient_failure_requeues_with_bounded_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = job(status=BackgroundJobStatus.RUNNING)
    stored.attempt_count = 1
    database = MagicMock(spec=Session)
    database.get.return_value = stored
    context = MagicMock()
    context.__enter__.return_value = database
    context.__exit__.return_value = False
    monkeypatch.setattr("ledgerguard.jobs.SessionLocal", MagicMock(return_value=context))

    retry = mark_job_for_retry(stored.id)

    assert retry is True
    assert stored.status == BackgroundJobStatus.QUEUED
    assert stored.failure_code == "RETRYABLE_DEPENDENCY_ERROR"
    assert stored.finished_at is None
    database.commit.assert_called_once()


def test_retry_limit_fails_job_and_removes_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = job(status=BackgroundJobStatus.RUNNING)
    stored.attempt_count = stored.max_attempts
    database = MagicMock(spec=Session)
    database.get.return_value = stored
    context = MagicMock()
    context.__enter__.return_value = database
    context.__exit__.return_value = False
    monkeypatch.setattr("ledgerguard.jobs.SessionLocal", MagicMock(return_value=context))

    retry = mark_job_for_retry(stored.id)

    assert retry is False
    assert stored.status == BackgroundJobStatus.FAILED
    assert stored.failure_code == "RETRY_LIMIT_EXCEEDED"
    assert stored.finished_at is not None
    assert stored.payload == {}
    database.commit.assert_called_once()


def test_ingestion_worker_delivery_links_result_and_uses_requester(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = job(kind=BackgroundJobKind.TRANSACTION_INGESTION)
    stored.payload = {
        "format": "json",
        "metadata": {
            "schema_version": "1.0",
            "source_system": "synthetic-demo",
            "source_account_id": "DEMO-ACCOUNT-001",
        },
        "idempotency_key": "worker-test",
        "original_filename": None,
        "records": [
            {
                "source_record_id": "JOB-TX-1",
                "source_reference": "JOB-REF-1",
                "amount": "10.000000",
                "currency": "USD",
                "direction": "credit",
                "status": "posted",
                "occurred_at": "2026-10-13T01:00:00Z",
            }
        ],
    }
    requester = principal("operations_analyst", user_id=stored.requested_by_user_id)
    batch_id = uuid4()
    completed = _job_response(stored)
    completed.status = BackgroundJobStatus.SUCCEEDED
    completed.ingestion_batch_id = batch_id
    database = MagicMock(spec=Session)
    context = MagicMock()
    context.__enter__.return_value = database
    context.__exit__.return_value = False
    session_factory = MagicMock(return_value=context)
    ingest = MagicMock(return_value=SimpleNamespace(batch_id=batch_id))
    monkeypatch.setattr("ledgerguard.jobs._claim_job", lambda _db, _id: (stored, stored.payload))
    monkeypatch.setattr("ledgerguard.jobs._worker_principal", lambda _db, _job: requester)
    monkeypatch.setattr("ledgerguard.jobs._update_progress", lambda *args: None)
    monkeypatch.setattr("ledgerguard.jobs._cancellation_checkpoint", lambda *args: False)
    monkeypatch.setattr("ledgerguard.ingestion.ingest_transactions", ingest)
    monkeypatch.setattr("ledgerguard.jobs._finish_job", lambda *args, **kwargs: completed)

    result = process_background_job_once(stored.id, session_factory)

    assert result.status == BackgroundJobStatus.SUCCEEDED
    assert result.ingestion_batch_id == batch_id
    assert ingest.call_args.args[3].user_id == requester.user_id


def test_ingestion_job_is_private_to_requester(client: TestClient) -> None:
    stored = job(kind=BackgroundJobKind.TRANSACTION_INGESTION)
    db = MagicMock(spec=Session)
    db.get.return_value = stored
    app.dependency_overrides[get_current_principal] = lambda: principal("operations_analyst")
    app.dependency_overrides[get_db] = lambda: db

    response = client.get(f"/api/v1/jobs/{stored.id}")

    assert response.status_code == 403


def test_missing_job_returns_not_found(client: TestClient) -> None:
    db = MagicMock(spec=Session)
    db.get.return_value = None
    app.dependency_overrides[get_current_principal] = lambda: principal("administrator")
    app.dependency_overrides[get_db] = lambda: db

    response = client.get(f"/api/v1/jobs/{uuid4()}")

    assert response.status_code == 404
