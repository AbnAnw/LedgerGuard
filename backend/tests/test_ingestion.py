import json
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ledgerguard.auth import AuthPrincipal, get_current_principal
from ledgerguard.db import get_db
from ledgerguard.ingestion import (
    IngestionBatchMetadata,
    TransactionRecordV1,
    canonical_sha256,
    ingest_transactions,
    parse_csv_records,
)
from ledgerguard.jobs import BackgroundJobResponse
from ledgerguard.main import app
from ledgerguard.models import (
    Account,
    AccountStatus,
    AccountType,
    BackgroundJobKind,
    BackgroundJobStatus,
    FinancialTransaction,
    IngestionBatch,
    IngestionBatchStatus,
    IngestionRecord,
    IngestionRecordKind,
    IngestionRecordOutcome,
    MoneyDirection,
    TransactionStatus,
)

SAMPLE_DATA = Path(__file__).resolve().parents[2] / "sample-data"


def valid_record(record_id: str = "TXN-0001") -> dict[str, object]:
    return {
        "source_record_id": record_id,
        "source_reference": "ORDER-1001",
        "amount": "125.450000",
        "currency": "USD",
        "direction": "debit",
        "status": "posted",
        "occurred_at": "2026-10-13T01:30:00+00:00",
        "instrument_fingerprint": "a" * 64,
    }


def make_account() -> Account:
    now = datetime.now(UTC)
    return Account(
        id=uuid4(),
        source_system="synthetic-demo",
        source_account_id="DEMO-ACCOUNT-001",
        display_name="Synthetic Demonstration Account",
        account_type=AccountType.MERCHANT,
        default_currency="USD",
        status=AccountStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        version=1,
    )


def make_principal(role: str = "operations_analyst") -> AuthPrincipal:
    return AuthPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email=f"{role}@ledgerguard.invalid",
        display_name=f"Synthetic {role}",
        roles=(role,),
    )


def queued_job(*, replayed: bool = False) -> BackgroundJobResponse:
    return BackgroundJobResponse(
        job_id=uuid4(),
        kind=BackgroundJobKind.TRANSACTION_INGESTION,
        status=BackgroundJobStatus.QUEUED,
        replayed=replayed,
        progress_current=0,
        progress_total=2,
        progress_percent=0,
        attempt_count=0,
        max_attempts=3,
        status_message="Queued for worker delivery.",
        failure_code=None,
        failure_detail=None,
        cancellation_requested=False,
        ingestion_batch_id=None,
        reconciliation_run_id=None,
        created_at=datetime.now(UTC),
        started_at=None,
        finished_at=None,
    )


def make_db(
    account: Account | None = None,
    *,
    existing_batch: IngestionBatch | None = None,
    scalar_rows: list[object] | None = None,
) -> MagicMock:
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [account, existing_batch]
    db.scalars.return_value.all.return_value = scalar_rows or []
    return db


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_transaction_schema_preserves_decimal_and_normalizes_utc() -> None:
    parsed = TransactionRecordV1.model_validate(
        {**valid_record(), "occurred_at": "2026-10-13T09:30:00+08:00"}
    )

    assert parsed.decimal_amount == Decimal("125.450000")
    assert parsed.occurred_at == datetime(2026, 10, 13, 1, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount", 125.45),
        ("amount", "0"),
        ("amount", "1.0000001"),
        ("amount", "100000000000000.00"),
        ("currency", "usd"),
        ("currency", "ZZZ"),
        ("occurred_at", "2026-10-13T01:30:00"),
        ("source_record_id", "contains spaces"),
        ("instrument_fingerprint", "raw-card-number-is-forbidden"),
    ],
)
def test_transaction_schema_rejects_invalid_external_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        TransactionRecordV1.model_validate({**valid_record(), field: value})


def test_hashing_is_deterministic_and_order_independent() -> None:
    first = {"a": "one", "b": "two"}
    second = {"b": "two", "a": "one"}

    assert canonical_sha256(first) == canonical_sha256(second)
    assert len(canonical_sha256(first)) == 64


