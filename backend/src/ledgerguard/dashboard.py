"""Read-only operational dashboard projection."""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ledgerguard.auth import AuthPrincipal, Permission, require_permissions
from ledgerguard.db import get_db
from ledgerguard.models import (
    Account,
    AccountStatus,
    FinancialTransaction,
    IngestionBatch,
    IngestionBatchStatus,
    IngestionRecordKind,
    ReconciliationClassification,
    ReconciliationRun,
    ReconciliationRunStatus,
    Settlement,
)
from ledgerguard.reconciliation import (
    ReconciliationRunResponse,
    load_reconciliation_run_response,
)

ZERO = Decimal("0")
PERCENT_QUANTUM = Decimal("0.01")


class DashboardMetrics(BaseModel):
    transaction_count: int
    settlement_count: int
    transaction_value: str
    settlement_value: str
    exact_matched_value: str
    unresolved_value: str
    match_rate_percent: str
    validation_failure_count: int
    classification_counts: dict[str, int]


class DashboardBatch(BaseModel):
    id: UUID
    record_kind: IngestionRecordKind
    source_system: str
    status: IngestionBatchStatus
    source_count: int
    accepted_count: int
    rejected_count: int
    duplicate_count: int
    conflict_count: int
    created_at: datetime
    finished_at: datetime | None


class DashboardOverviewResponse(BaseModel):
    account_id: UUID
    source_system: str
    source_account_id: str
    display_name: str
    currency: str | None
    metrics: DashboardMetrics
    latest_run: ReconciliationRunResponse | None
    batches: list[DashboardBatch]


def _money(value: Decimal) -> str:
    return format(value, "f")


def calculate_dashboard_metrics(
    run: ReconciliationRunResponse | None,
    validation_failure_count: int,
) -> DashboardMetrics:
    """Calculate dashboard values with Decimal and explicit metric definitions."""

    classification_counts = {
        classification.value: 0 for classification in ReconciliationClassification
    }
    if run is None:
        return DashboardMetrics(
            transaction_count=0,
            settlement_count=0,
            transaction_value="0",
            settlement_value="0",
            exact_matched_value="0",
            unresolved_value="0",
            match_rate_percent="0.00",
            validation_failure_count=validation_failure_count,
            classification_counts=classification_counts,
        )

    transaction_value = Decimal(run.summary.transaction_value)
    settlement_value = Decimal(run.summary.settlement_value)
    exact_matched_value = sum(
        (
            Decimal(result.transaction_total)
            for result in run.results
            if result.classification == ReconciliationClassification.EXACT_MATCH
        ),
        ZERO,
    )
    unresolved_value = sum(
        (
            max(Decimal(result.transaction_total), Decimal(result.settlement_total))
            for result in run.results
            if result.classification != ReconciliationClassification.EXACT_MATCH
        ),
        ZERO,
    )
    match_rate = (
        (exact_matched_value * Decimal("100") / transaction_value).quantize(
            PERCENT_QUANTUM, rounding=ROUND_HALF_UP
        )
        if transaction_value > ZERO
        else ZERO
    )
    classification_counts.update(run.summary.classification_counts)
    return DashboardMetrics(
        transaction_count=run.summary.transaction_count,
        settlement_count=run.summary.settlement_count,
        transaction_value=_money(transaction_value),
        settlement_value=_money(settlement_value),
        exact_matched_value=_money(exact_matched_value),
        unresolved_value=_money(unresolved_value),
        match_rate_percent=f"{match_rate:.2f}",
        validation_failure_count=validation_failure_count,
        classification_counts=classification_counts,
    )


def build_dashboard_overview(
    db: Session,
    source_system: str,
    source_account_id: str,
    batch_limit: int,
) -> DashboardOverviewResponse:
    account = db.scalar(
        select(Account).where(
            Account.source_system == source_system,
            Account.source_account_id == source_account_id,
            Account.status == AccountStatus.ACTIVE,
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Active account not found"
        )

    latest_run_model = db.scalar(
        select(ReconciliationRun)
        .where(
            ReconciliationRun.account_id == account.id,
            ReconciliationRun.status == ReconciliationRunStatus.COMPLETED,
        )
        .order_by(
            ReconciliationRun.input_cutoff_at.desc(),
            ReconciliationRun.created_at.desc(),
            ReconciliationRun.id.desc(),
        )
        .limit(1)
    )
    latest_run = (
        load_reconciliation_run_response(db, latest_run_model, account, replayed=False)
        if latest_run_model is not None
        else None
    )

    transaction_batch_ids = set(
        db.scalars(
            select(FinancialTransaction.batch_id).where(
                FinancialTransaction.account_id == account.id
            )
        ).all()
    )
    settlement_batch_ids = set(
        db.scalars(select(Settlement.batch_id).where(Settlement.account_id == account.id)).all()
    )
    batch_ids = transaction_batch_ids | settlement_batch_ids
    batch_models = (
        list(
            db.scalars(
                select(IngestionBatch)
                .where(IngestionBatch.id.in_(batch_ids))
                .order_by(IngestionBatch.created_at.desc(), IngestionBatch.id.desc())
                .limit(batch_limit)
            ).all()
        )
        if batch_ids
        else []
    )
    validation_failures = (
        db.scalar(
            select(func.coalesce(func.sum(IngestionBatch.rejected_count), 0)).where(
                IngestionBatch.id.in_(batch_ids)
            )
        )
        if batch_ids
        else 0
    )
    batches = [
        DashboardBatch(
            id=batch.id,
            record_kind=batch.record_kind,
            source_system=batch.source_system,
            status=batch.status,
            source_count=batch.source_count or 0,
            accepted_count=batch.accepted_count,
            rejected_count=batch.rejected_count,
            duplicate_count=batch.duplicate_count,
            conflict_count=batch.conflict_count,
            created_at=batch.created_at,
            finished_at=batch.finished_at,
        )
        for batch in batch_models
    ]
    return DashboardOverviewResponse(
        account_id=account.id,
        source_system=account.source_system,
        source_account_id=account.source_account_id,
        display_name=account.display_name,
        currency=account.default_currency,
        metrics=calculate_dashboard_metrics(latest_run, int(validation_failures or 0)),
        latest_run=latest_run,
        batches=batches,
    )


router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/overview", response_model=DashboardOverviewResponse)
def dashboard_overview(
    source_system: Annotated[
        str,
        Query(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"),
    ],
    source_account_id: Annotated[
        str,
        Query(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
    ],
    _principal: Annotated[
        AuthPrincipal,
        Depends(require_permissions(Permission.TRANSACTIONS_READ, Permission.RECONCILIATION_READ)),
    ],
    db: Annotated[Session, Depends(get_db)],
    batch_limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> DashboardOverviewResponse:
    return build_dashboard_overview(db, source_system, source_account_id, batch_limit)
