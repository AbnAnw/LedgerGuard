from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ledgerguard.auth import AuthPrincipal, get_current_principal
from ledgerguard.cases import (
    ResolutionCode,
    TransitionRequest,
    _check_version,
    apply_transition,
    validate_resolution,
    validate_transition,
)
from ledgerguard.db import get_db
from ledgerguard.main import app
from ledgerguard.models import Alert, AlertStatus, CasePriority, CaseStatus, InvestigationCase


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def principal(role: str) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email=f"{role}@ledgerguard.invalid",
        display_name=f"Synthetic {role}",
        roles=(role,),
    )


def investigation(case_status: CaseStatus = CaseStatus.OPEN) -> InvestigationCase:
    return InvestigationCase(
        id=uuid4(),
        case_number=42,
        title="Synthetic investigation",
        status=case_status,
        priority=CasePriority.HIGH,
        created_by_user_id=uuid4(),
        version=1,
    )


def alert() -> Alert:
    return Alert(id=uuid4(), status=AlertStatus.OPEN, version=1)


def request(
    target: CaseStatus,
    *,
    code: ResolutionCode | None = None,
    summary: str | None = None,
) -> TransitionRequest:
    return TransitionRequest(
        expected_version=1,
        to_status=target,
        reason=f"Move to {target.value}",
        resolution_code=code,
        resolution_summary=summary,
    )


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (CaseStatus.OPEN, CaseStatus.IN_REVIEW),
        (CaseStatus.OPEN, CaseStatus.ESCALATED),
        (CaseStatus.IN_REVIEW, CaseStatus.ESCALATED),
        (CaseStatus.IN_REVIEW, CaseStatus.RESOLVED),
        (CaseStatus.ESCALATED, CaseStatus.IN_REVIEW),
        (CaseStatus.ESCALATED, CaseStatus.RESOLVED),
        (CaseStatus.RESOLVED, CaseStatus.REOPENED),
        (CaseStatus.REOPENED, CaseStatus.IN_REVIEW),
        (CaseStatus.REOPENED, CaseStatus.ESCALATED),
        (CaseStatus.REOPENED, CaseStatus.RESOLVED),
    ],
)
def test_documented_case_transitions_are_allowed(current: CaseStatus, target: CaseStatus) -> None:
    validate_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (CaseStatus.OPEN, CaseStatus.OPEN),
        (CaseStatus.OPEN, CaseStatus.RESOLVED),
        (CaseStatus.IN_REVIEW, CaseStatus.OPEN),
        (CaseStatus.ESCALATED, CaseStatus.OPEN),
        (CaseStatus.RESOLVED, CaseStatus.IN_REVIEW),
        (CaseStatus.REOPENED, CaseStatus.OPEN),
    ],
)
def test_invalid_or_same_state_transitions_are_rejected(
    current: CaseStatus, target: CaseStatus
) -> None:
    with pytest.raises(ValueError, match="not allowed"):
        validate_transition(current, target)


def test_stale_case_version_is_rejected_before_mutation() -> None:
    case = investigation(CaseStatus.IN_REVIEW)
    case.version = 3

    with pytest.raises(HTTPException) as error:
        _check_version(case, 2)

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "CASE_VERSION_CONFLICT"
    assert case.status is CaseStatus.IN_REVIEW
    assert case.version == 3


def test_resolution_requires_code_and_summary_and_rejects_them_elsewhere() -> None:
    with pytest.raises(ValueError, match="required"):
        validate_resolution(request(CaseStatus.RESOLVED))
    with pytest.raises(ValueError, match="only when resolving"):
        validate_resolution(
            request(
                CaseStatus.IN_REVIEW,
                code=ResolutionCode.NO_ACTION,
                summary="Not a resolution transition",
            )
        )


def test_resolution_and_reopen_update_alerts_and_preserve_history() -> None:
    case = investigation(CaseStatus.IN_REVIEW)
    linked_alert = alert()
    actor_id = uuid4()
    correlation_id = uuid4()
    resolved_at = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)

    history = apply_transition(
        case,
        request(
            CaseStatus.RESOLVED,
            code=ResolutionCode.CONFIRMED_ISSUE,
            summary="Stored rule evidence confirms investigation outcome.",
        ),
        [linked_alert],
        actor_id,
        correlation_id,
        resolved_at,
    )

    assert (history.from_status, history.to_status) == (
        CaseStatus.IN_REVIEW,
        CaseStatus.RESOLVED,
    )
    assert history.changed_by_user_id == actor_id
    assert history.correlation_id == correlation_id
    assert case.resolution_code == "confirmed_issue"
    assert case.resolved_at == resolved_at
    assert linked_alert.status is AlertStatus.CLOSED
    assert linked_alert.closed_by_user_id == actor_id
    assert case.version == 2

    reopened = apply_transition(
        case,
        TransitionRequest(
            expected_version=2,
            to_status=CaseStatus.REOPENED,
            reason="New evidence requires another review",
        ),
        [linked_alert],
        actor_id,
        uuid4(),
        datetime(2026, 10, 16, 3, 0, tzinfo=UTC),
    )

    assert reopened.from_status is CaseStatus.RESOLVED
    assert case.status is CaseStatus.REOPENED
    assert case.resolution_code is None
    assert case.resolved_at is None
    assert linked_alert.status is AlertStatus.IN_REVIEW
    assert linked_alert.closed_by_user_id is None
    assert linked_alert.closed_at is None


def test_non_confirmed_resolution_dismisses_linked_alert() -> None:
    case = investigation(CaseStatus.ESCALATED)
    linked_alert = alert()
    apply_transition(
        case,
        request(
            CaseStatus.RESOLVED,
            code=ResolutionCode.FALSE_POSITIVE,
            summary="The evidence was reviewed and found benign.",
        ),
        [linked_alert],
        uuid4(),
        uuid4(),
        datetime.now(UTC),
    )
    assert linked_alert.status is AlertStatus.DISMISSED


def test_auditor_can_read_cases_but_cannot_create_or_change_them(client: TestClient) -> None:
    auditor = principal("auditor")
    app.dependency_overrides[get_current_principal] = lambda: auditor
    database = MagicMock(spec=Session)
    database.scalar.return_value = None
    app.dependency_overrides[get_db] = lambda: database

    read = client.get(f"/api/v1/cases/{uuid4()}")
    create = client.post(
        "/api/v1/cases",
        json={
            "title": "Forbidden auditor change",
            "priority": "high",
            "alert_ids": [str(uuid4())],
        },
    )
    comment = client.post(
        f"/api/v1/cases/{uuid4()}/comments",
        json={"expected_version": 1, "body": "Forbidden"},
    )

    assert read.status_code == 404
    assert create.status_code == 403
    assert comment.status_code == 403


def test_unknown_role_is_denied_case_reads(client: TestClient) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal("unknown")
    assert client.get(f"/api/v1/cases/{UUID(int=1)}").status_code == 403
