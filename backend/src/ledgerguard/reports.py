"""Verified operational reports and spreadsheet-safe exports."""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ledgerguard.audit_service import append_audit_event
from ledgerguard.auth import AuthPrincipal, Permission, require_permissions
from ledgerguard.db import get_db
from ledgerguard.models import (
    Account,
    AccountStatus,
    Alert,
    CaseAlert,
    CasePriority,
    CaseStatus,
    FinancialTransaction,
    FraudRule,
    FraudRuleVersion,
    InvestigationCase,
    ReconciliationClassification,
    ReconciliationResult,
    ReconciliationRun,
    ReconciliationRunStatus,
    Settlement,
    SettlementStatus,
    TransactionStatus,
    User,
)

MONEY_QUANTUM = Decimal("0.000001")
ZERO = Decimal("0.000000")
DAILY_CSV_FIELDS = (
    "report_date",
    "window_start_utc",
    "window_end_utc",
    "source_system",
    "source_account_id",
    "currency",
    "transaction_count",
    "transaction_total",
    "settlement_count",
    "settlement_total",
    "difference",
    "totals_verified",
    "reconciliation_run_id",
    "run_input_cutoff_utc",
)
UNRESOLVED_CSV_FIELDS = (
    "cutoff_utc",
    "case_id",
    "case_number",
    "title",
    "status",
    "priority",
    "owner_user_id",
    "owner_display_name",
    "created_at_utc",
    "age_hours",
    "alert_count",
    "rule_codes",
)


class ReportTotalMismatch(RuntimeError):
    """Raised when independent calculations disagree."""


@dataclass(frozen=True, slots=True)
class ExactTotal:
    count: int
    amount: Decimal


class CurrencyTotals(BaseModel):
    currency: str
    transaction_count: int
    transaction_total: str
    settlement_count: int
    settlement_total: str
    difference: str


class ClassificationTotals(BaseModel):
    classification: ReconciliationClassification
    result_count: int
    transaction_total: str
    settlement_total: str
    difference_total: str


class ReconciliationSnapshot(BaseModel):
    run_id: UUID
    input_cutoff_at: datetime
    algorithm_version: str
    result_count: int
    classifications: list[ClassificationTotals]


class DailyReconciliationReport(BaseModel):
    report_date: date
    window_start: datetime
    window_end: datetime
    generated_at: datetime
    account_id: UUID
    source_system: str
    source_account_id: str
    totals_verified: bool
    currency_totals: list[CurrencyTotals]
    reconciliation_snapshot: ReconciliationSnapshot | None


class UnresolvedCaseRow(BaseModel):
    case_id: UUID
    case_number: int
    title: str
    status: CaseStatus
    priority: CasePriority
    owner_user_id: UUID | None
    owner_display_name: str | None
    created_at: datetime
    age_hours: int
    alert_count: int
    rule_codes: list[str]


class UnresolvedCaseReport(BaseModel):
    cutoff_at: datetime
    generated_at: datetime
    case_count: int
    cases: list[UnresolvedCaseRow]


def _money(value: Decimal) -> str:
    return f"{value.quantize(MONEY_QUANTUM):.6f}"