def test_exact_idempotent_retry_returns_existing_batch_without_writes() -> None:
    account = make_account()
    metadata = IngestionBatchMetadata(
        schema_version="1.0",
        source_system="synthetic-demo",
        source_account_id="DEMO-ACCOUNT-001",
    )
    raw_records = [valid_record()]
    batch = IngestionBatch(
        id=uuid4(),
        record_kind=IngestionRecordKind.TRANSACTION,
        source_system=metadata.source_system,
        schema_version=metadata.schema_version,
        idempotency_key="retry-key",
        payload_sha256=canonical_sha256(
            {"metadata": metadata.model_dump(), "records": raw_records}
        ),
        status=IngestionBatchStatus.COMPLETED,
        source_count=1,
        accepted_count=1,
        rejected_count=0,
        duplicate_count=0,
        conflict_count=0,
        requested_by_user_id=uuid4(),
        correlation_id=uuid4(),
        version=1,
    )
    transaction_id = uuid4()
    evidence = IngestionRecord(
        id=uuid4(),
        batch_id=batch.id,
        row_number=1,
        source_record_id="TXN-0001",
        payload=raw_records[0],
        payload_sha256=canonical_sha256(raw_records[0]),
        outcome=IngestionRecordOutcome.ACCEPTED,
        reason_codes=[],
        rejection_details=[],
        transaction_id=transaction_id,
        processed_at=datetime.now(UTC),
    )
    db = make_db(account, existing_batch=batch, scalar_rows=[evidence])

    result = ingest_transactions(db, metadata, raw_records, make_principal(), "retry-key")

    assert result.batch_id == batch.id
    assert result.idempotent_replay is True
    assert result.quality_summary.quality_status == "clean"
    assert result.records[0].transaction_id == transaction_id
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_changed_payload_with_same_idempotency_key_is_rejected() -> None:
    account = make_account()
    metadata = IngestionBatchMetadata(
        schema_version="1.0",
        source_system="synthetic-demo",
        source_account_id="DEMO-ACCOUNT-001",
    )
    batch = IngestionBatch(
        id=uuid4(),
        record_kind=IngestionRecordKind.TRANSACTION,
        source_system=metadata.source_system,
        schema_version=metadata.schema_version,
        idempotency_key="conflict-key",
        payload_sha256="0" * 64,
        status=IngestionBatchStatus.COMPLETED,
        source_count=1,
        accepted_count=1,
        rejected_count=0,
        duplicate_count=0,
        conflict_count=0,
        requested_by_user_id=uuid4(),
        correlation_id=uuid4(),
        version=1,
    )
    db = make_db(account, existing_batch=batch)

    with pytest.raises(HTTPException) as error:
        ingest_transactions(db, metadata, [valid_record()], make_principal(), "conflict-key")

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "IDEMPOTENCY_KEY_REUSED"
    db.add.assert_not_called()


def test_database_idempotency_race_returns_committed_exact_retry() -> None:
    account = make_account()
    metadata = IngestionBatchMetadata(
        schema_version="1.0",
        source_system="synthetic-demo",
        source_account_id="DEMO-ACCOUNT-001",
    )
    raw_records = [valid_record("TXN-RACE")]
    batch = IngestionBatch(
        id=uuid4(),
        record_kind=IngestionRecordKind.TRANSACTION,
        source_system=metadata.source_system,
        schema_version=metadata.schema_version,
        idempotency_key="race-key",
        payload_sha256=canonical_sha256(
            {"metadata": metadata.model_dump(), "records": raw_records}
        ),
        status=IngestionBatchStatus.COMPLETED,
        source_count=1,
        accepted_count=1,
        rejected_count=0,
        duplicate_count=0,
        conflict_count=0,
        requested_by_user_id=uuid4(),
        correlation_id=uuid4(),
        version=1,
    )
    evidence = IngestionRecord(
        id=uuid4(),
        batch_id=batch.id,
        row_number=1,
        source_record_id="TXN-RACE",
        payload=raw_records[0],
        payload_sha256=canonical_sha256(raw_records[0]),
        outcome=IngestionRecordOutcome.ACCEPTED,
        reason_codes=[],
        rejection_details=[],
        transaction_id=uuid4(),
        processed_at=datetime.now(UTC),
    )
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [account, None, batch]
    db.scalars.return_value.all.side_effect = [[], [evidence]]
    db.flush.side_effect = IntegrityError("insert", {}, Exception("synthetic race"))

    result = ingest_transactions(db, metadata, raw_records, make_principal(), "race-key")

    assert result.batch_id == batch.id
    assert result.idempotent_replay is True
    db.rollback.assert_called_once()
    db.commit.assert_not_called()


