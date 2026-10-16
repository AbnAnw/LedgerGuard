"""Retry-safe transaction ingestion and evidence-backed data-quality controls."""

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

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ledgerguard.audit_service import append_audit_event
from ledgerguard.auth import AuthPrincipal, Permission, require_permissions
from ledgerguard.config import Settings, get_settings
from ledgerguard.db import get_db
from ledgerguard.jobs import BackgroundJobResponse, enqueue_ingestion_job
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
    "DUPLICATE_SOURCE_RECORD": (
        "source_record_id already exists with the same normalized transaction data."
    ),
    "CONFLICTING_SOURCE_RECORD": (
        "source_record_id already exists with different normalized transaction data."
    ),
}

IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$"


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


class BatchQualitySummary(BaseModel):
    quality_status: Literal["clean", "issues_detected"]
    issue_count: int
    acceptance_rate_percent: str
    reason_counts: dict[str, int]


class IngestionBatchResponse(BaseModel):
    batch_id: UUID
    schema_version: str
    status: IngestionBatchStatus
    source_count: int
    accepted_count: int
    rejected_count: int
    duplicate_count: int
    conflict_count: int
    idempotent_replay: bool
    quality_summary: BatchQualitySummary
    records: list[IngestionRecordResult]


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _normalized_record_signature(record: TransactionRecordV1) -> tuple[object, ...]:
    return (
        record.source_reference,
        record.decimal_amount,
        record.currency,
        record.direction,
        record.status,
        record.occurred_at,
        record.instrument_fingerprint,
    )


def _stored_transaction_signature(transaction: FinancialTransaction) -> tuple[object, ...]:
    occurred_at = transaction.occurred_at
    if occurred_at.tzinfo is not None and occurred_at.utcoffset() is not None:
        occurred_at = occurred_at.astimezone(UTC)
    return (
        transaction.source_reference,
        Decimal(transaction.amount),
        transaction.currency,
        transaction.direction,
        transaction.status,
        occurred_at,
        transaction.instrument_fingerprint,
    )


def _source_record_detail(
    code: Literal["DUPLICATE_SOURCE_RECORD", "CONFLICTING_SOURCE_RECORD"],
) -> dict[str, str]:
    return {"code": code, "field": "source_record_id", "message": REASON_MESSAGES[code]}


def _quality_summary(
    source_count: int,
    accepted_count: int,
    rejected_count: int,
    duplicate_count: int,
    conflict_count: int,
    records: list[IngestionRecordResult],
) -> BatchQualitySummary:
    issue_count = rejected_count + duplicate_count + conflict_count
    acceptance_rate = (
        (Decimal(accepted_count) * Decimal(100) / Decimal(source_count)).quantize(Decimal("0.01"))
        if source_count
        else Decimal("0.00")
    )
    reason_counts: dict[str, int] = {}
    for code in sorted(code for record in records for code in record.reason_codes):
        reason_counts[code] = reason_counts.get(code, 0) + 1
    return BatchQualitySummary(
        quality_status="clean" if issue_count == 0 else "issues_detected",
        issue_count=issue_count,
        acceptance_rate_percent=format(acceptance_rate, ".2f"),
        reason_counts=reason_counts,
    )


def _batch_response(
    batch: IngestionBatch,
    records: list[IngestionRecordResult],
    *,
    idempotent_replay: bool,
) -> IngestionBatchResponse:
    source_count = batch.source_count or 0
    return IngestionBatchResponse(
        batch_id=batch.id,
        schema_version=batch.schema_version,
        status=batch.status,
        source_count=source_count,
        accepted_count=batch.accepted_count,
        rejected_count=batch.rejected_count,
        duplicate_count=batch.duplicate_count,
        conflict_count=batch.conflict_count,
        idempotent_replay=idempotent_replay,
        quality_summary=_quality_summary(
            source_count,
            batch.accepted_count,
            batch.rejected_count,
            batch.duplicate_count,
            batch.conflict_count,
            records,
        ),
        records=records,
    )