def _window(report_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(report_date, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _normalise_cutoff(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cutoff_at must include a UTC offset",
        )
    return value.astimezone(UTC)


def aggregate_exact_totals(rows: list[tuple[str, Any]]) -> dict[str, ExactTotal]:
    """Aggregate individual rows without binary floating-point arithmetic."""

    totals: dict[str, ExactTotal] = {}
    for currency, raw_amount in rows:
        amount = Decimal(str(raw_amount))
        current = totals.get(currency, ExactTotal(0, ZERO))
        totals[currency] = ExactTotal(current.count + 1, current.amount + amount)
    return totals


def verify_exact_totals(
    calculated: dict[str, ExactTotal], independently_queried: dict[str, ExactTotal]
) -> None:
    if calculated != independently_queried:
        raise ReportTotalMismatch("independent report totals do not match")


def neutralize_csv_cell(value: object | None) -> str:
    """Return a cell that spreadsheet software cannot treat as a formula."""

    if value is None:
        return ""
    text = str(value)
    significant = text.lstrip()
    if text.startswith(("\t", "\r", "\n")) or significant.startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


def _database_totals(rows: Sequence[Any]) -> dict[str, ExactTotal]:
    return {
        str(row[0]): ExactTotal(count=int(row[1]), amount=Decimal(str(row[2] or ZERO)))
        for row in rows
    }


def _account(db: Session, source_system: str, source_account_id: str) -> Account:
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
    return account


def _classification_snapshot(db: Session, run: ReconciliationRun) -> ReconciliationSnapshot:
    rows = db.execute(
        select(
            ReconciliationResult.classification,
            func.count(ReconciliationResult.id),
            func.coalesce(func.sum(ReconciliationResult.transaction_total), ZERO),
            func.coalesce(func.sum(ReconciliationResult.settlement_total), ZERO),
            func.coalesce(func.sum(ReconciliationResult.difference_amount), ZERO),
        )
        .where(ReconciliationResult.run_id == run.id)
        .group_by(ReconciliationResult.classification)
    ).all()
    by_classification = {
        row[0]: ClassificationTotals(
            classification=row[0],
            result_count=int(row[1]),
            transaction_total=_money(Decimal(str(row[2]))),
            settlement_total=_money(Decimal(str(row[3]))),
            difference_total=_money(Decimal(str(row[4]))),
        )
        for row in rows
    }
    classifications = [
        by_classification.get(
            classification,
            ClassificationTotals(
                classification=classification,
                result_count=0,
                transaction_total=_money(ZERO),
                settlement_total=_money(ZERO),
                difference_total=_money(ZERO),
            ),
        )
        for classification in ReconciliationClassification
    ]
    return ReconciliationSnapshot(
        run_id=run.id,
        input_cutoff_at=run.input_cutoff_at,
        algorithm_version=run.algorithm_version,
        result_count=sum(item.result_count for item in classifications),
        classifications=classifications,
    )


def build_daily_reconciliation_report(
    db: Session,
    report_date: date,
    source_system: str,
    source_account_id: str,
    *,
    generated_at: datetime | None = None,
) -> DailyReconciliationReport:
    account = _account(db, source_system, source_account_id)
    start, end = _window(report_date)

    transaction_rows = [
        (str(row[0]), row[1])
        for row in db.execute(
            select(FinancialTransaction.currency, FinancialTransaction.amount).where(
                FinancialTransaction.account_id == account.id,
                FinancialTransaction.status == TransactionStatus.POSTED,
                FinancialTransaction.occurred_at >= start,
                FinancialTransaction.occurred_at < end,
            )
        ).all()
    ]
    settlement_rows = [
        (str(row[0]), row[1])
        for row in db.execute(
            select(Settlement.currency, Settlement.amount).where(
                Settlement.account_id == account.id,
                Settlement.status == SettlementStatus.CONFIRMED,
                Settlement.settled_at >= start,
                Settlement.settled_at < end,
            )
        ).all()
    ]
    transaction_totals = aggregate_exact_totals(transaction_rows)
    settlement_totals = aggregate_exact_totals(settlement_rows)

    transaction_check = _database_totals(
        db.execute(
            select(
                FinancialTransaction.currency,
                func.count(FinancialTransaction.id),
                func.sum(FinancialTransaction.amount),
            )
            .where(
                FinancialTransaction.account_id == account.id,
                FinancialTransaction.status == TransactionStatus.POSTED,
                FinancialTransaction.occurred_at >= start,
                FinancialTransaction.occurred_at < end,
            )
            .group_by(FinancialTransaction.currency)
        ).all()
    )
    settlement_check = _database_totals(
        db.execute(
            select(
                Settlement.currency,
                func.count(Settlement.id),
                func.sum(Settlement.amount),
            )
            .where(
                Settlement.account_id == account.id,
                Settlement.status == SettlementStatus.CONFIRMED,
                Settlement.settled_at >= start,
                Settlement.settled_at < end,
            )
            .group_by(Settlement.currency)
        ).all()
    )
    verify_exact_totals(transaction_totals, transaction_check)
    verify_exact_totals(settlement_totals, settlement_check)

    currencies = sorted(transaction_totals.keys() | settlement_totals.keys())
    currency_totals = []
    for currency in currencies:
        transaction = transaction_totals.get(currency, ExactTotal(0, ZERO))
        settlement = settlement_totals.get(currency, ExactTotal(0, ZERO))
        currency_totals.append(
            CurrencyTotals(
                currency=currency,
                transaction_count=transaction.count,
                transaction_total=_money(transaction.amount),
                settlement_count=settlement.count,
                settlement_total=_money(settlement.amount),
                difference=_money(settlement.amount - transaction.amount),
            )
        )

    latest_run = db.scalar(
        select(ReconciliationRun)
        .where(
            ReconciliationRun.account_id == account.id,
            ReconciliationRun.status == ReconciliationRunStatus.COMPLETED,
            ReconciliationRun.input_cutoff_at < end,
        )
        .order_by(
            ReconciliationRun.input_cutoff_at.desc(),
            ReconciliationRun.created_at.desc(),
            ReconciliationRun.id.desc(),
        )
        .limit(1)
    )
    return DailyReconciliationReport(
        report_date=report_date,
        window_start=start,
        window_end=end,
        generated_at=(generated_at or datetime.now(UTC)).astimezone(UTC),
        account_id=account.id,
        source_system=account.source_system,
        source_account_id=account.source_account_id,
        totals_verified=True,
        currency_totals=currency_totals,
        reconciliation_snapshot=(
            _classification_snapshot(db, latest_run) if latest_run is not None else None
        ),
    )


def build_unresolved_case_report(
    db: Session,
    cutoff_at: datetime,
    limit: int,
    *,
    generated_at: datetime | None = None,
) -> UnresolvedCaseReport:
    cutoff = _normalise_cutoff(cutoff_at)
    priority_order = sa.case(
        (InvestigationCase.priority == CasePriority.CRITICAL, 0),
        (InvestigationCase.priority == CasePriority.HIGH, 1),
        (InvestigationCase.priority == CasePriority.MEDIUM, 2),
        else_=3,
    )
    case_rows = db.execute(
        select(InvestigationCase, User.display_name)
        .outerjoin(User, User.id == InvestigationCase.owner_user_id)
        .where(
            InvestigationCase.status != CaseStatus.RESOLVED,
            InvestigationCase.created_at <= cutoff,
        )
        .order_by(priority_order, InvestigationCase.created_at, InvestigationCase.id)
        .limit(limit)
    ).all()
    case_ids = [row[0].id for row in case_rows]
    alert_counts: dict[UUID, int] = {}
    rule_codes: dict[UUID, list[str]] = {}
    if case_ids:
        alert_counts = {
            row[0]: int(row[1])
            for row in db.execute(
                select(CaseAlert.case_id, func.count(CaseAlert.alert_id))
                .where(CaseAlert.case_id.in_(case_ids))
                .group_by(CaseAlert.case_id)
            ).all()
        }
        for case_id, code in db.execute(
            select(CaseAlert.case_id, FraudRule.code)
            .join(Alert, Alert.id == CaseAlert.alert_id)
            .join(FraudRuleVersion, FraudRuleVersion.id == Alert.rule_version_id)
            .join(FraudRule, FraudRule.id == FraudRuleVersion.rule_id)
            .where(CaseAlert.case_id.in_(case_ids))
            .distinct()
            .order_by(CaseAlert.case_id, FraudRule.code)
        ).all():
            rule_codes.setdefault(case_id, []).append(str(code))

    cases = [
        UnresolvedCaseRow(
            case_id=investigation.id,
            case_number=investigation.case_number,
            title=investigation.title,
            status=investigation.status,
            priority=investigation.priority,
            owner_user_id=investigation.owner_user_id,
            owner_display_name=owner_name,
            created_at=investigation.created_at,
            age_hours=max(0, int((cutoff - investigation.created_at).total_seconds() // 3600)),
            alert_count=alert_counts.get(investigation.id, 0),
            rule_codes=rule_codes.get(investigation.id, []),
        )
        for investigation, owner_name in case_rows
    ]
    return UnresolvedCaseReport(
        cutoff_at=cutoff,
        generated_at=(generated_at or datetime.now(UTC)).astimezone(UTC),
        case_count=len(cases),
        cases=cases,
    )


def _csv_response(
    fields: tuple[str, ...], rows: list[dict[str, object]], filename: str
) -> Response:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="raise", lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: neutralize_csv_cell(row[field]) for field in fields})
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def daily_report_csv(report: DailyReconciliationReport) -> Response:
    snapshot = report.reconciliation_snapshot
    rows = [
        {
            "report_date": report.report_date.isoformat(),
            "window_start_utc": report.window_start.isoformat(),
            "window_end_utc": report.window_end.isoformat(),
            "source_system": report.source_system,
            "source_account_id": report.source_account_id,
            "currency": item.currency,
            "transaction_count": item.transaction_count,
            "transaction_total": item.transaction_total,
            "settlement_count": item.settlement_count,
            "settlement_total": item.settlement_total,
            "difference": item.difference,
            "totals_verified": str(report.totals_verified).lower(),
            "reconciliation_run_id": snapshot.run_id if snapshot else None,
            "run_input_cutoff_utc": snapshot.input_cutoff_at.isoformat() if snapshot else None,
        }
        for item in report.currency_totals
    ]
    return _csv_response(DAILY_CSV_FIELDS, rows, "ledgerguard-daily-reconciliation.csv")


def unresolved_report_csv(report: UnresolvedCaseReport) -> Response:
    rows = [
        {
            "cutoff_utc": report.cutoff_at.isoformat(),
            "case_id": item.case_id,
            "case_number": item.case_number,
            "title": item.title,
            "status": item.status.value,
            "priority": item.priority.value,
            "owner_user_id": item.owner_user_id,
            "owner_display_name": item.owner_display_name,
            "created_at_utc": item.created_at.isoformat(),
            "age_hours": item.age_hours,
            "alert_count": item.alert_count,
            "rule_codes": "|".join(item.rule_codes),
        }
        for item in report.cases
    ]
    return _csv_response(UNRESOLVED_CSV_FIELDS, rows, "ledgerguard-unresolved-cases.csv")


def _daily_or_unavailable(
    db: Session, report_date: date, source_system: str, source_account_id: str
) -> DailyReconciliationReport:
    try:
        return build_daily_reconciliation_report(db, report_date, source_system, source_account_id)
    except ReportTotalMismatch as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "REPORT_TOTAL_MISMATCH",
                "message": "Independent report totals did not match; no report was returned.",
            },
        ) from error