def test_same_batch_duplicates_and_conflicts_create_one_financial_fact() -> None:
    account = make_account()
    db = make_db(account)
    metadata = IngestionBatchMetadata(
        schema_version="1.0",
        source_system="synthetic-demo",
        source_account_id="DEMO-ACCOUNT-001",
    )
    first = valid_record("TXN-REPEATED")
    duplicate = {**first, "amount": "125.4500", "occurred_at": "2026-10-13T09:30:00+08:00"}
    conflict = {**first, "amount": "125.460000"}

    result = ingest_transactions(
        db,
        metadata,
        [first, duplicate, conflict],
        make_principal(),
        "same-batch-key",
    )

    assert result.accepted_count == 1
    assert result.duplicate_count == 1
    assert result.conflict_count == 1
    assert result.rejected_count == 0
    assert result.records[1].outcome == IngestionRecordOutcome.DUPLICATE
    assert result.records[2].outcome == IngestionRecordOutcome.CONFLICT
    assert result.quality_summary.issue_count == 2
    assert result.quality_summary.acceptance_rate_percent == "33.33"
    assert result.quality_summary.reason_counts == {
        "CONFLICTING_SOURCE_RECORD": 1,
        "DUPLICATE_SOURCE_RECORD": 1,
    }
    persisted = [item for call in db.add_all.call_args_list for item in call.args[0]]
    assert len([item for item in persisted if isinstance(item, FinancialTransaction)]) == 1


def test_prior_transaction_is_classified_as_duplicate_or_conflict() -> None:
    account = make_account()
    stored = FinancialTransaction(
        id=uuid4(),
        account_id=account.id,
        batch_id=uuid4(),
        source_record_id="TXN-STORED",
        source_reference="ORDER-1001",
        amount=Decimal("125.450000"),
        currency="USD",
        direction=MoneyDirection.DEBIT,
        status=TransactionStatus.POSTED,
        instrument_fingerprint="a" * 64,
        occurred_at=datetime(2026, 10, 13, 1, 30, tzinfo=UTC),
    )
    db = make_db(account, scalar_rows=[stored])
    metadata = IngestionBatchMetadata(
        schema_version="1.0",
        source_system="synthetic-demo",
        source_account_id="DEMO-ACCOUNT-001",
    )
    duplicate = valid_record("TXN-STORED")
    conflict = {**duplicate, "currency": "SGD"}

    result = ingest_transactions(
        db, metadata, [duplicate, conflict], make_principal(), "prior-batch-key"
    )

    assert result.accepted_count == 0
    assert result.duplicate_count == 1
    assert result.conflict_count == 1
    assert result.quality_summary.acceptance_rate_percent == "0.00"
    persisted = [item for call in db.add_all.call_args_list for item in call.args[0]]
    assert not any(isinstance(item, FinancialTransaction) for item in persisted)


def test_mixed_batch_persists_accepted_and_rejected_evidence() -> None:
    account = make_account()
    db = make_db(account)
    metadata = IngestionBatchMetadata(
        schema_version="1.0",
        source_system="synthetic-demo",
        source_account_id="DEMO-ACCOUNT-001",
    )
    invalid = {
        **valid_record("TXN-BAD"),
        "amount": "-10.00",
        "currency": "ZZZ",
        "occurred_at": "not-a-timestamp",
    }

    result = ingest_transactions(
        db,
        metadata,
        [valid_record(), invalid],
        make_principal(),
        "mixed-batch-key",
        original_filename="..\\synthetic-batch.csv",
    )

    assert result.status == IngestionBatchStatus.COMPLETED_WITH_ERRORS
    assert result.source_count == 2
    assert result.accepted_count == 1
    assert result.rejected_count == 1
    assert result.records[0].outcome == IngestionRecordOutcome.ACCEPTED
    assert result.records[1].reason_codes == [
        "INVALID_AMOUNT",
        "INVALID_CURRENCY",
        "INVALID_TIMESTAMP",
    ]
    assert all(detail.message for detail in result.records[1].rejection_details)

    batch = db.add.call_args.args[0]
    persisted = [item for call in db.add_all.call_args_list for item in call.args[0]]
    transactions = [item for item in persisted if isinstance(item, FinancialTransaction)]
    records = [item for item in persisted if isinstance(item, IngestionRecord)]
    assert isinstance(batch, IngestionBatch)
    assert batch.original_filename == "synthetic-batch.csv"
    assert batch.accepted_count == 1
    assert batch.rejected_count == 1
    assert len(transactions) == 1
    assert transactions[0].amount == Decimal("125.450000")
    assert len(records) == 2
    assert records[1].rejection_details[0]["code"] == "INVALID_AMOUNT"
    assert db.flush.call_count == 2
    db.commit.assert_called_once()