def _replay_response(db: Session, batch: IngestionBatch) -> IngestionBatchResponse:
    stored_records = db.scalars(
        select(IngestionRecord)
        .where(IngestionRecord.batch_id == batch.id)
        .order_by(IngestionRecord.row_number)
    ).all()
    records = [
        IngestionRecordResult(
            row_number=record.row_number,
            source_record_id=record.source_record_id,
            outcome=record.outcome,
            reason_codes=list(record.reason_codes),
            rejection_details=[
                RejectionDetail.model_validate(detail) for detail in record.rejection_details
            ],
            transaction_id=record.transaction_id,
        )
        for record in stored_records
    ]
    return _batch_response(batch, records, idempotent_replay=True)


def _raise_idempotency_conflict() -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "IDEMPOTENCY_KEY_REUSED",
            "message": "Idempotency-Key was already used for a different batch payload.",
        },
    )


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
    idempotency_key: str,
    original_filename: str | None = None,
    audit_correlation_id: UUID | None = None,
    audit_job_id: UUID | None = None,
) -> IngestionBatchResponse:
    """Validate every row and atomically persist the batch, evidence, and accepted facts."""

    account = db.scalar(
        select(Account)
        .where(
            Account.source_system == metadata.source_system,
            Account.source_account_id == metadata.source_account_id,
            Account.status == AccountStatus.ACTIVE,
        )
        .with_for_update()
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
    payload = {"metadata": metadata.model_dump(), "records": raw_records}
    payload_sha256 = canonical_sha256(payload)
    existing_batch = db.scalar(
        select(IngestionBatch).where(
            IngestionBatch.source_system == metadata.source_system,
            IngestionBatch.idempotency_key == idempotency_key,
        )
    )
    if existing_batch is not None:
        if existing_batch.payload_sha256 != payload_sha256:
            _raise_idempotency_conflict()
        return _replay_response(db, existing_batch)

    validation_results: list[
        tuple[TransactionRecordV1 | None, list[str], list[dict[str, str]]]
    ] = []
    valid_source_ids: set[str] = set()
    for raw_record in raw_records:
        try:
            validated_record = TransactionRecordV1.model_validate(raw_record)
        except ValidationError as error:
            codes, details = rejection_details(error)
            validation_results.append((None, codes, details))
        else:
            validation_results.append((validated_record, [], []))
            valid_source_ids.add(validated_record.source_record_id)

    stored_transactions = (
        db.scalars(
            select(FinancialTransaction).where(
                FinancialTransaction.account_id == account.id,
                FinancialTransaction.source_record_id.in_(valid_source_ids),
            )
        ).all()
        if valid_source_ids
        else []
    )
    stored_by_source_id = {
        transaction.source_record_id: transaction for transaction in stored_transactions
    }

    batch_id = uuid4()
    batch = IngestionBatch(
        id=batch_id,
        record_kind=IngestionRecordKind.TRANSACTION,
        source_system=metadata.source_system,
        schema_version=metadata.schema_version,
        idempotency_key=idempotency_key,
        payload_sha256=payload_sha256,
        original_filename=_safe_filename(original_filename),
        status=IngestionBatchStatus.PROCESSING,
        source_count=len(raw_records),
        accepted_count=0,
        rejected_count=0,
        duplicate_count=0,
        conflict_count=0,
        requested_by_user_id=principal.user_id,
        correlation_id=audit_correlation_id or uuid4(),
        started_at=now,
        version=1,
    )

    financial_facts: list[FinancialTransaction] = []
    evidence_records: list[IngestionRecord] = []
    results: list[IngestionRecordResult] = []
    accepted_count = 0
    rejected_count = 0
    duplicate_count = 0
    conflict_count = 0
    accepted_in_batch: dict[str, TransactionRecordV1] = {}

    for row_number, (raw_record, validation) in enumerate(
        zip(raw_records, validation_results, strict=True), start=1
    ):
        record, reason_codes, details = validation
        record_id = uuid4()
        transaction_id: UUID | None = None
        outcome = IngestionRecordOutcome.ACCEPTED
        source_record_id = raw_record.get("source_record_id")
        safe_source_record_id = (
            source_record_id
            if isinstance(source_record_id, str) and len(source_record_id) <= 200
            else None
        )

        if record is None:
            outcome = IngestionRecordOutcome.REJECTED
            rejected_count += 1
        else:
            prior_record = accepted_in_batch.get(record.source_record_id)
            prior_transaction = stored_by_source_id.get(record.source_record_id)
            prior_signature = (
                _normalized_record_signature(prior_record)
                if prior_record is not None
                else (
                    _stored_transaction_signature(prior_transaction)
                    if prior_transaction is not None
                    else None
                )
            )
            safe_source_record_id = record.source_record_id
            if prior_signature is not None:
                current_signature = _normalized_record_signature(record)
                if current_signature == prior_signature:
                    outcome = IngestionRecordOutcome.DUPLICATE
                    reason_codes = ["DUPLICATE_SOURCE_RECORD"]
                    details = [_source_record_detail("DUPLICATE_SOURCE_RECORD")]
                    duplicate_count += 1
                else:
                    outcome = IngestionRecordOutcome.CONFLICT
                    reason_codes = ["CONFLICTING_SOURCE_RECORD"]
                    details = [_source_record_detail("CONFLICTING_SOURCE_RECORD")]
                    conflict_count += 1
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
                accepted_in_batch[record.source_record_id] = record
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
    batch.duplicate_count = duplicate_count
    batch.conflict_count = conflict_count
    batch.status = (
        IngestionBatchStatus.COMPLETED_WITH_ERRORS
        if rejected_count or duplicate_count or conflict_count
        else IngestionBatchStatus.COMPLETED
    )
    batch.finished_at = now
    try:
        db.add(batch)
        db.flush()
    except IntegrityError:
        db.rollback()
        concurrent_batch = db.scalar(
            select(IngestionBatch).where(
                IngestionBatch.source_system == metadata.source_system,
                IngestionBatch.idempotency_key == idempotency_key,
            )
        )
        if concurrent_batch is not None:
            if concurrent_batch.payload_sha256 != payload_sha256:
                _raise_idempotency_conflict()
            return _replay_response(db, concurrent_batch)
        raise

    try:
        if financial_facts:
            db.add_all(financial_facts)
            db.flush()
        db.add_all(evidence_records)
        append_audit_event(
            db,
            action="transaction.ingestion.completed",
            target_type="transaction_batch",
            target_id=batch.id,
            actor_user_id=principal.user_id,
            correlation_id=batch.correlation_id,
            job_id=audit_job_id,
            after_state={
                "status": batch.status.value,
                "accepted_count": accepted_count,
                "rejected_count": rejected_count,
                "duplicate_count": duplicate_count,
                "conflict_count": conflict_count,
            },
            metadata={
                "schema_version": "audit-v1",
                "source_system": metadata.source_system,
                "transaction_ids": [str(item.id) for item in financial_facts],
            },
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise

    return _batch_response(batch, results, idempotent_replay=False)


router = APIRouter(prefix="/api/v1/ingestion/transactions", tags=["transaction ingestion"])


@router.post("/json", response_model=BackgroundJobResponse, status_code=status.HTTP_202_ACCEPTED)
def ingest_json_transactions(
    request: TransactionJsonBatchRequest,
    response: Response,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", pattern=IDEMPOTENCY_KEY_PATTERN)
    ],
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.INGESTION_WRITE))],
    db: Annotated[Session, Depends(get_db)],
) -> BackgroundJobResponse:
    result, replayed = enqueue_ingestion_job(
        db,
        source_system=request.source_system,
        source_account_id=request.source_account_id,
        schema_version=request.schema_version,
        idempotency_key=idempotency_key,
        format_name="json",
        records=request.records,
        csv_content=None,
        original_filename=None,
        principal=principal,
    )
    if replayed:
        response.status_code = status.HTTP_200_OK
    return result


@router.post("/csv", response_model=BackgroundJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_csv_transactions(
    response: Response,
    schema_version: Annotated[Literal["1.0"], Form()],
    source_system: Annotated[
        str, Form(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    ],
    source_account_id: Annotated[
        str,
        Form(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"),
    ],
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", pattern=IDEMPOTENCY_KEY_PATTERN)
    ],
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.INGESTION_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BackgroundJobResponse:
    content = await file.read(settings.ingestion_max_upload_bytes + 1)
    if len(content) > settings.ingestion_max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "UPLOAD_TOO_LARGE", "message": "CSV exceeds the configured limit."},
        )
    result, replayed = enqueue_ingestion_job(
        db,
        source_system=source_system,
        source_account_id=source_account_id,
        schema_version=schema_version,
        idempotency_key=idempotency_key,
        format_name="csv",
        records=None,
        csv_content=content,
        original_filename=file.filename,
        principal=principal,
    )
    if replayed:
        response.status_code = status.HTTP_200_OK
    return result
