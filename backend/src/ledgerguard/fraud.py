"""Deterministic, evidence-grounded fraud rule engine and API."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ledgerguard.audit_service import append_audit_event
from ledgerguard.auth import AuthPrincipal, Permission, require_permissions
from ledgerguard.db import get_db
from ledgerguard.models import (
    Account,
    AccountStatus,
    Alert,
    AlertSeverity,
    AlertStatus,
    FinancialTransaction,
    FraudRule,
    FraudRuleType,
    FraudRuleVersion,
    RuleVersionStatus,
    TransactionStatus,
)

EVIDENCE_SCHEMA_VERSION = "fraud-evidence-v1"
DECIMAL_PATTERN = re.compile(r"^(?:0|[1-9][0-9]{0,13})(?:\.[0-9]{1,6})?$")
FOUR_PLACES = Decimal("0.0001")


class RuleVersionInput(BaseModel):
    rule_type: FraudRuleType
    parameters: dict[str, Any]
    severity: AlertSeverity
    activate: bool = True

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        if any(isinstance(item, float) for item in value.values()):
            raise ValueError("binary floating-point rule parameters are not allowed")
        return value


class RuleCreateRequest(RuleVersionInput):
    code: str = Field(min_length=2, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)


class EvaluationRequest(BaseModel):
    source_system: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    source_account_id: str = Field(
        min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    input_cutoff_at: datetime

    @field_validator("input_cutoff_at")
    @classmethod
    def normalize_cutoff(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("input_cutoff_at must include a UTC offset")
        return value.astimezone(UTC)


class RuleVersionResponse(BaseModel):
    id: UUID
    rule_id: UUID
    version_number: int
    rule_type: FraudRuleType
    parameters: dict[str, Any]
    severity: AlertSeverity
    status: RuleVersionStatus
    activated_at: datetime | None


class RuleResponse(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None
    versions: list[RuleVersionResponse]


class AlertResponse(BaseModel):
    id: UUID
    rule_code: str
    rule_version_id: UUID
    rule_version_number: int
    transaction_id: UUID
    source_record_id: str
    severity: AlertSeverity
    score: str
    status: AlertStatus
    reason_code: str
    evidence: dict[str, Any]
    evidence_sha256: str
    correlation_id: UUID
    created_at: datetime


class EvaluationResponse(BaseModel):
    account_id: UUID
    input_cutoff_at: datetime
    active_rule_count: int
    subject_count: int
    triggered_count: int
    created_count: int
    replayed_count: int
    alerts: list[AlertResponse]


@dataclass(frozen=True, slots=True)
class FraudTransactionFact:
    id: UUID
    source_record_id: str
    source_reference: str
    amount: Decimal
    currency: str
    status: TransactionStatus
    instrument_fingerprint: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class FraudRuleSpec:
    id: UUID
    rule_id: UUID
    rule_code: str
    version_number: int
    rule_type: FraudRuleType
    parameters: dict[str, Any]
    severity: AlertSeverity


@dataclass(frozen=True, slots=True)
class FraudDecision:
    subject: FraudTransactionFact
    rule: FraudRuleSpec
    reason_code: str
    score: Decimal
    evidence: dict[str, Any]
    evidence_sha256: str
    deduplication_key: str


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _fact_evidence(fact: FraudTransactionFact) -> dict[str, str | None]:
    return {
        "id": str(fact.id),
        "source_record_id": fact.source_record_id,
        "source_reference": fact.source_reference,
        "amount": format(fact.amount, "f"),
        "currency": fact.currency,
        "status": fact.status.value,
        "instrument_fingerprint": fact.instrument_fingerprint,
        "occurred_at": _utc_iso(fact.occurred_at),
    }


def _positive_int(value: Any, name: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer from 1 through {maximum}")
    return int(value)


def _hour(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 23:
        raise ValueError(f"{name} must be an integer from 0 through 23")
    return int(value)


def _decimal_parameter(value: Any, name: str) -> Decimal:
    if not isinstance(value, str) or not DECIMAL_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a positive decimal string with at most 6 decimal places")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{name} must be a valid decimal string") from error
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


def normalize_rule_parameters(
    rule_type: FraudRuleType, parameters: dict[str, Any]
) -> dict[str, Any]:
    """Validate and normalize the exact parameter contract for a rule type."""

    normalized: dict[str, Any]
    if rule_type is FraudRuleType.VELOCITY:
        expected = {"window_minutes", "count_threshold"}
        normalized = {
            "window_minutes": _positive_int(
                parameters.get("window_minutes"), "window_minutes", maximum=10080
            ),
            "count_threshold": _positive_int(
                parameters.get("count_threshold"), "count_threshold", maximum=100000
            ),
        }
    elif rule_type is FraudRuleType.UNUSUAL_AMOUNT:
        expected = {"amount_threshold"}
        normalized = {
            "amount_threshold": format(
                _decimal_parameter(parameters.get("amount_threshold"), "amount_threshold"), "f"
            )
        }
    elif rule_type is FraudRuleType.REPEATED_FAILURE:
        expected = {"window_hours", "count_threshold"}
        normalized = {
            "window_hours": _positive_int(
                parameters.get("window_hours"), "window_hours", maximum=720
            ),
            "count_threshold": _positive_int(
                parameters.get("count_threshold"), "count_threshold", maximum=100000
            ),
        }
    elif rule_type is FraudRuleType.DUPLICATE_INSTRUMENT:
        expected = {"window_hours", "distinct_reference_threshold"}
        normalized = {
            "window_hours": _positive_int(
                parameters.get("window_hours"), "window_hours", maximum=720
            ),
            "distinct_reference_threshold": _positive_int(
                parameters.get("distinct_reference_threshold"),
                "distinct_reference_threshold",
                maximum=100000,
            ),
        }
    elif rule_type is FraudRuleType.SUSPICIOUS_TIMING:
        expected = {"start_hour_utc", "end_hour_utc"}
        normalized = {
            "start_hour_utc": _hour(parameters.get("start_hour_utc"), "start_hour_utc"),
            "end_hour_utc": _hour(parameters.get("end_hour_utc"), "end_hour_utc"),
        }
        if normalized["start_hour_utc"] == normalized["end_hour_utc"]:
            raise ValueError("suspicious timing interval cannot cover zero hours")
    else:
        raise ValueError(f"unsupported fraud rule type: {rule_type}")
    if set(parameters) != expected:
        unknown = sorted(set(parameters) - expected)
        missing = sorted(expected - set(parameters))
        raise ValueError(
            f"parameters must match the rule contract; missing={missing}, unknown={unknown}"
        )
    return normalized


def _score(metric: Decimal, threshold: Decimal) -> Decimal:
    exceedance = max(Decimal("0"), metric - threshold) / threshold
    return (Decimal("50") + min(Decimal("50"), exceedance * Decimal("50"))).quantize(
        FOUR_PLACES, rounding=ROUND_HALF_UP
    )


def _in_window(fact: FraudTransactionFact, subject: FraudTransactionFact, delta: timedelta) -> bool:
    lower = subject.occurred_at - delta
    return lower <= fact.occurred_at <= subject.occurred_at and (
        fact.occurred_at < subject.occurred_at or fact.id.int <= subject.id.int
    )


def evaluate_rule(
    rule: FraudRuleSpec,
    subject: FraudTransactionFact,
    facts: tuple[FraudTransactionFact, ...],
    input_cutoff_at: datetime,
) -> FraudDecision | None:
    """Evaluate one immutable rule version against one posted transaction."""

    parameters = normalize_rule_parameters(rule.rule_type, rule.parameters)
    matched: list[FraudTransactionFact]
    threshold: int | str
    metric: int | str

    if rule.rule_type is FraudRuleType.VELOCITY:
        matched = [
            fact
            for fact in facts
            if fact.status is TransactionStatus.POSTED
            and _in_window(fact, subject, timedelta(minutes=parameters["window_minutes"]))
        ]
        threshold = int(parameters["count_threshold"])
        metric = len(matched)
        triggered = metric >= threshold
        score = _score(Decimal(metric), Decimal(threshold))
        reason_code = "VELOCITY_THRESHOLD_MET"
    elif rule.rule_type is FraudRuleType.UNUSUAL_AMOUNT:
        matched = [subject]
        amount_threshold = Decimal(parameters["amount_threshold"])
        threshold = parameters["amount_threshold"]
        metric = format(subject.amount, "f")
        triggered = subject.amount >= amount_threshold
        score = _score(subject.amount, amount_threshold)
        reason_code = "UNUSUAL_AMOUNT_THRESHOLD_MET"
    elif rule.rule_type is FraudRuleType.REPEATED_FAILURE:
        if subject.instrument_fingerprint is None:
            return None
        matched = [
            fact
            for fact in facts
            if fact.instrument_fingerprint == subject.instrument_fingerprint
            and fact.status in {TransactionStatus.VOIDED, TransactionStatus.REVERSED}
            and _in_window(fact, subject, timedelta(hours=parameters["window_hours"]))
        ]
        threshold = int(parameters["count_threshold"])
        metric = len(matched)
        triggered = metric >= threshold
        score = _score(Decimal(metric), Decimal(threshold))
        reason_code = "REPEATED_FAILURE_THRESHOLD_MET"
    elif rule.rule_type is FraudRuleType.DUPLICATE_INSTRUMENT:
        if subject.instrument_fingerprint is None:
            return None
        matched = [
            fact
            for fact in facts
            if fact.status is TransactionStatus.POSTED
            and fact.instrument_fingerprint == subject.instrument_fingerprint
            and _in_window(fact, subject, timedelta(hours=parameters["window_hours"]))
        ]
        references = {fact.source_reference for fact in matched}
        threshold = int(parameters["distinct_reference_threshold"])
        metric = len(references)
        triggered = metric >= threshold
        score = _score(Decimal(metric), Decimal(threshold))
        reason_code = "DUPLICATE_INSTRUMENT_THRESHOLD_MET"
    elif rule.rule_type is FraudRuleType.SUSPICIOUS_TIMING:
        matched = [subject]
        hour = subject.occurred_at.astimezone(UTC).hour
        start = parameters["start_hour_utc"]
        end = parameters["end_hour_utc"]
        triggered = start <= hour < end if start < end else hour >= start or hour < end
        threshold = f"[{start:02d}:00,{end:02d}:00) UTC"
        metric = hour
        score = Decimal("50.0000")
        reason_code = "SUSPICIOUS_UTC_TIME_WINDOW"
    else:
        raise ValueError(f"unsupported fraud rule type: {rule.rule_type}")

    if not triggered:
        return None
    matched.sort(key=lambda fact: (fact.occurred_at, fact.id.int))
    evidence: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "rule": {
            "id": str(rule.rule_id),
            "code": rule.rule_code,
            "version_id": str(rule.id),
            "version_number": rule.version_number,
            "type": rule.rule_type.value,
            "parameters": parameters,
        },
        "subject": _fact_evidence(subject),
        "evaluated_inputs": {
            "metric": metric,
            "threshold": threshold,
            "matched_facts": [_fact_evidence(fact) for fact in matched],
        },
        "output": {
            "triggered": True,
            "reason_code": reason_code,
            "score": format(score, "f"),
            "severity": rule.severity.value,
        },
        "input_cutoff_at": _utc_iso(input_cutoff_at),
    }
    digest = _canonical_digest(evidence)
    deduplication_key = _canonical_digest(
        {
            "rule_version_id": str(rule.id),
            "transaction_id": str(subject.id),
            "evidence_sha256": digest,
        }
    )
    return FraudDecision(subject, rule, reason_code, score, evidence, digest, deduplication_key)


def build_fraud_decisions(
    rules: tuple[FraudRuleSpec, ...],
    facts: tuple[FraudTransactionFact, ...],
    input_cutoff_at: datetime,
) -> tuple[FraudDecision, ...]:
    """Return all deterministic triggered decisions in stable order."""

    ordered_facts = tuple(sorted(facts, key=lambda fact: (fact.occurred_at, fact.id.int)))
    subjects = tuple(fact for fact in ordered_facts if fact.status is TransactionStatus.POSTED)
    decisions = [
        decision
        for rule in sorted(
            rules, key=lambda item: (item.rule_code, item.version_number, item.id.int)
        )
        for subject in subjects
        if (decision := evaluate_rule(rule, subject, ordered_facts, input_cutoff_at)) is not None
    ]
    return tuple(decisions)


def _version_response(version: FraudRuleVersion) -> RuleVersionResponse:
    return RuleVersionResponse(
        id=version.id,
        rule_id=version.rule_id,
        version_number=version.version_number,
        rule_type=version.rule_type,
        parameters=version.parameters,
        severity=version.severity,
        status=version.status,
        activated_at=version.activated_at,
    )


def _alert_response(
    alert: Alert, rule: FraudRule, version: FraudRuleVersion, transaction: FinancialTransaction
) -> AlertResponse:
    if alert.transaction_id is None or alert.score is None:
        raise RuntimeError("fraud transaction alert is missing required persisted fields")
    return AlertResponse(
        id=alert.id,
        rule_code=rule.code,
        rule_version_id=version.id,
        rule_version_number=version.version_number,
        transaction_id=alert.transaction_id,
        source_record_id=transaction.source_record_id,
        severity=alert.severity,
        score=format(alert.score, "f"),
        status=alert.status,
        reason_code=alert.reason_code,
        evidence=alert.evidence,
        evidence_sha256=alert.evidence_sha256,
        correlation_id=alert.correlation_id,
        created_at=alert.created_at,
    )


def _activate_version(
    db: Session, version: FraudRuleVersion, actor_id: UUID, activated_at: datetime
) -> None:
    current = db.scalar(
        select(FraudRuleVersion)
        .where(
            FraudRuleVersion.rule_id == version.rule_id,
            FraudRuleVersion.status == RuleVersionStatus.ACTIVE,
        )
        .with_for_update()
    )
    if current is not None:
        current.status = RuleVersionStatus.RETIRED
        current.retired_at = activated_at
    version.status = RuleVersionStatus.ACTIVE
    version.activated_by_user_id = actor_id
    version.activated_at = activated_at


router = APIRouter(prefix="/api/v1/fraud", tags=["fraud-monitoring"])


@router.get("/rules", response_model=list[RuleResponse])
def list_rules(
    _: Annotated[AuthPrincipal, Depends(require_permissions(Permission.ALERTS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> list[RuleResponse]:
    rules = list(db.scalars(select(FraudRule).order_by(FraudRule.code)))
    versions = list(
        db.scalars(
            select(FraudRuleVersion).order_by(
                FraudRuleVersion.rule_id, FraudRuleVersion.version_number
            )
        )
    )
    by_rule: dict[UUID, list[RuleVersionResponse]] = {}
    for version in versions:
        by_rule.setdefault(version.rule_id, []).append(_version_response(version))
    return [
        RuleResponse(
            id=rule.id,
            code=rule.code,
            name=rule.name,
            description=rule.description,
            versions=by_rule.get(rule.id, []),
        )
        for rule in rules
    ]


@router.post("/rules", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
def create_rule(
    request: RuleCreateRequest,
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.RULES_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> RuleResponse:
    try:
        parameters = normalize_rule_parameters(request.rule_type, request.parameters)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    rule = FraudRule(
        code=request.code,
        name=request.name.strip(),
        description=request.description.strip() if request.description else None,
        created_by_user_id=principal.user_id,
    )
    try:
        db.add(rule)
        db.flush()
        version = FraudRuleVersion(
            rule_id=rule.id,
            version_number=1,
            rule_type=request.rule_type,
            parameters=parameters,
            severity=request.severity,
            status=RuleVersionStatus.DRAFT,
            created_by_user_id=principal.user_id,
        )
        db.add(version)
        if request.activate:
            _activate_version(db, version, principal.user_id, datetime.now(UTC))
        append_audit_event(
            db,
            action="fraud.rule.created",
            target_type="fraud_rule",
            target_id=rule.id,
            actor_user_id=principal.user_id,
            after_state={
                "code": rule.code,
                "version_number": version.version_number,
                "version_status": version.status.value,
            },
            metadata={"schema_version": "audit-v1", "rule_type": version.rule_type.value},
        )
        db.commit()
        db.refresh(rule)
        db.refresh(version)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Rule code already exists"
        ) from error
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Rule could not be stored"
        ) from error
    return RuleResponse(
        id=rule.id,
        code=rule.code,
        name=rule.name,
        description=rule.description,
        versions=[_version_response(version)],
    )


@router.post(
    "/rules/{rule_id}/versions",
    response_model=RuleVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_rule_version(
    rule_id: UUID,
    request: RuleVersionInput,
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.RULES_MANAGE))],
    db: Annotated[Session, Depends(get_db)],
) -> RuleVersionResponse:
    rule = db.scalar(select(FraudRule).where(FraudRule.id == rule_id).with_for_update())
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    try:
        parameters = normalize_rule_parameters(request.rule_type, request.parameters)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    latest = db.scalar(
        select(FraudRuleVersion.version_number)
        .where(FraudRuleVersion.rule_id == rule_id)
        .order_by(FraudRuleVersion.version_number.desc())
        .limit(1)
    )
    version = FraudRuleVersion(
        rule_id=rule.id,
        version_number=(latest or 0) + 1,
        rule_type=request.rule_type,
        parameters=parameters,
        severity=request.severity,
        status=RuleVersionStatus.DRAFT,
        created_by_user_id=principal.user_id,
    )
    db.add(version)
    if request.activate:
        _activate_version(db, version, principal.user_id, datetime.now(UTC))
    append_audit_event(
        db,
        action="fraud.rule.version_created",
        target_type="fraud_rule",
        target_id=rule.id,
        actor_user_id=principal.user_id,
        after_state={
            "version_number": version.version_number,
            "version_status": version.status.value,
        },
        metadata={"schema_version": "audit-v1", "rule_type": version.rule_type.value},
    )
    try:
        db.commit()
        db.refresh(version)
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rule version could not be stored",
        ) from error
    return _version_response(version)


@router.post("/evaluations", response_model=EvaluationResponse)
def run_evaluation(
    request: EvaluationRequest,
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.ALERTS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
) -> EvaluationResponse:
    account = db.scalar(
        select(Account).where(
            Account.source_system == request.source_system,
            Account.source_account_id == request.source_account_id,
            Account.status == AccountStatus.ACTIVE,
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Active source account not found"
        )
    rule_rows = db.execute(
        select(FraudRule, FraudRuleVersion)
        .join(FraudRuleVersion, FraudRuleVersion.rule_id == FraudRule.id)
        .where(FraudRuleVersion.status == RuleVersionStatus.ACTIVE)
        .order_by(FraudRule.code)
    ).all()
    transactions = list(
        db.scalars(
            select(FinancialTransaction)
            .where(
                FinancialTransaction.account_id == account.id,
                FinancialTransaction.occurred_at <= request.input_cutoff_at,
            )
            .order_by(FinancialTransaction.occurred_at, FinancialTransaction.id)
        )
    )
    facts = tuple(
        FraudTransactionFact(
            id=item.id,
            source_record_id=item.source_record_id,
            source_reference=item.source_reference,
            amount=Decimal(item.amount),
            currency=item.currency,
            status=item.status,
            instrument_fingerprint=item.instrument_fingerprint,
            occurred_at=item.occurred_at,
        )
        for item in transactions
    )
    specs = tuple(
        FraudRuleSpec(
            id=version.id,
            rule_id=rule.id,
            rule_code=rule.code,
            version_number=version.version_number,
            rule_type=version.rule_type,
            parameters=version.parameters,
            severity=version.severity,
        )
        for rule, version in rule_rows
    )
    try:
        decisions = build_fraud_decisions(specs, facts, request.input_cutoff_at)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Active rule configuration is invalid: {error}",
        ) from error

    rule_by_version = {version.id: (rule, version) for rule, version in rule_rows}
    transaction_by_id = {item.id: item for item in transactions}
    alerts: list[AlertResponse] = []
    created_count = 0
    evaluation_correlation_id = uuid4()
    for decision in decisions:
        existing = db.scalar(
            select(Alert).where(Alert.deduplication_key == decision.deduplication_key)
        )
        if existing is None:
            existing = Alert(
                rule_version_id=decision.rule.id,
                transaction_id=decision.subject.id,
                deduplication_key=decision.deduplication_key,
                severity=decision.rule.severity,
                score=decision.score,
                status=AlertStatus.OPEN,
                reason_code=decision.reason_code,
                evidence=decision.evidence,
                evidence_sha256=decision.evidence_sha256,
                correlation_id=evaluation_correlation_id,
            )
            db.add(existing)
            db.flush()
            append_audit_event(
                db,
                action="fraud.alert.created",
                target_type="alert",
                target_id=existing.id,
                actor_user_id=principal.user_id,
                correlation_id=evaluation_correlation_id,
                after_state={
                    "status": existing.status.value,
                    "severity": existing.severity.value,
                    "rule_version_id": str(existing.rule_version_id),
                },
                metadata={
                    "schema_version": "audit-v1",
                    "transaction_id": str(decision.subject.id),
                    "evidence_sha256": existing.evidence_sha256,
                    "reason_code": existing.reason_code,
                },
            )
            created_count += 1
        rule, version = rule_by_version[existing.rule_version_id]
        if existing.transaction_id is None:
            raise RuntimeError("fraud alert unexpectedly lacks a transaction")
        transaction = transaction_by_id[existing.transaction_id]
        alerts.append(_alert_response(existing, rule, version, transaction))
    append_audit_event(
        db,
        action="fraud.evaluation.completed",
        target_type="account",
        target_id=account.id,
        actor_user_id=principal.user_id,
        correlation_id=evaluation_correlation_id,
        after_state={
            "triggered_count": len(decisions),
            "created_count": created_count,
            "replayed_count": len(decisions) - created_count,
        },
        metadata={
            "schema_version": "audit-v1",
            "alert_ids": [str(item.id) for item in alerts],
            "transaction_ids": [str(item.transaction_id) for item in alerts],
            "input_cutoff_at": request.input_cutoff_at.isoformat(),
        },
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Concurrent evaluation conflict; retry safely",
        ) from error
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Evaluation could not be stored"
        ) from error
    subject_count = sum(fact.status is TransactionStatus.POSTED for fact in facts)
    return EvaluationResponse(
        account_id=account.id,
        input_cutoff_at=request.input_cutoff_at,
        active_rule_count=len(specs),
        subject_count=subject_count,
        triggered_count=len(decisions),
        created_count=created_count,
        replayed_count=len(decisions) - created_count,
        alerts=alerts,
    )


@router.get("/alerts", response_model=list[AlertResponse])
def list_alerts(
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.ALERTS_READ))],
    db: Annotated[Session, Depends(get_db)],
    response: Response,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AlertResponse]:
    rows = db.execute(
        select(Alert, FraudRule, FraudRuleVersion, FinancialTransaction)
        .join(FraudRuleVersion, FraudRuleVersion.id == Alert.rule_version_id)
        .join(FraudRule, FraudRule.id == FraudRuleVersion.rule_id)
        .join(FinancialTransaction, FinancialTransaction.id == Alert.transaction_id)
        .order_by(Alert.created_at.desc(), Alert.id)
        .limit(limit)
    ).all()
    response.headers["X-Result-Limit"] = str(limit)
    result = [
        _alert_response(alert, rule, version, transaction)
        for alert, rule, version, transaction in rows
    ]
    append_audit_event(
        db,
        action="fraud.alerts.read",
        target_type="alert_collection",
        actor_user_id=principal.user_id,
        metadata={"schema_version": "audit-v1", "result_count": len(result), "limit": limit},
    )
    db.commit()
    return result