def _audit_report(
    db: Session,
    principal: AuthPrincipal,
    *,
    action: str,
    report_kind: str,
    row_count: int,
    cutoff: str,
) -> None:
    append_audit_event(
        db,
        action=action,
        target_type="report",
        actor_user_id=principal.user_id,
        metadata={
            "schema_version": "audit-v1",
            "report_kind": report_kind,
            "row_count": row_count,
            "cutoff": cutoff,
        },
    )
    db.commit()


router = APIRouter(prefix="/api/v1/reports", tags=["reporting"])


@router.get("/daily-reconciliation", response_model=DailyReconciliationReport)
def read_daily_reconciliation_report(
    report_date: date,
    source_system: Annotated[
        str, Query(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    ],
    source_account_id: Annotated[
        str, Query(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    ],
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.REPORTS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> DailyReconciliationReport:
    report = _daily_or_unavailable(db, report_date, source_system, source_account_id)
    _audit_report(
        db,
        principal,
        action="report.daily.view",
        report_kind="daily_reconciliation",
        row_count=len(report.currency_totals),
        cutoff=report.window_end.isoformat(),
    )
    return report


@router.get("/daily-reconciliation.csv")
def export_daily_reconciliation_report(
    report_date: date,
    source_system: Annotated[
        str, Query(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    ],
    source_account_id: Annotated[
        str, Query(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    ],
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.REPORTS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    report = _daily_or_unavailable(db, report_date, source_system, source_account_id)
    _audit_report(
        db,
        principal,
        action="report.daily.export",
        report_kind="daily_reconciliation",
        row_count=len(report.currency_totals),
        cutoff=report.window_end.isoformat(),
    )
    return daily_report_csv(report)


@router.get("/unresolved-cases", response_model=UnresolvedCaseReport)
def read_unresolved_case_report(
    cutoff_at: datetime,
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.REPORTS_READ))],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
) -> UnresolvedCaseReport:
    report = build_unresolved_case_report(db, cutoff_at, limit)
    _audit_report(
        db,
        principal,
        action="report.unresolved.view",
        report_kind="unresolved_cases",
        row_count=report.case_count,
        cutoff=report.cutoff_at.isoformat(),
    )
    return report


@router.get("/unresolved-cases.csv")
def export_unresolved_case_report(
    cutoff_at: datetime,
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.REPORTS_READ))],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
) -> Response:
    report = build_unresolved_case_report(db, cutoff_at, limit)
    _audit_report(
        db,
        principal,
        action="report.unresolved.export",
        report_kind="unresolved_cases",
        row_count=report.case_count,
        cutoff=report.cutoff_at.isoformat(),
    )
    return unresolved_report_csv(report)
