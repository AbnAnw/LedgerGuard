"""Case queue, investigation timeline, and controlled lifecycle transitions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, NoReturn
from uuid import UUID, uuid4

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ledgerguard.audit_service import append_audit_event
from ledgerguard.auth import AuthPrincipal, Permission, require_permissions
from ledgerguard.db import get_db
from ledgerguard.models import (
    Alert,
    AlertStatus,
    AuditResult,
    CaseAlert,
    CaseComment,
    CasePriority,
    CaseStatus,
    CaseStatusHistory,
    FinancialTransaction,
    FraudRule,
    FraudRuleVersion,
    InvestigationCase,
    User,
    UserRole,
    UserStatus,
)

ALLOWED_OWNER_ROLES = frozenset({"administrator", "operations_analyst"})
TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.OPEN: frozenset({CaseStatus.IN_REVIEW, CaseStatus.ESCALATED}),
    CaseStatus.IN_REVIEW: frozenset({CaseStatus.ESCALATED, CaseStatus.RESOLVED}),
    CaseStatus.ESCALATED: frozenset({CaseStatus.IN_REVIEW, CaseStatus.RESOLVED}),
    CaseStatus.RESOLVED: frozenset({CaseStatus.REOPENED}),
    CaseStatus.REOPENED: frozenset(
        {CaseStatus.IN_REVIEW, CaseStatus.ESCALATED, CaseStatus.RESOLVED}
    ),
}


class ResolutionCode(StrEnum):
    CONFIRMED_ISSUE = "confirmed_issue"
    FALSE_POSITIVE = "false_positive"
    NO_ACTION = "no_action"
    DUPLICATE = "duplicate"


def _clean_required(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("must not be blank")
    return cleaned


class CaseCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    priority: CasePriority
    owner_user_id: UUID | None = None
    alert_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return _clean_required(value)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("alert_ids")
    @classmethod
    def unique_alerts(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("alert_ids must not contain duplicates")
        return value


class VersionedRequest(BaseModel):
    expected_version: int = Field(ge=1)


class AssignmentRequest(VersionedRequest):
    owner_user_id: UUID | None


class CommentRequest(VersionedRequest):
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def clean_body(cls, value: str) -> str:
        return _clean_required(value)


class AlertLinkRequest(VersionedRequest):
    alert_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("alert_ids")
    @classmethod
    def unique_alerts(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("alert_ids must not contain duplicates")
        return value


class TransitionRequest(VersionedRequest):
    to_status: CaseStatus
    reason: str = Field(min_length=1, max_length=2000)
    resolution_code: ResolutionCode | None = None
    resolution_summary: str | None = Field(default=None, max_length=4000)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return _clean_required(value)

    @field_validator("resolution_summary")
    @classmethod
    def clean_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_required(value)


class CaseSummaryResponse(BaseModel):
    id: UUID
    case_number: int
    title: str
    status: CaseStatus
    priority: CasePriority
    owner_user_id: UUID | None
    owner_display_name: str | None
    alert_count: int
    created_at: datetime
    updated_at: datetime
    version: int


class CaseAlertResponse(BaseModel):
    id: UUID
    rule_code: str
    rule_version_number: int
    source_record_id: str
    severity: str
    score: str | None
    status: AlertStatus
    reason_code: str
    created_at: datetime


class CaseCommentResponse(BaseModel):
    id: UUID
    author_user_id: UUID
    author_display_name: str
    body: str
    created_at: datetime


class CaseHistoryResponse(BaseModel):
    id: UUID
    from_status: CaseStatus | None
    to_status: CaseStatus
    reason: str
    changed_by_user_id: UUID
    changed_by_display_name: str
    correlation_id: UUID
    changed_at: datetime


class CaseDetailResponse(CaseSummaryResponse):
    description: str | None
    resolution_code: str | None
    resolution_summary: str | None
    resolved_at: datetime | None
    alerts: list[CaseAlertResponse]
    comments: list[CaseCommentResponse]
    history: list[CaseHistoryResponse]


def validate_transition(current: CaseStatus, target: CaseStatus) -> None:
    """Reject same-state, skipped, and backward case transitions."""

    if target not in TRANSITIONS[current]:
        raise ValueError(f"transition from {current.value} to {target.value} is not allowed")


def validate_resolution(request: TransitionRequest) -> None:
    """Ensure resolution evidence exists only on a resolution transition."""

    if request.to_status is CaseStatus.RESOLVED:
        if request.resolution_code is None or request.resolution_summary is None:
            raise ValueError("resolution_code and resolution_summary are required when resolving")
    elif request.resolution_code is not None or request.resolution_summary is not None:
        raise ValueError("resolution fields are allowed only when resolving")


def apply_transition(
    investigation: InvestigationCase,
    request: TransitionRequest,
    linked_alerts: list[Alert],
    actor_id: UUID,
    correlation_id: UUID,
    changed_at: datetime,
) -> CaseStatusHistory:
    """Apply one validated, deterministic case transition to loaded records."""

    validate_transition(investigation.status, request.to_status)
    validate_resolution(request)
    old_status = investigation.status
    investigation.status = request.to_status
    investigation.updated_at = changed_at
    investigation.version += 1
    if request.to_status is CaseStatus.RESOLVED:
        if request.resolution_code is None or request.resolution_summary is None:
            raise ValueError("resolution evidence unexpectedly missing")
        investigation.resolution_code = request.resolution_code.value
        investigation.resolution_summary = request.resolution_summary
        investigation.resolved_at = changed_at
        alert_status = (
            AlertStatus.CLOSED
            if request.resolution_code is ResolutionCode.CONFIRMED_ISSUE
            else AlertStatus.DISMISSED
        )
        for alert in linked_alerts:
            alert.status = alert_status
            alert.closed_by_user_id = actor_id
            alert.closed_at = changed_at
            alert.version += 1
    else:
        investigation.resolution_code = None
        investigation.resolution_summary = None
        investigation.resolved_at = None
        for alert in linked_alerts:
            alert.status = AlertStatus.IN_REVIEW
            alert.closed_by_user_id = None
            alert.closed_at = None
            alert.version += 1
    return CaseStatusHistory(
        case_id=investigation.id,
        from_status=old_status,
        to_status=request.to_status,
        reason=request.reason,
        changed_by_user_id=actor_id,
        correlation_id=correlation_id,
        changed_at=changed_at,
    )


def _not_found() -> NoReturn:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")


def _check_version(investigation: InvestigationCase, expected: int) -> None:
    if investigation.version != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CASE_VERSION_CONFLICT",
                "message": "Case changed since it was loaded; refresh and retry",
            },
        )


def _load_case(db: Session, case_id: UUID, *, lock: bool = False) -> InvestigationCase:
    statement = select(InvestigationCase).where(InvestigationCase.id == case_id)
    if lock:
        statement = statement.with_for_update()
    investigation = db.scalar(statement)
    if investigation is None:
        _not_found()
    return investigation


def _valid_owner(db: Session, owner_id: UUID) -> User:
    owner = db.scalar(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .where(
            User.id == owner_id,
            User.status == UserStatus.ACTIVE,
            UserRole.revoked_at.is_(None),
            UserRole.role_code.in_(ALLOWED_OWNER_ROLES),
        )
        .limit(1)
    )
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Owner must be an active administrator or operations analyst",
        )
    return owner


def _locked_alerts_for_link(db: Session, alert_ids: list[UUID]) -> list[Alert]:
    alerts = list(db.scalars(select(Alert).where(Alert.id.in_(alert_ids)).with_for_update()).all())
    if len(alerts) != len(alert_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    existing = db.scalar(select(CaseAlert).where(CaseAlert.alert_id.in_(alert_ids)).limit(1))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An alert is already linked to a case",
        )
    if any(alert.status not in {AlertStatus.OPEN, AlertStatus.IN_REVIEW} for alert in alerts):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Closed or dismissed alerts cannot be linked to an active case",
        )
    return alerts


def _linked_alerts(db: Session, case_id: UUID, *, lock: bool = False) -> list[Alert]:
    statement = (
        select(Alert)
        .join(CaseAlert, CaseAlert.alert_id == Alert.id)
        .where(CaseAlert.case_id == case_id)
        .order_by(Alert.created_at, Alert.id)
    )
    if lock:
        statement = statement.with_for_update()
    return list(db.scalars(statement).all())


def _summary(
    investigation: InvestigationCase, alert_count: int, owner_name: str | None
) -> CaseSummaryResponse:
    return CaseSummaryResponse(
        id=investigation.id,
        case_number=investigation.case_number,
        title=investigation.title,
        status=investigation.status,
        priority=investigation.priority,
        owner_user_id=investigation.owner_user_id,
        owner_display_name=owner_name,
        alert_count=alert_count,
        created_at=investigation.created_at,
        updated_at=investigation.updated_at,
        version=investigation.version,
    )


def _detail(db: Session, investigation: InvestigationCase) -> CaseDetailResponse:
    owner_name = None
    if investigation.owner_user_id is not None:
        owner_name = db.scalar(
            select(User.display_name).where(User.id == investigation.owner_user_id)
        )
    alert_rows = db.execute(
        select(Alert, FraudRule, FraudRuleVersion, FinancialTransaction)
        .join(CaseAlert, CaseAlert.alert_id == Alert.id)
        .join(FraudRuleVersion, FraudRuleVersion.id == Alert.rule_version_id)
        .join(FraudRule, FraudRule.id == FraudRuleVersion.rule_id)
        .join(FinancialTransaction, FinancialTransaction.id == Alert.transaction_id)
        .where(CaseAlert.case_id == investigation.id)
        .order_by(Alert.created_at, Alert.id)
    ).all()
    comment_rows = db.execute(
        select(CaseComment, User)
        .join(User, User.id == CaseComment.author_user_id)
        .where(CaseComment.case_id == investigation.id)
        .order_by(CaseComment.created_at, CaseComment.id)
    ).all()
    history_rows = db.execute(
        select(CaseStatusHistory, User)
        .join(User, User.id == CaseStatusHistory.changed_by_user_id)
        .where(CaseStatusHistory.case_id == investigation.id)
        .order_by(CaseStatusHistory.changed_at, CaseStatusHistory.id)
    ).all()
    summary = _summary(investigation, len(alert_rows), owner_name)
    return CaseDetailResponse(
        **summary.model_dump(),
        description=investigation.description,
        resolution_code=investigation.resolution_code,
        resolution_summary=investigation.resolution_summary,
        resolved_at=investigation.resolved_at,
        alerts=[
            CaseAlertResponse(
                id=alert.id,
                rule_code=rule.code,
                rule_version_number=version.version_number,
                source_record_id=transaction.source_record_id,
                severity=alert.severity.value,
                score=format(alert.score, "f") if alert.score is not None else None,
                status=alert.status,
                reason_code=alert.reason_code,
                created_at=alert.created_at,
            )
            for alert, rule, version, transaction in alert_rows
        ],
        comments=[
            CaseCommentResponse(
                id=comment.id,
                author_user_id=comment.author_user_id,
                author_display_name=author.display_name,
                body=comment.body,
                created_at=comment.created_at,
            )
            for comment, author in comment_rows
        ],
        history=[
            CaseHistoryResponse(
                id=entry.id,
                from_status=entry.from_status,
                to_status=entry.to_status,
                reason=entry.reason,
                changed_by_user_id=entry.changed_by_user_id,
                changed_by_display_name=actor.display_name,
                correlation_id=entry.correlation_id,
                changed_at=entry.changed_at,
            )
            for entry, actor in history_rows
        ],
    )


def _commit(db: Session, message: str) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message) from error
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Case change could not be stored",
        ) from error


router = APIRouter(prefix="/api/v1/cases", tags=["case-management"])


@router.post("", response_model=CaseDetailResponse, status_code=status.HTTP_201_CREATED)
def create_case(
    request: CaseCreateRequest,
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.CASES_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    request_id: Annotated[UUID | None, Header(alias="X-Request-ID")] = None,
) -> CaseDetailResponse:
    if request.owner_user_id is not None:
        _valid_owner(db, request.owner_user_id)
    alerts = _locked_alerts_for_link(db, request.alert_ids)
    now = datetime.now(UTC)
    investigation = InvestigationCase(
        title=request.title,
        description=request.description,
        status=CaseStatus.OPEN,
        priority=request.priority,
        owner_user_id=request.owner_user_id,
        created_by_user_id=principal.user_id,
        updated_at=now,
    )
    db.add(investigation)
    db.flush()
    db.add(
        CaseStatusHistory(
            case_id=investigation.id,
            from_status=None,
            to_status=CaseStatus.OPEN,
            reason="Case created from fraud alert evidence",
            changed_by_user_id=principal.user_id,
            correlation_id=request_id or uuid4(),
            changed_at=now,
        )
    )
    for alert in alerts:
        db.add(
            CaseAlert(
                case_id=investigation.id,
                alert_id=alert.id,
                linked_by_user_id=principal.user_id,
                linked_at=now,
            )
        )
        alert.status = AlertStatus.IN_REVIEW
        alert.version += 1
    append_audit_event(
        db,
        action="case.created",
        target_type="case",
        target_id=investigation.id,
        actor_user_id=principal.user_id,
        correlation_id=request_id,
        after_state={
            "status": investigation.status.value,
            "priority": investigation.priority.value,
            "owner_user_id": str(investigation.owner_user_id)
            if investigation.owner_user_id
            else None,
            "version": investigation.version,
        },
        metadata={
            "schema_version": "audit-v1",
            "alert_ids": [str(alert.id) for alert in alerts],
            "transaction_ids": [
                str(alert.transaction_id) for alert in alerts if alert.transaction_id is not None
            ],
        },
    )
    _commit(db, "Case or alert link conflicted with another request")
    return _detail(db, investigation)


@router.get("", response_model=list[CaseSummaryResponse])
def list_cases(
    _: Annotated[AuthPrincipal, Depends(require_permissions(Permission.CASES_READ))],
    db: Annotated[Session, Depends(get_db)],
    owner_user_id: UUID | None = None,
    unassigned: bool = False,
    priority: CasePriority | None = None,
    case_status: Annotated[CaseStatus | None, Query(alias="status")] = None,
    rule_code: Annotated[str | None, Query(min_length=2, max_length=80)] = None,
    min_age_hours: Annotated[int | None, Query(ge=0, le=87600)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[CaseSummaryResponse]:
    if unassigned and owner_user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="owner_user_id and unassigned cannot be combined",
        )
    alert_count = sa.func.count(CaseAlert.alert_id).label("alert_count")
    statement = (
        select(InvestigationCase, alert_count)
        .outerjoin(CaseAlert, CaseAlert.case_id == InvestigationCase.id)
        .group_by(InvestigationCase.id)
    )
    if unassigned:
        statement = statement.where(InvestigationCase.owner_user_id.is_(None))
    elif owner_user_id is not None:
        statement = statement.where(InvestigationCase.owner_user_id == owner_user_id)
    if priority is not None:
        statement = statement.where(InvestigationCase.priority == priority)
    if case_status is not None:
        statement = statement.where(InvestigationCase.status == case_status)
    if min_age_hours is not None:
        statement = statement.where(
            InvestigationCase.created_at <= datetime.now(UTC) - timedelta(hours=min_age_hours)
        )
    if rule_code is not None:
        matching_cases = (
            select(CaseAlert.case_id)
            .join(Alert, Alert.id == CaseAlert.alert_id)
            .join(FraudRuleVersion, FraudRuleVersion.id == Alert.rule_version_id)
            .join(FraudRule, FraudRule.id == FraudRuleVersion.rule_id)
            .where(FraudRule.code == rule_code)
        )
        statement = statement.where(InvestigationCase.id.in_(matching_cases))
    priority_order = sa.case(
        (InvestigationCase.priority == CasePriority.CRITICAL, 0),
        (InvestigationCase.priority == CasePriority.HIGH, 1),
        (InvestigationCase.priority == CasePriority.MEDIUM, 2),
        else_=3,
    )
    rows = db.execute(
        statement.order_by(
            priority_order, InvestigationCase.updated_at, InvestigationCase.case_number
        ).limit(limit)
    ).all()
    owner_ids = {case.owner_user_id for case, _ in rows if case.owner_user_id is not None}
    owners = {
        owner_id: name
        for owner_id, name in db.execute(
            select(User.id, User.display_name).where(User.id.in_(owner_ids))
        ).all()
    }
    return [
        _summary(investigation, count, owners.get(investigation.owner_user_id))
        for investigation, count in rows
    ]


@router.get("/{case_id}", response_model=CaseDetailResponse)
def get_case(
    case_id: UUID,
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.CASES_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> CaseDetailResponse:
    investigation = _load_case(db, case_id)
    append_audit_event(
        db,
        action="case.read",
        target_type="case",
        target_id=case_id,
        actor_user_id=principal.user_id,
        metadata={"schema_version": "audit-v1"},
    )
    db.commit()
    return _detail(db, investigation)


@router.patch("/{case_id}/assignment", response_model=CaseDetailResponse)
def assign_case(
    case_id: UUID,
    request: AssignmentRequest,
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.CASES_WRITE))],
    db: Annotated[Session, Depends(get_db)],
) -> CaseDetailResponse:
    investigation = _load_case(db, case_id, lock=True)
    _check_version(investigation, request.expected_version)
    if investigation.status is CaseStatus.RESOLVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Resolved cases cannot be reassigned"
        )
    if request.owner_user_id is not None:
        _valid_owner(db, request.owner_user_id)
    previous_owner = investigation.owner_user_id
    previous_version = investigation.version
    investigation.owner_user_id = request.owner_user_id
    investigation.updated_at = datetime.now(UTC)
    investigation.version += 1
    append_audit_event(
        db,
        action="case.assigned",
        target_type="case",
        target_id=case_id,
        actor_user_id=principal.user_id,
        before_state={
            "owner_user_id": str(previous_owner) if previous_owner else None,
            "version": previous_version,
        },
        after_state={
            "owner_user_id": str(investigation.owner_user_id)
            if investigation.owner_user_id
            else None,
            "version": investigation.version,
        },
        metadata={"schema_version": "audit-v1"},
    )
    _commit(db, "Concurrent case assignment conflict; refresh and retry")
    return _detail(db, investigation)


@router.post("/{case_id}/comments", response_model=CaseDetailResponse)
def add_comment(
    case_id: UUID,
    request: CommentRequest,
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.CASES_WRITE))],
    db: Annotated[Session, Depends(get_db)],
) -> CaseDetailResponse:
    investigation = _load_case(db, case_id, lock=True)
    _check_version(investigation, request.expected_version)
    now = datetime.now(UTC)
    comment = CaseComment(
        id=uuid4(),
        case_id=case_id,
        author_user_id=principal.user_id,
        body=request.body,
    )
    db.add(comment)
    previous_version = investigation.version
    investigation.updated_at = now
    investigation.version += 1
    append_audit_event(
        db,
        action="case.comment_added",
        target_type="case",
        target_id=case_id,
        actor_user_id=principal.user_id,
        before_state={"version": previous_version},
        after_state={"version": investigation.version},
        metadata={
            "schema_version": "audit-v1",
            "comment_id": str(comment.id),
            "body_length": len(request.body),
        },
    )
    _commit(db, "Concurrent case comment conflict; refresh and retry")
    return _detail(db, investigation)


@router.post("/{case_id}/alerts", response_model=CaseDetailResponse)
def link_alerts(
    case_id: UUID,
    request: AlertLinkRequest,
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.CASES_WRITE))],
    db: Annotated[Session, Depends(get_db)],
) -> CaseDetailResponse:
    investigation = _load_case(db, case_id, lock=True)
    _check_version(investigation, request.expected_version)
    if investigation.status is CaseStatus.RESOLVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reopen the case before linking alerts",
        )
    alerts = _locked_alerts_for_link(db, request.alert_ids)
    now = datetime.now(UTC)
    previous_version = investigation.version
    for alert in alerts:
        db.add(
            CaseAlert(
                case_id=case_id,
                alert_id=alert.id,
                linked_by_user_id=principal.user_id,
                linked_at=now,
            )
        )
        alert.status = AlertStatus.IN_REVIEW
        alert.version += 1
    investigation.updated_at = now
    investigation.version += 1
    append_audit_event(
        db,
        action="case.alerts_linked",
        target_type="case",
        target_id=case_id,
        actor_user_id=principal.user_id,
        before_state={"version": previous_version},
        after_state={"version": investigation.version},
        metadata={
            "schema_version": "audit-v1",
            "alert_ids": [str(alert.id) for alert in alerts],
            "transaction_ids": [
                str(alert.transaction_id) for alert in alerts if alert.transaction_id is not None
            ],
        },
    )
    _commit(db, "Case or alert link conflicted with another request")
    return _detail(db, investigation)


@router.post("/{case_id}/transitions", response_model=CaseDetailResponse)
def transition_case(
    case_id: UUID,
    request: TransitionRequest,
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.CASES_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    request_id: Annotated[UUID | None, Header(alias="X-Request-ID")] = None,
) -> CaseDetailResponse:
    investigation = _load_case(db, case_id, lock=True)
    _check_version(investigation, request.expected_version)
    linked_alerts = _linked_alerts(db, case_id, lock=True)
    try:
        history = apply_transition(
            investigation,
            request,
            linked_alerts,
            principal.user_id,
            request_id or uuid4(),
            datetime.now(UTC),
        )
    except ValueError as error:
        append_audit_event(
            db,
            action="case.transitioned",
            target_type="case",
            target_id=case_id,
            actor_user_id=principal.user_id,
            result=AuditResult.DENIED,
            correlation_id=request_id,
            before_state={"status": investigation.status.value, "version": investigation.version},
            metadata={
                "schema_version": "audit-v1",
                "requested_status": request.to_status.value,
                "reason_code": "INVALID_TRANSITION",
            },
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    db.add(history)
    append_audit_event(
        db,
        action="case.transitioned",
        target_type="case",
        target_id=case_id,
        actor_user_id=principal.user_id,
        correlation_id=history.correlation_id,
        before_state={
            "status": history.from_status.value if history.from_status else None,
            "version": investigation.version - 1,
        },
        after_state={
            "status": investigation.status.value,
            "version": investigation.version,
            "resolution_code": investigation.resolution_code,
        },
        metadata={
            "schema_version": "audit-v1",
            "alert_ids": [str(alert.id) for alert in linked_alerts],
        },
    )
    _commit(db, "Concurrent case transition conflict; refresh and retry")
    return _detail(db, investigation)
