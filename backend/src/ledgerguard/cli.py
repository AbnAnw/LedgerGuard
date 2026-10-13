"""Administrative command-line entry points."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ledgerguard.auth import hash_password
from ledgerguard.config import get_settings
from ledgerguard.db import SessionLocal
from ledgerguard.models import (
    Account,
    AccountStatus,
    AccountType,
    FinancialTransaction,
    IngestionBatch,
    IngestionBatchStatus,
    IngestionRecordKind,
    MoneyDirection,
    Role,
    Settlement,
    SettlementStatus,
    TransactionStatus,
    User,
    UserRole,
    UserStatus,
)

DEMONSTRATION_USERS = (
    ("admin@ledgerguard.invalid", "Synthetic Administrator", "administrator"),
    ("analyst@ledgerguard.invalid", "Synthetic Operations Analyst", "operations_analyst"),
    ("auditor@ledgerguard.invalid", "Synthetic Auditor", "auditor"),
)


def seed() -> None:
    """Idempotently seed reference data and local-only synthetic users."""

    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("Synthetic demonstration users cannot be seeded in production")

    role_rows = [
        {"code": "administrator", "description": "Manages users, rules, and configuration"},
        {"code": "operations_analyst", "description": "Ingests and investigates data"},
        {"code": "auditor", "description": "Reads evidence and audit history"},
    ]

    with SessionLocal.begin() as session:
        session.execute(
            insert(Role).values(role_rows).on_conflict_do_nothing(index_elements=["code"])
        )

        account_statement = (
            insert(Account)
            .values(
                source_system="synthetic-demo",
                source_account_id="DEMO-ACCOUNT-001",
                display_name="Synthetic Demonstration Account",
                account_type=AccountType.MERCHANT,
                default_currency="USD",
                status=AccountStatus.ACTIVE,
            )
            .on_conflict_do_nothing(index_elements=["source_system", "source_account_id"])
        )
        session.execute(account_statement)

        password = settings.demo_user_password.get_secret_value()
        users: dict[str, User] = {}
        for email, display_name, _ in DEMONSTRATION_USERS:
            session.execute(
                insert(User)
                .values(
                    email=email,
                    display_name=display_name,
                    password_hash=hash_password(password),
                    status=UserStatus.ACTIVE,
                )
                .on_conflict_do_nothing(index_elements=["email"])
            )
            user = session.scalar(select(User).where(User.email == email))
            if user is None:
                raise RuntimeError(f"Unable to seed synthetic user {email}")
            users[email] = user

        administrator = users[DEMONSTRATION_USERS[0][0]]
        for email, _, role_code in DEMONSTRATION_USERS:
            user = users[email]
            existing_role = session.scalar(
                select(UserRole.id).where(
                    UserRole.user_id == user.id,
                    UserRole.role_code == role_code,
                    UserRole.revoked_at.is_(None),
                )
            )
            if existing_role is None:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role_code=role_code,
                        granted_by_user_id=administrator.id,
                    )
                )

    print("Seed complete: roles, synthetic account, and three demonstration users are present.")


def _payload_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def seed_reconciliation() -> None:
    """Idempotently seed the published synthetic Day 7 reconciliation scenario."""

    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("Synthetic reconciliation data cannot be seeded in production")

    # Keep the fixed fixture safely in the past so "run now" is meaningful in every time zone.
    base_time = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
    transaction_rows = [
        ("RECON-TX-EXACT", "REF-EXACT", Decimal("100.000000")),
        ("RECON-TX-PARTIAL", "REF-PARTIAL", Decimal("100.000000")),
        ("RECON-TX-MISSING", "REF-MISSING", Decimal("30.000000")),
        ("RECON-TX-DUPLICATE", "REF-DUPLICATE", Decimal("20.000000")),
    ]
    settlement_rows = [
        ("RECON-ST-EXACT", "REF-EXACT", Decimal("100.000000"), 1),
        ("RECON-ST-PARTIAL", "REF-PARTIAL", Decimal("60.000000"), 1),
        ("RECON-ST-DUPLICATE-A", "REF-DUPLICATE", Decimal("20.000000"), 1),
        ("RECON-ST-DUPLICATE-B", "REF-DUPLICATE", Decimal("20.000000"), 2),
        ("RECON-ST-UNEXPLAINED", "REF-UNEXPLAINED", Decimal("15.000000"), 1),
    ]

    with SessionLocal.begin() as session:
        session.execute(
            insert(Account)
            .values(
                source_system="synthetic-reconciliation",
                source_account_id="DEMO-RECON-001",
                display_name="Synthetic Reconciliation Demonstration Account",
                account_type=AccountType.MERCHANT,
                default_currency="USD",
                status=AccountStatus.ACTIVE,
            )
            .on_conflict_do_nothing(index_elements=["source_system", "source_account_id"])
        )
        account = session.scalar(
            select(Account).where(
                Account.source_system == "synthetic-reconciliation",
                Account.source_account_id == "DEMO-RECON-001",
            )
        )
        analyst = session.scalar(select(User).where(User.email == "analyst@ledgerguard.invalid"))
        if account is None or analyst is None:
            raise RuntimeError("Run ledgerguard-seed before seeding the reconciliation scenario")

        batch_specs = (
            (
                IngestionRecordKind.TRANSACTION,
                "day-07-reconciliation-transactions-v1",
                transaction_rows,
            ),
            (
                IngestionRecordKind.SETTLEMENT,
                "day-07-reconciliation-settlements-v1",
                settlement_rows,
            ),
        )
        batches: dict[IngestionRecordKind, IngestionBatch] = {}
        for record_kind, idempotency_key, rows in batch_specs:
            session.execute(
                insert(IngestionBatch)
                .values(
                    record_kind=record_kind,
                    source_system="synthetic-reconciliation-v1",
                    schema_version="1.0",
                    idempotency_key=idempotency_key,
                    payload_sha256=_payload_digest(rows),
                    status=IngestionBatchStatus.COMPLETED,
                    source_count=len(rows),
                    accepted_count=len(rows),
                    rejected_count=0,
                    duplicate_count=0,
                    conflict_count=0,
                    requested_by_user_id=analyst.id,
                    correlation_id=uuid4(),
                    started_at=base_time,
                    finished_at=base_time,
                )
                .on_conflict_do_nothing(index_elements=["source_system", "idempotency_key"])
            )
            batch = session.scalar(
                select(IngestionBatch).where(
                    IngestionBatch.source_system == "synthetic-reconciliation-v1",
                    IngestionBatch.idempotency_key == idempotency_key,
                )
            )
            if batch is None:
                raise RuntimeError(f"Unable to seed {record_kind.value} batch")
            batches[record_kind] = batch

        for source_record_id, reference, amount in transaction_rows:
            session.execute(
                insert(FinancialTransaction)
                .values(
                    account_id=account.id,
                    batch_id=batches[IngestionRecordKind.TRANSACTION].id,
                    source_record_id=source_record_id,
                    source_reference=reference,
                    amount=amount,
                    currency="USD",
                    direction=MoneyDirection.CREDIT,
                    status=TransactionStatus.POSTED,
                    occurred_at=base_time,
                )
                .on_conflict_do_nothing(index_elements=["account_id", "source_record_id"])
            )

        for source_record_id, reference, amount, delay_hours in settlement_rows:
            session.execute(
                insert(Settlement)
                .values(
                    account_id=account.id,
                    batch_id=batches[IngestionRecordKind.SETTLEMENT].id,
                    source_record_id=source_record_id,
                    source_reference=reference,
                    provider="Synthetic Clearing Provider",
                    amount=amount,
                    currency="USD",
                    status=SettlementStatus.CONFIRMED,
                    settled_at=base_time + timedelta(hours=delay_hours),
                )
                .on_conflict_do_nothing(index_elements=["account_id", "source_record_id"])
            )

    print("Seed complete: deterministic Day 7 reconciliation scenario is present.")
