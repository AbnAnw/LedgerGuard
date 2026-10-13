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
from sqlalchemy.exc import SQLAlchemyError
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
from ledgerguard.main import app
from ledgerguard.models import (
    Account,
    AccountStatus,
    AccountType,
    FinancialTransaction,
    IngestionBatch,
    IngestionBatchStatus,
    IngestionRecord,
    IngestionRecordOutcome,
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


def make_db(account: Account | None = None) -> MagicMock:
    db = MagicMock(spec=Session)
    db.scalar.return_value = account
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
        ingest_transactions(db, metadata, [valid_record()], make_principal())

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
        ingest_transactions(db, metadata, [valid_record()], make_principal())

    db.rollback.assert_called_once()


def test_csv_parser_rejects_bad_encoding_and_missing_columns() -> None:
    with pytest.raises(HTTPException) as encoding_error:
        parse_csv_records(b"\xff\xfe\x00")
    assert encoding_error.value.detail["code"] == "INVALID_CSV_ENCODING"

    with pytest.raises(HTTPException) as columns_error:
        parse_csv_records(b"source_record_id,amount\nTXN-1,1.00\n")
    assert columns_error.value.detail["code"] == "MISSING_CSV_COLUMNS"
    assert "occurred_at" in columns_error.value.detail["fields"]


def test_json_endpoint_returns_deterministic_record_results(client: TestClient) -> None:
    db = make_db(make_account())
    app.dependency_overrides[get_current_principal] = lambda: make_principal()
    app.dependency_overrides[get_db] = lambda: db

    response = client.post(
        "/api/v1/ingestion/transactions/json",
        json={
            "schema_version": "1.0",
            "source_system": "synthetic-demo",
            "source_account_id": "DEMO-ACCOUNT-001",
            "records": [valid_record(), {**valid_record("TXN-BAD"), "amount": 12.5}],
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["accepted_count"] == 1
    assert payload["rejected_count"] == 1
    assert payload["records"][1]["reason_codes"] == ["INVALID_AMOUNT"]


def test_csv_endpoint_uses_same_validation_pipeline(client: TestClient) -> None:
    db = make_db(make_account())
    app.dependency_overrides[get_current_principal] = lambda: make_principal()
    app.dependency_overrides[get_db] = lambda: db
    csv_content = (
        "source_record_id,source_reference,amount,currency,direction,status,occurred_at,"
        "instrument_fingerprint\n"
        "CSV-1,ORDER-CSV-1,19.990000,USD,credit,posted,2026-10-13T02:00:00Z,\n"
    )

    response = client.post(
        "/api/v1/ingestion/transactions/csv",
        data={
            "schema_version": "1.0",
            "source_system": "synthetic-demo",
            "source_account_id": "DEMO-ACCOUNT-001",
        },
        files={"file": ("synthetic.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 201, response.text
    assert response.json()["accepted_count"] == 1
    assert response.json()["status"] == "completed"


def test_auditor_cannot_ingest_transactions(client: TestClient) -> None:
    app.dependency_overrides[get_current_principal] = lambda: make_principal("auditor")

    response = client.post(
        "/api/v1/ingestion/transactions/json",
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
        original_filename=filename,
    )

    assert result.accepted_count == accepted
    assert result.rejected_count == rejected
    assert result.status == status
    if filename == "transactions-mixed-v1.json":
        assert result.records[1].reason_codes == ["INVALID_AMOUNT"]
        assert result.records[2].reason_codes == ["INVALID_CURRENCY", "INVALID_TIMESTAMP"]


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
        original_filename=filename,
    )

    assert result.accepted_count == accepted
    assert result.rejected_count == rejected
