"""Synchronous Day 5 transaction ingestion and record-level validation."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ledgerguard.auth import AuthPrincipal, Permission, require_permissions
from ledgerguard.config import Settings, get_settings
from ledgerguard.db import get_db
from ledgerguard.models import (
    Account,
    AccountStatus,
    FinancialTransaction,
    IngestionBatch,
    IngestionBatchStatus,
    IngestionRecord,
    IngestionRecordKind,
    IngestionRecordOutcome,
    MoneyDirection,
    TransactionStatus,
)

SCHEMA_VERSION = "1.0"
SUPPORTED_CURRENCIES = frozenset({"AUD", "EUR", "GBP", "MVR", "MYR", "SGD", "USD"})
MAX_BATCH_RECORDS = 10_000
REQUIRED_CSV_FIELDS = frozenset(
    {
        "source_record_id",
        "source_reference",
        "amount",
        "currency",
        "direction",
        "status",
        "occurred_at",
    }
)

FIELD_REASON_CODES = {
    "source_record_id": "INVALID_SOURCE_RECORD_ID",
    "source_reference": "INVALID_SOURCE_REFERENCE",
    "amount": "INVALID_AMOUNT",
    "currency": "INVALID_CURRENCY",
    "direction": "INVALID_DIRECTION",
    "status": "INVALID_STATUS",
    "occurred_at": "INVALID_TIMESTAMP",
    "instrument_fingerprint": "INVALID_INSTRUMENT_FINGERPRINT",
}
REASON_MESSAGES = {
    "MISSING_REQUIRED_FIELD": "A required field is missing.",
    "UNSUPPORTED_FIELD": "The record contains a field outside schema version 1.0.",
    "INVALID_SOURCE_RECORD_ID": "source_record_id must use the published identifier format.",
    "INVALID_SOURCE_REFERENCE": "source_reference must use the published identifier format.",
    "INVALID_AMOUNT": (
        "amount must be a positive decimal string with at most 14 integer and 6 fractional digits."
    ),
    "INVALID_CURRENCY": "currency must be an allowed uppercase ISO 4217 code.",
    "INVALID_DIRECTION": "direction must be debit or credit.",
    "INVALID_STATUS": "status must be pending, posted, voided, or reversed.",
    "INVALID_TIMESTAMP": "occurred_at must be an ISO 8601 timestamp with an explicit UTC offset.",
    "INVALID_INSTRUMENT_FINGERPRINT": (
        "instrument_fingerprint must be empty or 64 lowercase hexadecimal characters."
    ),
    "INVALID_RECORD": "The record does not conform to transaction schema version 1.0.",
}


class IngestionBatchMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["1.0"]
    source_system: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    source_account_id: str = Field(
        min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"
    )


class TransactionJsonBatchRequest(IngestionBatchMetadata):
    records: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_BATCH_RECORDS)


class TransactionRecordV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_record_id: str = Field(
        min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"
    )
    source_reference: str = Field(
        min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"
    )
    amount: str
    currency: str
    direction: MoneyDirection
    status: TransactionStatus
    occurred_at: datetime
    instrument_fingerprint: str | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def require_decimal_string(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("amount must be a decimal string")
        return value

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: str) -> str:
        if not re.fullmatch(r"(?:0|[1-9]\d{0,13})(?:\.\d{1,6})?", value):
            raise ValueError("amount has invalid precision or format")
        if Decimal(value) <= 0:
            raise ValueError("amount must be positive")
        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if value not in SUPPORTED_CURRENCIES:
            raise ValueError("currency is not supported")
        return value

    @field_validator("occurred_at", mode="before")
    @classmethod
    def require_timestamp_string(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("occurred_at must be an ISO 8601 string")
        return value

    @field_validator("occurred_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a UTC offset")
        return value.astimezone(UTC)

    @field_validator("instrument_fingerprint", mode="before")
    @classmethod
    def normalize_optional_fingerprint(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("instrument_fingerprint")
    @classmethod
    def validate_fingerprint(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("instrument_fingerprint has invalid format")
        return value

    @property
    def decimal_amount(self) -> Decimal:
        return Decimal(self.amount)


class RejectionDetail(BaseModel):
    code: str
    field: str
    message: str


class IngestionRecordResult(BaseModel):
    row_number: int
    source_record_id: str | None
    outcome: IngestionRecordOutcome
    reason_codes: list[str]
    rejection_details: list[RejectionDetail]
    transaction_id: UUID | None


class IngestionBatchResponse(BaseModel):
    batch_id: UUID
    schema_version: str
    status: IngestionBatchStatus
    source_count: int
    accepted_count: int
    rejected_count: int
    records: list[IngestionRecordResult]


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def rejection_details(error: ValidationError) -> tuple[list[str], list[dict[str, str]]]:
    codes: list[str] = []
    details: list[dict[str, str]] = []
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        field = str(item["loc"][-1]) if item["loc"] else "record"
        error_type = str(item["type"])
        if error_type == "missing":
            code = "MISSING_REQUIRED_FIELD"
        elif error_type == "extra_forbidden":
            code = "UNSUPPORTED_FIELD"
        else:
            code = FIELD_REASON_CODES.get(field, "INVALID_RECORD")
        if code not in codes:
            codes.append(code)
        details.append({"code": code, "field": field, "message": REASON_MESSAGES[code]})
    return codes, details


def parse_csv_records(content: bytes) -> list[dict[str, Any]]:
    try:
        text = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_CSV_ENCODING", "message": "CSV must use UTF-8 encoding."},
        ) from error

    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = set(reader.fieldnames or [])
    missing = sorted(REQUIRED_CSV_FIELDS - headers)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "MISSING_CSV_COLUMNS",
                "message": "CSV is missing required columns.",
                "fields": missing,
            },
        )

    records: list[dict[str, Any]] = []
    for row in reader:
        record = {key: value for key, value in row.items() if key is not None}
        if None in row:
            record["_extra_columns"] = row[None]
        records.append(record)
    if not records:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "EMPTY_BATCH", "message": "CSV must contain at least one record."},
        )
    if len(records) > MAX_BATCH_RECORDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "BATCH_TOO_LARGE", "message": "Batch exceeds 10,000 records."},
        )
    return records


def _safe_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    normalized = filename.replace("\\", "/")
    return PurePosixPath(normalized).name[:255]


def ingest_transactions(
    db: Session,
    metadata: IngestionBatchMetadata,
    raw_records: list[dict[str, Any]],
    principal: AuthPrincipal,
    original_filename: str | None = None,
) -> IngestionBatchResponse:
    """Validate every row and atomically persist the batch, evidence, and accepted facts."""

    account = db.scalar(
        select(Account).where(
            Account.source_system == metadata.source_system,
            Account.source_account_id == metadata.source_account_id,
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

    now = datetime.now(UTC)
    batch_id = uuid4()
    payload = {"metadata": metadata.model_dump(), "records": raw_records}
    batch = IngestionBatch(
        id=batch_id,
        record_kind=IngestionRecordKind.TRANSACTION,
        source_system=metadata.source_system,
        schema_version=metadata.schema_version,
        idempotency_key=f"day5-generated-{uuid4()}",
        payload_sha256=canonical_sha256(payload),
        original_filename=_safe_filename(original_filename),
        status=IngestionBatchStatus.PROCESSING,
        source_count=len(raw_records),
        accepted_count=0,
        rejected_count=0,
        duplicate_count=0,
        conflict_count=0,
        requested_by_user_id=principal.user_id,
        correlation_id=uuid4(),
        started_at=now,
        version=1,
    )

    financial_facts: list[FinancialTransaction] = []
    evidence_records: list[IngestionRecord] = []
    results: list[IngestionRecordResult] = []
    accepted_count = 0
    rejected_count = 0

    for row_number, raw_record in enumerate(raw_records, start=1):
        record_id = uuid4()
        transaction_id: UUID | None = None
        reason_codes: list[str] = []
        details: list[dict[str, str]] = []
        outcome = IngestionRecordOutcome.ACCEPTED
        source_record_id = raw_record.get("source_record_id")
        safe_source_record_id = (
            source_record_id
            if isinstance(source_record_id, str) and len(source_record_id) <= 200
            else None
        )

        try:
            record = TransactionRecordV1.model_validate(raw_record)
        except ValidationError as error:
            outcome = IngestionRecordOutcome.REJECTED
            reason_codes, details = rejection_details(error)
            rejected_count += 1
        else:
            transaction_id = uuid4()
            financial_facts.append(
                FinancialTransaction(
                    id=transaction_id,
                    account_id=account.id,
                    batch_id=batch_id,
                    source_record_id=record.source_record_id,
                    source_reference=record.source_reference,
                    amount=record.decimal_amount,
                    currency=record.currency,
                    direction=record.direction,
                    status=record.status,
                    instrument_fingerprint=record.instrument_fingerprint,
                    occurred_at=record.occurred_at,
                )
            )
            safe_source_record_id = record.source_record_id
            accepted_count += 1

        evidence_records.append(
            IngestionRecord(
                id=record_id,
                batch_id=batch_id,
                row_number=row_number,
                source_record_id=safe_source_record_id,
                payload=raw_record,
                payload_sha256=canonical_sha256(raw_record),
                outcome=outcome,
                reason_codes=reason_codes,
                rejection_details=details,
                transaction_id=transaction_id,
                processed_at=now,
            )
        )
        results.append(
            IngestionRecordResult(
                row_number=row_number,
                source_record_id=safe_source_record_id,
                outcome=outcome,
                reason_codes=reason_codes,
                rejection_details=[RejectionDetail.model_validate(item) for item in details],
                transaction_id=transaction_id,
            )
        )

    batch.accepted_count = accepted_count
    batch.rejected_count = rejected_count
    batch.status = (
        IngestionBatchStatus.COMPLETED_WITH_ERRORS
        if rejected_count
        else IngestionBatchStatus.COMPLETED
    )
    batch.finished_at = now
    try:
        # Explicit flush boundaries preserve foreign-key ordering even though the
        # models intentionally expose UUID identifiers rather than ORM relationships.
        db.add(batch)
        db.flush()
        if financial_facts:
            db.add_all(financial_facts)
            db.flush()
        db.add_all(evidence_records)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise

    return IngestionBatchResponse(
        batch_id=batch_id,
        schema_version=metadata.schema_version,
        status=batch.status,
        source_count=len(raw_records),
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        records=results,
    )


router = APIRouter(prefix="/api/v1/ingestion/transactions", tags=["transaction ingestion"])


@router.post("/json", response_model=IngestionBatchResponse, status_code=status.HTTP_201_CREATED)
def ingest_json_transactions(
    request: TransactionJsonBatchRequest,
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.INGESTION_WRITE))],
    db: Annotated[Session, Depends(get_db)],
) -> IngestionBatchResponse:
    metadata = IngestionBatchMetadata.model_validate(request.model_dump(exclude={"records"}))
    return ingest_transactions(db, metadata, request.records, principal)


@router.post("/csv", response_model=IngestionBatchResponse, status_code=status.HTTP_201_CREATED)
async def ingest_csv_transactions(
    schema_version: Annotated[Literal["1.0"], Form()],
    source_system: Annotated[
        str, Form(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    ],
    source_account_id: Annotated[
        str,
        Form(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"),
    ],
    file: Annotated[UploadFile, File()],
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.INGESTION_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> IngestionBatchResponse:
    content = await file.read(settings.ingestion_max_upload_bytes + 1)
    if len(content) > settings.ingestion_max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "UPLOAD_TOO_LARGE", "message": "CSV exceeds the configured limit."},
        )
    records = parse_csv_records(content)
    metadata = IngestionBatchMetadata(
        schema_version=schema_version,
        source_system=source_system,
        source_account_id=source_account_id,
    )
    return ingest_transactions(db, metadata, records, principal, file.filename)