def test_unknown_account_rejects_batch_before_persistence() -> None:
    db = make_db(None)
    metadata = IngestionBatchMetadata(
        schema_version="1.0",
        source_system="unknown-source",
        source_account_id="UNKNOWN-1",
    )

    with pytest.raises(HTTPException) as error:
        ingest_transactions(db, metadata, [valid_record()], make_principal(), "unknown-account")

    assert error.value.status_code == 422
    assert error.value.detail["code"] == "ACCOUNT_NOT_FOUND"
    db.add.assert_not_called()


def test_database_failure_rolls_back_the_ingestion_transaction() -> None:
    db = make_db(make_account())
    db.commit.side_effect = SQLAlchemyError("synthetic database failure")
    metadata = IngestionBatchMetadata(
        schema_version="1.0",
        source_system="synthetic-demo",
        source_account_id="DEMO-ACCOUNT-001",
    )

    with pytest.raises(SQLAlchemyError, match="synthetic database failure"):
        ingest_transactions(db, metadata, [valid_record()], make_principal(), "database-failure")

    db.rollback.assert_called_once()


def test_csv_parser_rejects_bad_encoding_and_missing_columns() -> None:
    with pytest.raises(HTTPException) as encoding_error:
        parse_csv_records(b"\xff\xfe\x00")
    assert encoding_error.value.detail["code"] == "INVALID_CSV_ENCODING"

    with pytest.raises(HTTPException) as columns_error:
        parse_csv_records(b"source_record_id,amount\nTXN-1,1.00\n")
    assert columns_error.value.detail["code"] == "MISSING_CSV_COLUMNS"
    assert "occurred_at" in columns_error.value.detail["fields"]


def test_json_endpoint_queues_records_without_inline_processing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = object()
    app.dependency_overrides[get_current_principal] = lambda: make_principal()
    app.dependency_overrides[get_db] = lambda: db
    enqueue = MagicMock(return_value=(queued_job(), False))
    monkeypatch.setattr("ledgerguard.ingestion.enqueue_ingestion_job", enqueue)
    records = [valid_record(), {**valid_record("TXN-BAD"), "amount": 12.5}]

    response = client.post(
        "/api/v1/ingestion/transactions/json",
        headers={"Idempotency-Key": "json-endpoint-key"},
        json={
            "schema_version": "1.0",
            "source_system": "synthetic-demo",
            "source_account_id": "DEMO-ACCOUNT-001",
            "records": records,
        },
    )

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"
    assert response.json()["replayed"] is False
    assert enqueue.call_args.kwargs["records"] == records


def test_exact_endpoint_retry_returns_http_200_and_original_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = queued_job(replayed=True)
    app.dependency_overrides[get_current_principal] = lambda: make_principal()
    app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(
        "ledgerguard.ingestion.enqueue_ingestion_job", lambda *args, **kwargs: (job, True)
    )

    response = client.post(
        "/api/v1/ingestion/transactions/json",
        headers={"Idempotency-Key": "endpoint-retry-key"},
        json={
            "schema_version": "1.0",
            "source_system": "synthetic-demo",
            "source_account_id": "DEMO-ACCOUNT-001",
            "records": [valid_record("TXN-ENDPOINT-RETRY")],
        },
    )

    assert response.status_code == 200
    assert response.json()["job_id"] == str(job.job_id)
    assert response.json()["replayed"] is True


def test_ingestion_endpoint_requires_valid_idempotency_key(client: TestClient) -> None:
    app.dependency_overrides[get_current_principal] = lambda: make_principal()
    app.dependency_overrides[get_db] = lambda: make_db(make_account())
    request = {
        "schema_version": "1.0",
        "source_system": "synthetic-demo",
        "source_account_id": "DEMO-ACCOUNT-001",
        "records": [valid_record()],
    }

    missing = client.post("/api/v1/ingestion/transactions/json", json=request)
    malformed = client.post(
        "/api/v1/ingestion/transactions/json",
        headers={"Idempotency-Key": "contains spaces"},
        json=request,
    )

    assert missing.status_code == 422
    assert malformed.status_code == 422


