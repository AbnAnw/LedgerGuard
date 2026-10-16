"""Read-only audit history and case decision reconstruction API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ledgerguard.audit_service import append_audit_event
from ledgerguard.auth import AuthPrincipal, Permission, require_permissions
from ledgerguard.db import get_db
from ledgerguard.models import (
    Alert,
    AuditEvent,
    AuditResult,
    CaseAlert,
    InvestigationCase,
    User,
)


class AuditEventResponse(BaseModel):
    sequence_number: int
    id: UUID
    occurred_at: datetime
    actor_user_id: UUID | None
    actor_display_name: str | None
    actor_type: str
    action: str
    target_type: str
    target_id: UUID | None
    result: str
    correlation_id: UUID
    request_id: UUID | None
    job_id: UUID | None
    before_state: dict[str, Any] | None
    after_state: dict[str, Any] | None
    metadata: dict[str, Any]


class CaseAuditTrailResponse(BaseModel):
    case_id: UUID
    alert_ids: list[UUID]
    transaction_ids: list[UUID]
    events: list[AuditEventResponse]


def _event_response(event: AuditEvent, actor_name: str | None) -> AuditEventResponse:
    return AuditEventResponse(
        sequence_number=event.sequence_number,
        id=event.id,
        occurred_at=event.occurred_at,
        actor_user_id=event.actor_user_id,
        actor_display_name=actor_name,
        actor_type=event.actor_type.value,
        action=event.action,
        target_type=event.target_type,
        target_id=event.target_id,
        result=event.result.value,
        correlation_id=event.correlation_id,
        request_id=event.request_id,
        job_id=event.job_id,
        before_state=event.before_state,
        after_state=event.after_state,
        metadata=event.event_metadata,
    )


def _responses(db: Session, events: list[AuditEvent]) -> list[AuditEventResponse]:
    actor_ids = {event.actor_user_id for event in events if event.actor_user_id is not None}
    names = {
        actor_id: name
        for actor_id, name in db.execute(
            select(User.id, User.display_name).where(User.id.in_(actor_ids))
        ).all()
    }
    return [_event_response(event, names.get(event.actor_user_id)) for event in events]


def _utc_filter(value: datetime | None, name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{name} must include a UTC offset",
        )
    return value.astimezone(UTC)


router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("/events", response_model=list[AuditEventResponse])
def list_audit_events(
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.AUDIT_READ))],
    db: Annotated[Session, Depends(get_db)],
    actor_user_id: UUID | None = None,
    action: Annotated[str | None, Query(min_length=3, max_length=100)] = None,
    target_type: Annotated[str | None, Query(min_length=2, max_length=80)] = None,
    target_id: UUID | None = None,
    result: AuditResult | None = None,
    correlation_id: UUID | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    before_sequence: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditEventResponse]:
    started_at = _utc_filter(occurred_from, "occurred_from")
    ended_at = _utc_filter(occurred_to, "occurred_to")
    if started_at is not None and ended_at is not None and started_at >= ended_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="occurred_from must be earlier than occurred_to",
        )
    append_audit_event(
        db,
        action="audit.history.read",
        target_type="audit_history",
        actor_user_id=principal.user_id,
        correlation_id=uuid4(),
        metadata={
            "schema_version": "audit-v1",
            "filters_applied": any(
                value is not None
                for value in (
                    actor_user_id,
                    action,
                    target_type,
                    target_id,
                    result,
                    correlation_id,
                    started_at,
                    ended_at,
                    before_sequence,
                )
            ),
            "limit": limit,
        },
    )
    db.commit()
    statement = select(AuditEvent)
    if actor_user_id is not None:
        statement = statement.where(AuditEvent.actor_user_id == actor_user_id)
    if action is not None:
        statement = statement.where(AuditEvent.action == action)
    if target_type is not None:
        statement = statement.where(AuditEvent.target_type == target_type)
    if target_id is not None:
        statement = statement.where(AuditEvent.target_id == target_id)
    if result is not None:
        statement = statement.where(AuditEvent.result == result)
    if correlation_id is not None:
        statement = statement.where(AuditEvent.correlation_id == correlation_id)
    if started_at is not None:
        statement = statement.where(AuditEvent.occurred_at >= started_at)
    if ended_at is not None:
        statement = statement.where(AuditEvent.occurred_at < ended_at)
    if before_sequence is not None:
        statement = statement.where(AuditEvent.sequence_number < before_sequence)
    events = list(
        db.scalars(statement.order_by(AuditEvent.sequence_number.desc()).limit(limit)).all()
    )
    return _responses(db, events)


@router.get("/cases/{case_id}/timeline", response_model=CaseAuditTrailResponse)
def read_case_audit_trail(
    case_id: UUID,
    principal: Annotated[AuthPrincipal, Depends(require_permissions(Permission.AUDIT_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> CaseAuditTrailResponse:
    if db.get(InvestigationCase, case_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    linked_rows = db.execute(
        select(CaseAlert.alert_id, Alert.transaction_id)
        .join(Alert, Alert.id == CaseAlert.alert_id)
        .where(CaseAlert.case_id == case_id)
    ).all()
    alert_ids = sorted((row.alert_id for row in linked_rows), key=str)
    transaction_ids = sorted(
        {row.transaction_id for row in linked_rows if row.transaction_id is not None}, key=str
    )
    append_audit_event(
        db,
        action="audit.case_timeline.read",
        target_type="case",
        target_id=case_id,
        actor_user_id=principal.user_id,
        metadata={"schema_version": "audit-v1"},
    )
    db.commit()
    predicates = [
        sa.and_(AuditEvent.target_type == "case", AuditEvent.target_id == case_id),
    ]
    if alert_ids:
        predicates.append(
            sa.and_(AuditEvent.target_type == "alert", AuditEvent.target_id.in_(alert_ids))
        )
    if transaction_ids:
        predicates.extend(
            sa.and_(
                AuditEvent.target_type == "transaction_batch",
                AuditEvent.event_metadata["transaction_ids"].contains([str(transaction_id)]),
            )
            for transaction_id in transaction_ids
        )
    events = list(
        db.scalars(
            select(AuditEvent).where(sa.or_(*predicates)).order_by(AuditEvent.sequence_number)
        ).all()
    )
    return CaseAuditTrailResponse(
        case_id=case_id,
        alert_ids=alert_ids,
        transaction_ids=transaction_ids,
        events=_responses(db, events),
    )
