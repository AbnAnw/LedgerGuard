"""Deterministic, evidence-preserving reconciliation engine."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ledgerguard.audit_service import append_audit_event
from ledgerguard.auth import AuthPrincipal, Permission, require_permissions
from ledgerguard.config import Settings, get_settings
from ledgerguard.db import get_db
from ledgerguard.jobs import BackgroundJobResponse, enqueue_reconciliation_job
from ledgerguard.models import (
    Account,
    AccountStatus,
    FinancialTransaction,
    ReconciliationClassification,
    ReconciliationItemRole,
    ReconciliationResult,
    ReconciliationResultSettlement,
    ReconciliationResultTransaction,
    ReconciliationReviewStatus,
    ReconciliationRun,
    ReconciliationRunStatus,
    Settlement,
    SettlementStatus,
    TransactionStatus,
)
from ledgerguard.security import enforce_synthetic_source

ALGORITHM_VERSION = "reconciliation-v1.0.0"
ZERO = Decimal("0")


class ReconciliationRunRequest(BaseModel):
    source_system: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    source_account_id: str = Field(
        min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    input_cutoff_at: datetime
    match_window_hours: int = Field(default=72, ge=1, le=168)

    @field_validator("input_cutoff_at")
    @classmethod
    def normalize_cutoff(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("input_cutoff_at must include a UTC offset")
        return value.astimezone(UTC)


class ReconciliationItemResponse(BaseModel):
    id: UUID
    source_record_id: str
    source_reference: str
    amount: str
    currency: str
    occurred_at: datetime | None = None
    settled_at: datetime | None = None
    item_role: ReconciliationItemRole
    allocated_amount: str | None


class ReconciliationResultResponse(BaseModel):
    id: UUID
    classification: ReconciliationClassification
    reason_code: str
    currency: str
    transaction_total: str
    settlement_total: str
    difference_amount: str
    evidence: dict[str, Any]
    evidence_sha256: str
    transactions: list[ReconciliationItemResponse]
    settlements: list[ReconciliationItemResponse]


class ReconciliationSummary(BaseModel):
    transaction_count: int
    settlement_count: int
    transaction_value: str
    settlement_value: str
    result_count: int
    classification_counts: dict[str, int]


class ReconciliationRunResponse(BaseModel):
    run_id: UUID
    account_id: UUID
    source_system: str
    source_account_id: str
    algorithm_version: str
    input_cutoff_at: datetime
    configuration: dict[str, Any]
    replay_key: str
    status: ReconciliationRunStatus
    replayed: bool
    summary: ReconciliationSummary
    results: list[ReconciliationResultResponse]


@dataclass(frozen=True, slots=True)
class TransactionFact:
    id: UUID
    source_record_id: str
    source_reference: str
    amount: Decimal
    currency: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class SettlementFact:
    id: UUID
    source_record_id: str
    source_reference: str
    amount: Decimal
    currency: str
    settled_at: datetime


@dataclass(frozen=True, slots=True)
class ReconciliationDecision:
    classification: ReconciliationClassification
    reason_code: str
    currency: str
    transactions: tuple[TransactionFact, ...]
    settlements: tuple[SettlementFact, ...]
    transaction_total: Decimal
    settlement_total: Decimal
    difference_amount: Decimal
    evidence: dict[str, Any]
    evidence_sha256: str


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _money(value: Decimal) -> str:
    return format(value, "f")


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _transaction_evidence(fact: TransactionFact) -> dict[str, str]:
    return {
        "id": str(fact.id),
        "source_record_id": fact.source_record_id,
        "source_reference": fact.source_reference,
        "amount": _money(fact.amount),
        "currency": fact.currency,
        "occurred_at": _utc_iso(fact.occurred_at),
    }


def _settlement_evidence(fact: SettlementFact) -> dict[str, str]:
    return {
        "id": str(fact.id),
        "source_record_id": fact.source_record_id,
        "source_reference": fact.source_reference,
        "amount": _money(fact.amount),
        "currency": fact.currency,
        "settled_at": _utc_iso(fact.settled_at),
    }


def _is_candidate(
    transaction: TransactionFact,
    settlement: SettlementFact,
    window: timedelta,
) -> bool:
    elapsed = settlement.settled_at - transaction.occurred_at
    return (
        transaction.source_reference == settlement.source_reference
        and transaction.currency == settlement.currency
        and timedelta(0) <= elapsed <= window
    )


def _candidate_edges(
    transactions: list[TransactionFact],
    settlements: list[SettlementFact],
    window: timedelta,
) -> tuple[dict[UUID, tuple[UUID, ...]], dict[UUID, tuple[UUID, ...]]]:
    """Build deterministic candidate edges without a Cartesian product."""

    mutable_transaction_edges: dict[UUID, list[UUID]] = defaultdict(list)
    mutable_settlement_edges: dict[UUID, list[UUID]] = defaultdict(list)
    settlements_by_match_key: dict[tuple[str, str], list[SettlementFact]] = defaultdict(list)
    for settlement in settlements:
        settlements_by_match_key[(settlement.source_reference, settlement.currency)].append(
            settlement
        )
    for transaction in transactions:
        for settlement in settlements_by_match_key[
            (transaction.source_reference, transaction.currency)
        ]:
            if _is_candidate(transaction, settlement, window):
                mutable_transaction_edges[transaction.id].append(settlement.id)
                mutable_settlement_edges[settlement.id].append(transaction.id)

    return (
        {
            fact.id: tuple(sorted(mutable_transaction_edges[fact.id], key=str))
            for fact in transactions
        },
        {
            fact.id: tuple(sorted(mutable_settlement_edges[fact.id], key=str))
            for fact in settlements
        },
    )


def _classification_for_component(
    transactions: tuple[TransactionFact, ...],
    settlements: tuple[SettlementFact, ...],
    transaction_edges: dict[UUID, tuple[UUID, ...]],
    settlement_edges: dict[UUID, tuple[UUID, ...]],
    settlements_by_id: dict[UUID, SettlementFact],
    transactions_by_id: dict[UUID, TransactionFact],
) -> tuple[ReconciliationClassification, str]:
    if not settlements:
        return ReconciliationClassification.MISSING_SETTLEMENT, "NO_ELIGIBLE_SETTLEMENT"
    if not transactions:
        return ReconciliationClassification.UNEXPLAINED_SETTLEMENT, "NO_ELIGIBLE_TRANSACTION"

    duplicate_transaction_candidate = any(
        sum(
            settlements_by_id[settlement_id].amount == transaction.amount
            for settlement_id in transaction_edges[transaction.id]
        )
        > 1
        for transaction in transactions
    )
    duplicate_settlement_candidate = any(
        sum(
            transactions_by_id[transaction_id].amount == settlement.amount
            for transaction_id in settlement_edges[settlement.id]
        )
        > 1
        for settlement in settlements
    )
    if duplicate_transaction_candidate or duplicate_settlement_candidate:
        return ReconciliationClassification.DUPLICATE_CANDIDATE, "DUPLICATE_EXACT_CANDIDATES"

    if (
        len(transactions) == 1
        and len(settlements) == 1
        and transactions[0].amount == settlements[0].amount
    ):
        return (
            ReconciliationClassification.EXACT_MATCH,
            "EXACT_REFERENCE_AMOUNT_CURRENCY_TIME",
        )

    transaction_total = sum((fact.amount for fact in transactions), ZERO)
    settlement_total = sum((fact.amount for fact in settlements), ZERO)
    reason = (
        "PARTIAL_GROUP_MATCH"
        if transaction_total == settlement_total
        else "PARTIAL_AMOUNT_MISMATCH"
    )
    return ReconciliationClassification.PARTIAL_MATCH, reason


def build_reconciliation_decisions(
    transactions: list[TransactionFact],
    settlements: list[SettlementFact],
    match_window_hours: int,
) -> list[ReconciliationDecision]:
    """Build a stable partition of eligible facts into explainable outcomes."""

    window = timedelta(hours=match_window_hours)
    ordered_transactions = sorted(transactions, key=lambda item: str(item.id))
    ordered_settlements = sorted(settlements, key=lambda item: str(item.id))
    transactions_by_id = {item.id: item for item in ordered_transactions}
    settlements_by_id = {item.id: item for item in ordered_settlements}

    transaction_edges, settlement_edges = _candidate_edges(
        ordered_transactions, ordered_settlements, window
    )

    unvisited_transactions = set(transactions_by_id)
    unvisited_settlements = set(settlements_by_id)
    components: list[tuple[tuple[TransactionFact, ...], tuple[SettlementFact, ...]]] = []

    node_order = [*(("transaction", item.id) for item in ordered_transactions)]
    node_order.extend(("settlement", item.id) for item in ordered_settlements)
    for initial_kind, initial_id in node_order:
        if initial_kind == "transaction" and initial_id not in unvisited_transactions:
            continue
        if initial_kind == "settlement" and initial_id not in unvisited_settlements:
            continue

        component_transaction_ids: set[UUID] = set()
        component_settlement_ids: set[UUID] = set()
        queue: deque[tuple[str, UUID]] = deque([(initial_kind, initial_id)])
        while queue:
            kind, item_id = queue.popleft()
            if kind == "transaction":
                if item_id not in unvisited_transactions:
                    continue
                unvisited_transactions.remove(item_id)
                component_transaction_ids.add(item_id)
                queue.extend(("settlement", value) for value in transaction_edges[item_id])
            else:
                if item_id not in unvisited_settlements:
                    continue
                unvisited_settlements.remove(item_id)
                component_settlement_ids.add(item_id)
                queue.extend(("transaction", value) for value in settlement_edges[item_id])

        components.append(
            (
                tuple(
                    transactions_by_id[value]
                    for value in sorted(component_transaction_ids, key=str)
                ),
                tuple(
                    settlements_by_id[value] for value in sorted(component_settlement_ids, key=str)
                ),
            )
        )

    decisions: list[ReconciliationDecision] = []
    for component_transactions, component_settlements in components:
        classification, reason_code = _classification_for_component(
            component_transactions,
            component_settlements,
            transaction_edges,
            settlement_edges,
            settlements_by_id,
            transactions_by_id,
        )
        transaction_total = sum((fact.amount for fact in component_transactions), ZERO)
        settlement_total = sum((fact.amount for fact in component_settlements), ZERO)
        difference = settlement_total - transaction_total
        currency = (
            component_transactions[0].currency
            if component_transactions
            else component_settlements[0].currency
        )
        comparisons = []
        for transaction in component_transactions:
            for settlement_id in transaction_edges[transaction.id]:
                if settlement_id not in {item.id for item in component_settlements}:
                    continue
                settlement = settlements_by_id[settlement_id]
                comparisons.append(
                    {
                        "transaction_id": str(transaction.id),
                        "settlement_id": str(settlement.id),
                        "reference_equal": True,
                        "currency_equal": True,
                        "within_utc_window": True,
                        "amount_equal": transaction.amount == settlement.amount,
                    }
                )

        evidence: dict[str, Any] = {
            "algorithm_version": ALGORITHM_VERSION,
            "classification": classification.value,
            "reason_code": reason_code,
            "match_window_hours": match_window_hours,
            "criteria": {
                "reference": "exact",
                "currency": "exact",
                "settlement_delay_hours": {"minimum": 0, "maximum": match_window_hours},
                "money_comparison": "decimal",
            },
            "transactions": [_transaction_evidence(item) for item in component_transactions],
            "settlements": [_settlement_evidence(item) for item in component_settlements],
            "candidate_comparisons": comparisons,
            "totals": {
                "currency": currency,
                "transaction": _money(transaction_total),
                "settlement": _money(settlement_total),
                "difference": _money(difference),
            },
        }
        decisions.append(
            ReconciliationDecision(
                classification=classification,
                reason_code=reason_code,
                currency=currency,
                transactions=component_transactions,
                settlements=component_settlements,
                transaction_total=transaction_total,
                settlement_total=settlement_total,
                difference_amount=difference,
                evidence=evidence,
                evidence_sha256=_canonical_digest(evidence),
            )
        )

    return sorted(
        decisions,
        key=lambda item: (
            item.classification.value,
            tuple(str(fact.id) for fact in item.transactions),
            tuple(str(fact.id) for fact in item.settlements),
        ),
    )


def _replay_key(
    account_id: UUID,
    request: ReconciliationRunRequest,
    transactions: list[TransactionFact],
    settlements: list[SettlementFact],
) -> str:
    replay_input = {
        "algorithm_version": ALGORITHM_VERSION,
        "account_id": str(account_id),
        "input_cutoff_at": _utc_iso(request.input_cutoff_at),
        "configuration": {"match_window_hours": request.match_window_hours},
        "transactions": [
            _transaction_evidence(item) for item in sorted(transactions, key=lambda x: str(x.id))
        ],
        "settlements": [
            _settlement_evidence(item) for item in sorted(settlements, key=lambda x: str(x.id))
        ],
    }
    return _canonical_digest(replay_input)


def _model_facts(
    transactions: list[FinancialTransaction], settlements: list[Settlement]
) -> tuple[list[TransactionFact], list[SettlementFact]]:
    return (
        [
            TransactionFact(
                id=item.id,
                source_record_id=item.source_record_id,
                source_reference=item.source_reference,
                amount=Decimal(item.amount),
                currency=item.currency,
                occurred_at=item.occurred_at,
            )
            for item in transactions
        ],
        [
            SettlementFact(
                id=item.id,
                source_record_id=item.source_record_id,
                source_reference=item.source_reference,
                amount=Decimal(item.amount),
                currency=item.currency,
                settled_at=item.settled_at,
            )
            for item in settlements
        ],
    )


def _result_response(db: Session, result: ReconciliationResult) -> ReconciliationResultResponse:
    transaction_links = list(
        db.scalars(
            select(ReconciliationResultTransaction)
            .where(ReconciliationResultTransaction.result_id == result.id)
            .order_by(ReconciliationResultTransaction.transaction_id)
        ).all()
    )
    settlement_links = list(
        db.scalars(
            select(ReconciliationResultSettlement)
            .where(ReconciliationResultSettlement.result_id == result.id)
            .order_by(ReconciliationResultSettlement.settlement_id)
        ).all()
    )
    transaction_items = [
        (link, db.get(FinancialTransaction, link.transaction_id)) for link in transaction_links
    ]
    settlement_items = [(link, db.get(Settlement, link.settlement_id)) for link in settlement_links]
    if any(item is None for _, item in [*transaction_items, *settlement_items]):
        raise RuntimeError("Reconciliation evidence references a missing financial fact")

    return ReconciliationResultResponse(
        id=result.id,
        classification=result.classification,
        reason_code=result.reason_code,
        currency=result.currency,
        transaction_total=_money(Decimal(result.transaction_total)),
        settlement_total=_money(Decimal(result.settlement_total)),
        difference_amount=_money(Decimal(result.difference_amount)),
        evidence=result.evidence,
        evidence_sha256=result.evidence_sha256,
        transactions=[
            ReconciliationItemResponse(
                id=item.id,
                source_record_id=item.source_record_id,
                source_reference=item.source_reference,
                amount=_money(Decimal(item.amount)),
                currency=item.currency,
                occurred_at=item.occurred_at,
                item_role=link.item_role,
                allocated_amount=(
                    _money(Decimal(link.allocated_amount))
                    if link.allocated_amount is not None
                    else None
                ),
            )
            for link, item in transaction_items
            if item is not None
        ],
        settlements=[
            ReconciliationItemResponse(
                id=item.id,
                source_record_id=item.source_record_id,
                source_reference=item.source_reference,
                amount=_money(Decimal(item.amount)),
                currency=item.currency,
                settled_at=item.settled_at,
                item_role=link.item_role,
                allocated_amount=(
                    _money(Decimal(link.allocated_amount))
                    if link.allocated_amount is not None
                    else None
                ),
            )
            for link, item in settlement_items
            if item is not None
        ],
    )


def load_reconciliation_run_response(
    db: Session, run: ReconciliationRun, account: Account, *, replayed: bool
) -> ReconciliationRunResponse:
    results = list(
        db.scalars(
            select(ReconciliationResult)
            .where(ReconciliationResult.run_id == run.id)
            .order_by(ReconciliationResult.classification, ReconciliationResult.id)
        ).all()
    )
    responses = [_result_response(db, result) for result in results]
    transaction_ids = {item.id for result in responses for item in result.transactions}
    settlement_ids = {item.id for result in responses for item in result.settlements}
    classification_counts = {
        classification.value: sum(result.classification == classification for result in responses)
        for classification in ReconciliationClassification
    }
    return ReconciliationRunResponse(
        run_id=run.id,
        account_id=account.id,
        source_system=account.source_system,
        source_account_id=account.source_account_id,
        algorithm_version=run.algorithm_version,
        input_cutoff_at=run.input_cutoff_at,
        configuration=run.configuration,
        replay_key=run.replay_key,
        status=run.status,
        replayed=replayed,
        summary=ReconciliationSummary(
            transaction_count=len(transaction_ids),
            settlement_count=len(settlement_ids),
            transaction_value=_money(
                sum(
                    (Decimal(item.amount) for result in responses for item in result.transactions),
                    ZERO,
                )
            ),
            settlement_value=_money(
                sum(
                    (Decimal(item.amount) for result in responses for item in result.settlements),
                    ZERO,
                )
            ),
            result_count=len(responses),
            classification_counts=classification_counts,
        ),
        results=responses,
    )


def execute_reconciliation(
    db: Session,
    request: ReconciliationRunRequest,
    principal: AuthPrincipal,
    audit_correlation_id: UUID | None = None,
    audit_job_id: UUID | None = None,
) -> ReconciliationRunResponse:
    """Select eligible facts and atomically persist a reproducible run."""

    account = db.scalar(
        select(Account)
        .where(
            Account.source_system == request.source_system,
            Account.source_account_id == request.source_account_id,
            Account.status == AccountStatus.ACTIVE,
        )
        .with_for_update()
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Active account not found"
        )

    transaction_models = list(
        db.scalars(
            select(FinancialTransaction)
            .where(
                FinancialTransaction.account_id == account.id,
                FinancialTransaction.status == TransactionStatus.POSTED,
                FinancialTransaction.occurred_at <= request.input_cutoff_at,
            )
            .order_by(FinancialTransaction.id)
        ).all()
    )
    settlement_models = list(
        db.scalars(
            select(Settlement)
            .where(
                Settlement.account_id == account.id,
                Settlement.status == SettlementStatus.CONFIRMED,
                Settlement.settled_at <= request.input_cutoff_at,
            )
            .order_by(Settlement.id)
        ).all()
    )
    transaction_facts, settlement_facts = _model_facts(transaction_models, settlement_models)
    replay_key = _replay_key(account.id, request, transaction_facts, settlement_facts)
    existing = db.scalar(
        select(ReconciliationRun).where(ReconciliationRun.replay_key == replay_key)
    )
    if existing is not None:
        return load_reconciliation_run_response(db, existing, account, replayed=True)

    decisions = build_reconciliation_decisions(
        transaction_facts, settlement_facts, request.match_window_hours
    )
    now = datetime.now(UTC)
    run = ReconciliationRun(
        account_id=account.id,
        algorithm_version=ALGORITHM_VERSION,
        configuration={"match_window_hours": request.match_window_hours},
        input_cutoff_at=request.input_cutoff_at,
        replay_key=replay_key,
        status=ReconciliationRunStatus.RUNNING,
        requested_by_user_id=principal.user_id,
        correlation_id=audit_correlation_id or uuid4(),
        started_at=now,
    )

    try:
        db.add(run)
        db.flush()
        for decision in decisions:
            result = ReconciliationResult(
                run_id=run.id,
                classification=decision.classification,
                reason_code=decision.reason_code,
                currency=decision.currency,
                transaction_total=decision.transaction_total,
                settlement_total=decision.settlement_total,
                difference_amount=decision.difference_amount,
                evidence=decision.evidence,
                evidence_sha256=decision.evidence_sha256,
                review_status=ReconciliationReviewStatus.OPEN,
            )
            db.add(result)
            db.flush()
            role = (
                ReconciliationItemRole.CANDIDATE
                if decision.classification == ReconciliationClassification.DUPLICATE_CANDIDATE
                else ReconciliationItemRole.MATCHED
            )
            for transaction_fact in decision.transactions:
                db.add(
                    ReconciliationResultTransaction(
                        result_id=result.id,
                        transaction_id=transaction_fact.id,
                        item_role=role,
                        allocated_amount=(
                            transaction_fact.amount
                            if decision.classification == ReconciliationClassification.EXACT_MATCH
                            else None
                        ),
                    )
                )
            for settlement_fact in decision.settlements:
                db.add(
                    ReconciliationResultSettlement(
                        result_id=result.id,
                        settlement_id=settlement_fact.id,
                        item_role=role,
                        allocated_amount=(
                            settlement_fact.amount
                            if decision.classification == ReconciliationClassification.EXACT_MATCH
                            else None
                        ),
                    )
                )
        run.status = ReconciliationRunStatus.COMPLETED
        run.finished_at = datetime.now(UTC)
        append_audit_event(
            db,
            action="reconciliation.run.completed",
            target_type="reconciliation_run",
            target_id=run.id,
            actor_user_id=principal.user_id,
            correlation_id=run.correlation_id,
            job_id=audit_job_id,
            after_state={
                "status": run.status.value,
                "result_count": len(decisions),
                "algorithm_version": run.algorithm_version,
            },
            metadata={
                "schema_version": "audit-v1",
                "transaction_ids": [str(item.id) for item in transaction_models],
                "settlement_ids": [str(item.id) for item in settlement_models],
                "input_cutoff_at": request.input_cutoff_at.isoformat(),
            },
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.scalar(
            select(ReconciliationRun).where(ReconciliationRun.replay_key == replay_key)
        )
        if concurrent is not None:
            concurrent_account = db.get(Account, concurrent.account_id)
            if concurrent_account is None:
                raise RuntimeError("Reconciliation run references a missing account") from None
            return load_reconciliation_run_response(
                db, concurrent, concurrent_account, replayed=True
            )
        raise
    except SQLAlchemyError:
        db.rollback()
        raise

    return load_reconciliation_run_response(db, run, account, replayed=False)


router = APIRouter(prefix="/api/v1/reconciliation", tags=["reconciliation"])


@router.post("/runs", response_model=BackgroundJobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_reconciliation_run(
    request: ReconciliationRunRequest,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$",
        ),
    ],
    principal: Annotated[
        AuthPrincipal, Depends(require_permissions(Permission.RECONCILIATION_WRITE))
    ],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BackgroundJobResponse:
    enforce_synthetic_source(request.source_system, settings)
    result, replayed = enqueue_reconciliation_job(
        db,
        request_payload=request.model_dump(mode="json"),
        idempotency_key=idempotency_key,
        principal=principal,
    )
    if replayed:
        response.status_code = status.HTTP_200_OK
    return result


@router.get("/runs/{run_id}", response_model=ReconciliationRunResponse)
def read_reconciliation_run(
    run_id: UUID,
    _principal: Annotated[
        AuthPrincipal, Depends(require_permissions(Permission.RECONCILIATION_READ))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> ReconciliationRunResponse:
    run = db.get(ReconciliationRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    account = db.get(Account, run.account_id)
    if account is None:
        raise RuntimeError("Reconciliation run references a missing account")
    return load_reconciliation_run_response(db, run, account, replayed=False)