def test_csv_endpoint_queues_raw_content_for_worker_parsing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = object()
    app.dependency_overrides[get_current_principal] = lambda: make_principal()
    app.dependency_overrides[get_db] = lambda: db
    enqueue = MagicMock(return_value=(queued_job(), False))
    monkeypatch.setattr("ledgerguard.ingestion.enqueue_ingestion_job", enqueue)
    csv_content = (
        "source_record_id,source_reference,amount,currency,direction,status,occurred_at,"
        "instrument_fingerprint\n"
        "CSV-1,ORDER-CSV-1,19.990000,USD,credit,posted,2026-10-13T02:00:00Z,\n"
    )

    response = client.post(
        "/api/v1/ingestion/transactions/csv",
        headers={"Idempotency-Key": "csv-endpoint-key"},
        data={
            "schema_version": "1.0",
            "source_system": "synthetic-demo",
            "source_account_id": "DEMO-ACCOUNT-001",
        },
        files={"file": ("synthetic.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"
    assert enqueue.call_args.kwargs["csv_content"] == csv_content.encode()


def test_auditor_cannot_ingest_transactions(client: TestClient) -> None:
    app.dependency_overrides[get_current_principal] = lambda: make_principal("auditor")

    response = client.post(
        "/api/v1/ingestion/transactions/json",
        headers={"Idempotency-Key": "auditor-denied-key"},
        json={
            "schema_version": "1.0",
            "source_system": "synthetic-demo",
            "source_account_id": "DEMO-ACCOUNT-001",
            "records": [valid_record()],
        },
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("filename", "accepted", "rejected", "status"),
    [
        ("transactions-valid-v1.json", 2, 0, IngestionBatchStatus.COMPLETED),
        (
            "transactions-mixed-v1.json",
            1,
            2,
            IngestionBatchStatus.COMPLETED_WITH_ERRORS,
        ),
    ],
)
def test_published_json_samples_have_deterministic_outcomes(
    filename: str,
    accepted: int,
    rejected: int,
    status: IngestionBatchStatus,
) -> None:
    payload = json.loads((SAMPLE_DATA / filename).read_text(encoding="utf-8"))
    metadata = IngestionBatchMetadata.model_validate(
        {key: payload[key] for key in ("schema_version", "source_system", "source_account_id")}
    )

    result = ingest_transactions(
        make_db(make_account()),
        metadata,
        payload["records"],
        make_principal(),
        f"sample-{filename}",
        original_filename=filename,
    )

    assert result.accepted_count == accepted
    assert result.rejected_count == rejected
    assert result.status == status
    if filename == "transactions-mixed-v1.json":
        assert result.records[1].reason_codes == ["INVALID_AMOUNT"]
        assert result.records[2].reason_codes == ["INVALID_CURRENCY", "INVALID_TIMESTAMP"]


def test_published_quality_sample_has_all_day_six_outcomes() -> None:
    payload = json.loads((SAMPLE_DATA / "transactions-quality-v1.json").read_text(encoding="utf-8"))
    metadata = IngestionBatchMetadata.model_validate(
        {key: payload[key] for key in ("schema_version", "source_system", "source_account_id")}
    )

    result = ingest_transactions(
        make_db(make_account()),
        metadata,
        payload["records"],
        make_principal(),
        "published-quality-sample",
        original_filename="transactions-quality-v1.json",
    )

    assert (
        result.accepted_count,
        result.rejected_count,
        result.duplicate_count,
        result.conflict_count,
    ) == (1, 1, 1, 1)
    assert result.quality_summary.acceptance_rate_percent == "25.00"
    assert result.quality_summary.reason_counts == {
        "CONFLICTING_SOURCE_RECORD": 1,
        "DUPLICATE_SOURCE_RECORD": 1,
        "INVALID_CURRENCY": 1,
    }


@pytest.mark.parametrize(
    ("filename", "accepted", "rejected"),
    [
        ("transactions-valid-v1.csv", 2, 0),
        ("transactions-mixed-v1.csv", 1, 2),
    ],
)
def test_published_csv_samples_use_the_same_validation_contract(
    filename: str, accepted: int, rejected: int
) -> None:
    records = parse_csv_records((SAMPLE_DATA / filename).read_bytes())
    metadata = IngestionBatchMetadata(
        schema_version="1.0",
        source_system="synthetic-demo",
        source_account_id="DEMO-ACCOUNT-001",
    )

    result = ingest_transactions(
        make_db(make_account()),
        metadata,
        records,
        make_principal(),
        f"sample-{filename}",
        original_filename=filename,
    )

    assert result.accepted_count == accepted
    assert result.rejected_count == rejected
