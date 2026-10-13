"""SQLAlchemy model implementing the Day 2 domain contract."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def enum_values(enum_class: type[Enum]) -> list[str]:
    """Persist string enum values rather than Python member names."""

    return [str(member.value) for member in enum_class]


def enum_column(enum_class: type[Enum], name: str) -> sa.Enum:
    """Build a migration-friendly VARCHAR enum with a database check constraint."""

    return sa.Enum(
        enum_class,
        values_callable=enum_values,
        name=name,
        native_enum=False,
        create_constraint=True,
    )


class Base(DeclarativeBase):
    """Declarative model base."""


class UuidPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class MutableMixin:
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="1")


class UserStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    LOCKED = "locked"


class AccountType(str, Enum):
    MERCHANT = "merchant"
    CLEARING = "clearing"
    INTERNAL = "internal"


class AccountStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class IngestionRecordKind(str, Enum):
    TRANSACTION = "transaction"
    SETTLEMENT = "settlement"


class IngestionBatchStatus(str, Enum):
    RECEIVED = "received"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IngestionRecordOutcome(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"


class MoneyDirection(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class TransactionStatus(str, Enum):
    PENDING = "pending"
    POSTED = "posted"
    VOIDED = "voided"
    REVERSED = "reversed"


class SettlementStatus(str, Enum):
    RECEIVED = "received"
    CONFIRMED = "confirmed"
    VOIDED = "voided"
    REVERSED = "reversed"


class ReconciliationRunStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReconciliationClassification(str, Enum):
    EXACT_MATCH = "exact_match"
    PARTIAL_MATCH = "partial_match"
    MISSING_SETTLEMENT = "missing_settlement"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    UNEXPLAINED_SETTLEMENT = "unexplained_settlement"


class ReconciliationReviewStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class ReconciliationItemRole(str, Enum):
    MATCHED = "matched"
    CANDIDATE = "candidate"


class FraudRuleType(str, Enum):
    VELOCITY = "velocity"
    UNUSUAL_AMOUNT = "unusual_amount"
    REPEATED_FAILURE = "repeated_failure"
    DUPLICATE_INSTRUMENT = "duplicate_instrument"
    SUSPICIOUS_TIMING = "suspicious_timing"


class AlertSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RuleVersionStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class AlertStatus(str, Enum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    CLOSED = "closed"
    DISMISSED = "dismissed"


class CaseStatus(str, Enum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    REOPENED = "reopened"


class CasePriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AuditActorType(str, Enum):
    USER = "user"
    SYSTEM = "system"
    ANONYMOUS = "anonymous"


class AuditResult(str, Enum):
    SUCCESS = "success"
    DENIED = "denied"
    FAILURE = "failure"


money_type = sa.Numeric(20, 6)
currency_check = "currency ~ '^[A-Z]{3}$'"


class User(UuidPrimaryKeyMixin, TimestampMixin, MutableMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        sa.CheckConstraint("failed_login_count >= 0", name="ck_users_failed_login_nonnegative"),
        sa.CheckConstraint("version > 0", name="ck_users_version_positive"),
        sa.Index("ix_users_status", "status"),
    )

    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        enum_column(UserStatus, "user_status"), nullable=False, default=UserStatus.ACTIVE
    )
    failed_login_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class Role(Base):
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    description: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class UserRole(UuidPrimaryKeyMixin, Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by_user_id IS NULL)",
            name="ck_user_roles_revoke_pair",
        ),
        sa.Index(
            "uq_user_roles_active",
            "user_id",
            "role_code",
            unique=True,
            postgresql_where=sa.text("revoked_at IS NULL"),
        ),
        sa.Index(
            "ix_user_roles_role_active",
            "role_code",
            postgresql_where=sa.text("revoked_at IS NULL"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="RESTRICT"))
    role_code: Mapped[str] = mapped_column(sa.ForeignKey("roles.code", ondelete="RESTRICT"))
    granted_by_user_id: Mapped[UUID] = mapped_column(sa.ForeignKey("users.id", ondelete="RESTRICT"))
    granted_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    revoked_by_user_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class AuthSession(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        sa.CheckConstraint("expires_at > created_at", name="ck_auth_sessions_expiry_after_create"),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_auth_sessions_revoked_after_create",
        ),
        sa.Index("ix_auth_sessions_user_expires", "user_id", "expires_at"),
        sa.Index(
            "ix_auth_sessions_active_expiry",
            "expires_at",
            postgresql_where=sa.text("revoked_at IS NULL"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_digest: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Account(UuidPrimaryKeyMixin, TimestampMixin, MutableMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        sa.UniqueConstraint("source_system", "source_account_id", name="uq_accounts_source"),
        sa.CheckConstraint(
            "default_currency IS NULL OR default_currency ~ '^[A-Z]{3}$'",
            name="ck_accounts_currency",
        ),
        sa.CheckConstraint("version > 0", name="ck_accounts_version_positive"),
        sa.Index("ix_accounts_status", "status"),
    )

    source_system: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    source_account_id: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(
        enum_column(AccountType, "account_type"), nullable=False
    )
    default_currency: Mapped[str | None] = mapped_column(sa.String(3))
    status: Mapped[AccountStatus] = mapped_column(
        enum_column(AccountStatus, "account_status"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class IngestionBatch(UuidPrimaryKeyMixin, TimestampMixin, MutableMixin, Base):
    __tablename__ = "ingestion_batches"
    __table_args__ = (
        sa.UniqueConstraint(
            "source_system", "idempotency_key", name="uq_ingestion_batches_idempotency"
        ),
        sa.CheckConstraint("payload_sha256 ~ '^[0-9a-f]{64}$'", name="ck_batches_payload_hash"),
        sa.CheckConstraint(
            "source_count IS NULL OR source_count >= 0", name="ck_batches_source_count"
        ),
        sa.CheckConstraint(
            "accepted_count >= 0 AND rejected_count >= 0 AND duplicate_count >= 0 "
            "AND conflict_count >= 0",
            name="ck_batches_result_counts",
        ),
        sa.CheckConstraint("version > 0", name="ck_batches_version_positive"),
        sa.Index("ix_ingestion_batches_status_created", "status", sa.desc("created_at")),
        sa.Index(
            "ix_ingestion_batches_requester_created",
            "requested_by_user_id",
            sa.desc("created_at"),
        ),
    )

    record_kind: Mapped[IngestionRecordKind] = mapped_column(
        enum_column(IngestionRecordKind, "ingestion_record_kind"), nullable=False
    )
    source_system: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(sa.String(255))
    status: Mapped[IngestionBatchStatus] = mapped_column(
        enum_column(IngestionBatchStatus, "ingestion_batch_status"), nullable=False
    )
    source_count: Mapped[int | None] = mapped_column(sa.Integer)
    accepted_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")
    rejected_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")
    duplicate_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")
    conflict_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")
    requested_by_user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    correlation_id: Mapped[UUID] = mapped_column(sa.Uuid, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(sa.String(80))
    failure_detail: Mapped[str | None] = mapped_column(sa.Text)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class FinancialTransaction(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        sa.UniqueConstraint("account_id", "source_record_id", name="uq_transactions_source"),
        sa.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        sa.CheckConstraint(currency_check, name="ck_transactions_currency"),
        sa.CheckConstraint(
            "reversal_of_transaction_id IS NULL OR reversal_of_transaction_id <> id",
            name="ck_transactions_not_self_reversal",
        ),
        sa.Index("ix_transactions_account_occurred", "account_id", sa.desc("occurred_at")),
        sa.Index(
            "ix_transactions_reconciliation",
            "account_id",
            "source_reference",
            "currency",
            "amount",
            "occurred_at",
        ),
        sa.Index(
            "ix_transactions_instrument_time",
            "instrument_fingerprint",
            "occurred_at",
            postgresql_where=sa.text("instrument_fingerprint IS NOT NULL"),
        ),
    )

    account_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("ingestion_batches.id", ondelete="RESTRICT"), nullable=False
    )
    source_record_id: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    source_reference: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    amount: Mapped[Any] = mapped_column(money_type, nullable=False)
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False)
    direction: Mapped[MoneyDirection] = mapped_column(
        enum_column(MoneyDirection, "money_direction"), nullable=False
    )
    status: Mapped[TransactionStatus] = mapped_column(
        enum_column(TransactionStatus, "transaction_status"), nullable=False
    )
    reversal_of_transaction_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("transactions.id", ondelete="RESTRICT")
    )
    instrument_fingerprint: Mapped[str | None] = mapped_column(sa.String(64))
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class Settlement(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "settlements"
    __table_args__ = (
        sa.UniqueConstraint("account_id", "source_record_id", name="uq_settlements_source"),
        sa.CheckConstraint("amount > 0", name="ck_settlements_amount_positive"),
        sa.CheckConstraint(currency_check, name="ck_settlements_currency"),
        sa.Index("ix_settlements_account_settled", "account_id", sa.desc("settled_at")),
        sa.Index(
            "ix_settlements_reconciliation",
            "account_id",
            "source_reference",
            "currency",
            "amount",
            "settled_at",
        ),
    )

    account_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("ingestion_batches.id", ondelete="RESTRICT"), nullable=False
    )
    source_record_id: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    source_reference: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    provider: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    amount: Mapped[Any] = mapped_column(money_type, nullable=False)
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False)
    status: Mapped[SettlementStatus] = mapped_column(
        enum_column(SettlementStatus, "settlement_status"), nullable=False
    )
    settled_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class IngestionRecord(UuidPrimaryKeyMixin, Base):
    __tablename__ = "ingestion_records"
    __table_args__ = (
        sa.UniqueConstraint("batch_id", "row_number", name="uq_ingestion_records_row"),
        sa.CheckConstraint("row_number > 0", name="ck_ingestion_records_row_positive"),
        sa.CheckConstraint("payload_sha256 ~ '^[0-9a-f]{64}$'", name="ck_records_payload_hash"),
        sa.CheckConstraint(
            "NOT (transaction_id IS NOT NULL AND settlement_id IS NOT NULL)",
            name="ck_records_single_fact",
        ),
        sa.Index("ix_ingestion_records_batch_outcome", "batch_id", "outcome"),
        sa.Index("ix_ingestion_records_source_record", "source_record_id"),
    )

    batch_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("ingestion_batches.id", ondelete="RESTRICT"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(sa.String(200))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    outcome: Mapped[IngestionRecordOutcome] = mapped_column(
        enum_column(IngestionRecordOutcome, "ingestion_record_outcome"), nullable=False
    )
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    rejection_details: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    transaction_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("transactions.id", ondelete="RESTRICT"), unique=True
    )
    settlement_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("settlements.id", ondelete="RESTRICT"), unique=True
    )
    processed_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class ReconciliationRun(UuidPrimaryKeyMixin, TimestampMixin, MutableMixin, Base):
    __tablename__ = "reconciliation_runs"
    __table_args__ = (
        sa.CheckConstraint("replay_key ~ '^[0-9a-f]{64}$'", name="ck_runs_replay_key"),
        sa.CheckConstraint("version > 0", name="ck_runs_version_positive"),
        sa.Index("ix_runs_account_created", "account_id", sa.desc("created_at")),
        sa.Index("ix_runs_status_created", "status", "created_at"),
    )

    account_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    algorithm_version: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_cutoff_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    replay_key: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    status: Mapped[ReconciliationRunStatus] = mapped_column(
        enum_column(ReconciliationRunStatus, "reconciliation_run_status"), nullable=False
    )
    requested_by_user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    correlation_id: Mapped[UUID] = mapped_column(sa.Uuid, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(sa.String(80))
    failure_detail: Mapped[str | None] = mapped_column(sa.Text)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class ReconciliationResult(UuidPrimaryKeyMixin, TimestampMixin, MutableMixin, Base):
    __tablename__ = "reconciliation_results"
    __table_args__ = (
        sa.CheckConstraint(currency_check, name="ck_results_currency"),
        sa.CheckConstraint(
            "transaction_total >= 0 AND settlement_total >= 0",
            name="ck_results_totals_nonnegative",
        ),
        sa.CheckConstraint("evidence_sha256 ~ '^[0-9a-f]{64}$'", name="ck_results_evidence_hash"),
        sa.CheckConstraint(
            "(reviewed_at IS NULL) = (reviewed_by_user_id IS NULL)",
            name="ck_results_review_pair",
        ),
        sa.CheckConstraint("version > 0", name="ck_results_version_positive"),
        sa.Index("ix_results_run_classification", "run_id", "classification"),
        sa.Index("ix_results_review_created", "review_status", "created_at"),
        sa.Index(
            "ix_results_classification_difference",
            "classification",
            sa.func.abs(sa.column("difference_amount")),
        ),
    )

    run_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    classification: Mapped[ReconciliationClassification] = mapped_column(
        enum_column(ReconciliationClassification, "reconciliation_classification"),
        nullable=False,
    )
    reason_code: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False)
    transaction_total: Mapped[Any] = mapped_column(money_type, nullable=False)
    settlement_total: Mapped[Any] = mapped_column(money_type, nullable=False)
    difference_amount: Mapped[Any] = mapped_column(money_type, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    review_status: Mapped[ReconciliationReviewStatus] = mapped_column(
        enum_column(ReconciliationReviewStatus, "reconciliation_review_status"), nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT")
    )


class ReconciliationResultTransaction(Base):
    __tablename__ = "reconciliation_result_transactions"
    __table_args__ = (
        sa.CheckConstraint(
            "allocated_amount IS NULL OR allocated_amount > 0",
            name="ck_result_transactions_allocation_positive",
        ),
        sa.Index("ix_result_transactions_transaction", "transaction_id"),
    )

    result_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("reconciliation_results.id", ondelete="RESTRICT"), primary_key=True
    )
    transaction_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("transactions.id", ondelete="RESTRICT"), primary_key=True
    )
    item_role: Mapped[ReconciliationItemRole] = mapped_column(
        enum_column(ReconciliationItemRole, "reconciliation_transaction_item_role"),
        nullable=False,
    )
    allocated_amount: Mapped[Any | None] = mapped_column(money_type)


class ReconciliationResultSettlement(Base):
    __tablename__ = "reconciliation_result_settlements"
    __table_args__ = (
        sa.CheckConstraint(
            "allocated_amount IS NULL OR allocated_amount > 0",
            name="ck_result_settlements_allocation_positive",
        ),
        sa.Index("ix_result_settlements_settlement", "settlement_id"),
    )

    result_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("reconciliation_results.id", ondelete="RESTRICT"), primary_key=True
    )
    settlement_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("settlements.id", ondelete="RESTRICT"), primary_key=True
    )
    item_role: Mapped[ReconciliationItemRole] = mapped_column(
        enum_column(ReconciliationItemRole, "reconciliation_settlement_item_role"),
        nullable=False,
    )
    allocated_amount: Mapped[Any | None] = mapped_column(money_type)


class FraudRule(UuidPrimaryKeyMixin, TimestampMixin, MutableMixin, Base):
    __tablename__ = "fraud_rules"
    __table_args__ = (sa.CheckConstraint("version > 0", name="ck_rules_version_positive"),)

    code: Mapped[str] = mapped_column(sa.String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text)
    created_by_user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class FraudRuleVersion(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fraud_rule_versions"
    __table_args__ = (
        sa.UniqueConstraint("rule_id", "version_number", name="uq_rule_versions_number"),
        sa.CheckConstraint("version_number > 0", name="ck_rule_versions_number_positive"),
        sa.Index(
            "uq_rule_versions_active",
            "rule_id",
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
        ),
    )

    rule_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("fraud_rules.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    rule_type: Mapped[FraudRuleType] = mapped_column(
        enum_column(FraudRuleType, "fraud_rule_type"), nullable=False
    )
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(
        enum_column(AlertSeverity, "alert_severity"), nullable=False
    )
    status: Mapped[RuleVersionStatus] = mapped_column(
        enum_column(RuleVersionStatus, "rule_version_status"), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    activated_by_user_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT")
    )
    activated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Alert(UuidPrimaryKeyMixin, TimestampMixin, MutableMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        sa.CheckConstraint(
            "transaction_id IS NOT NULL OR reconciliation_result_id IS NOT NULL",
            name="ck_alerts_evidence_target",
        ),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)", name="ck_alerts_score"
        ),
        sa.CheckConstraint("evidence_sha256 ~ '^[0-9a-f]{64}$'", name="ck_alerts_evidence_hash"),
        sa.CheckConstraint(
            "(closed_at IS NULL) = (closed_by_user_id IS NULL)", name="ck_alerts_close_pair"
        ),
        sa.CheckConstraint("version > 0", name="ck_alerts_version_positive"),
        sa.Index("ix_alerts_triage", "status", "severity", "created_at"),
        sa.Index("ix_alerts_rule_created", "rule_version_id", "created_at"),
    )

    rule_version_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("fraud_rule_versions.id", ondelete="RESTRICT"), nullable=False
    )
    transaction_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("transactions.id", ondelete="RESTRICT")
    )
    reconciliation_result_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("reconciliation_results.id", ondelete="RESTRICT")
    )
    deduplication_key: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    severity: Mapped[AlertSeverity] = mapped_column(
        enum_column(AlertSeverity, "alert_severity_snapshot"), nullable=False
    )
    score: Mapped[Any | None] = mapped_column(sa.Numeric(7, 4))
    status: Mapped[AlertStatus] = mapped_column(
        enum_column(AlertStatus, "alert_status"), nullable=False
    )
    reason_code: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(sa.Uuid, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    closed_by_user_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT")
    )


class InvestigationCase(UuidPrimaryKeyMixin, TimestampMixin, MutableMixin, Base):
    __tablename__ = "cases"
    __table_args__ = (
        sa.CheckConstraint("version > 0", name="ck_cases_version_positive"),
        sa.CheckConstraint(
            "(status <> 'resolved') OR "
            "(resolution_code IS NOT NULL AND resolution_summary IS NOT NULL "
            "AND resolved_at IS NOT NULL)",
            name="ck_cases_resolution_required",
        ),
        sa.Index("ix_cases_queue", "status", "priority", "updated_at"),
        sa.Index("ix_cases_owner_queue", "owner_user_id", "status", "updated_at"),
        sa.Index("ix_cases_resolved", "resolved_at"),
    )

    case_number: Mapped[int] = mapped_column(
        sa.BigInteger, sa.Identity(), nullable=False, unique=True
    )
    title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[CaseStatus] = mapped_column(
        enum_column(CaseStatus, "case_status"), nullable=False
    )
    priority: Mapped[CasePriority] = mapped_column(
        enum_column(CasePriority, "case_priority"), nullable=False
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT")
    )
    resolution_code: Mapped[str | None] = mapped_column(sa.String(80))
    resolution_summary: Mapped[str | None] = mapped_column(sa.Text)
    created_by_user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class CaseAlert(Base):
    __tablename__ = "case_alerts"
    __table_args__ = (sa.Index("ix_case_alerts_alert", "alert_id"),)

    case_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("cases.id", ondelete="RESTRICT"), primary_key=True
    )
    alert_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("alerts.id", ondelete="RESTRICT"), primary_key=True
    )
    linked_by_user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    linked_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class CaseComment(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "case_comments"
    __table_args__ = (sa.Index("ix_case_comments_timeline", "case_id", "created_at", "id"),)

    case_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False
    )
    author_user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)


class CaseStatusHistory(UuidPrimaryKeyMixin, Base):
    __tablename__ = "case_status_history"
    __table_args__ = (
        sa.Index("ix_case_status_history_timeline", "case_id", "changed_at", "id", unique=True),
    )

    case_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[CaseStatus | None] = mapped_column(
        enum_column(CaseStatus, "case_history_from_status")
    )
    to_status: Mapped[CaseStatus] = mapped_column(
        enum_column(CaseStatus, "case_history_to_status"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(sa.Text)
    changed_by_user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    correlation_id: Mapped[UUID] = mapped_column(sa.Uuid, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        sa.Index("ix_audit_target", "target_type", "target_id", "sequence_number"),
        sa.Index("ix_audit_actor", "actor_user_id", "sequence_number"),
        sa.Index("ix_audit_correlation", "correlation_id", "sequence_number"),
        sa.Index("ix_audit_occurred", "occurred_at"),
    )

    sequence_number: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)
    id: Mapped[UUID] = mapped_column(sa.Uuid, nullable=False, unique=True, default=uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT")
    )
    actor_type: Mapped[AuditActorType] = mapped_column(
        enum_column(AuditActorType, "audit_actor_type"), nullable=False
    )
    action: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    target_id: Mapped[UUID | None] = mapped_column(sa.Uuid)
    result: Mapped[AuditResult] = mapped_column(
        enum_column(AuditResult, "audit_result"), nullable=False
    )
    correlation_id: Mapped[UUID] = mapped_column(sa.Uuid, nullable=False)
    request_id: Mapped[UUID | None] = mapped_column(sa.Uuid)
    job_id: Mapped[UUID | None] = mapped_column(sa.Uuid)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    event_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)
