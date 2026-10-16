from collections.abc import Iterator
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ledgerguard.audit_service import append_audit_event
from ledgerguard.auth import AuthPrincipal, get_current_principal
from ledgerguard.db import get_db
from ledgerguard.main import app
from ledgerguard.models import AuditEvent, AuditResult


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


def test_audit_writer_stages_allowlisted_bounded_evidence() -> None:
    db = MagicMock(spec=Session)
    actor_id = uuid4()
    target_id = uuid4()
    event = append_audit_event(
        db,
        action="case.transitioned",
        target_type="case",
        target_id=target_id,
        actor_user_id=actor_id,
        result=AuditResult.SUCCESS,
        before_state={"status": "in_review", "version": 2},
        after_state={"status": "resolved", "version": 3},
        metadata={"schema_version": "audit-v1", "reason_code": "CONFIRMED"},
    )

    assert isinstance(event, AuditEvent)
    assert event.actor_user_id == actor_id
    assert event.target_id == target_id
    assert event.correlation_id is not None
    db.add.assert_called_once_with(event)


@pytest.mark.parametrize("forbidden", ["password", "token", "authorization", "payload"])
def test_audit_writer_rejects_secret_or_unrestricted_keys(forbidden: str) -> None:
    db = MagicMock(spec=Session)
    with pytest.raises(ValueError, match="forbidden key"):
        append_audit_event(
            db,
            action="auth.login",
            target_type="auth_session",
            actor_user_id=None,
            metadata={"schema_version": "audit-v1", forbidden: "must-not-persist"},
        )
    db.add.assert_not_called()


def test_audit_writer_rejects_oversized_metadata() -> None:
    with pytest.raises(ValueError, match="size limit"):
        append_audit_event(
            MagicMock(spec=Session),
            action="case.read",
            target_type="case",
            actor_user_id=uuid4(),
            metadata={"schema_version": "audit-v1", "value": "x" * 9_000},
        )


def test_auditor_can_read_append_only_history(client: TestClient) -> None:
    db = MagicMock(spec=Session)
    db.scalars.return_value.all.return_value = []
    db.execute.return_value.all.return_value = []
    app.dependency_overrides[get_current_principal] = lambda: principal("auditor")
    app.dependency_overrides[get_db] = lambda: db

    response = client.get("/api/v1/audit/events?limit=25")

    assert response.status_code == 200
    assert response.json() == []
    staged = db.add.call_args.args[0]
    assert isinstance(staged, AuditEvent)
    assert staged.action == "audit.history.read"
    db.commit.assert_called_once()
    assert client.patch("/api/v1/audit/events", json={}).status_code == 405
    assert client.delete("/api/v1/audit/events").status_code == 405


def test_analyst_cannot_read_audit_history_and_denial_is_recorded(client: TestClient) -> None:
    db = MagicMock(spec=Session)
    app.dependency_overrides[get_current_principal] = lambda: principal("operations_analyst")
    app.dependency_overrides[get_db] = lambda: db

    response = client.get("/api/v1/audit/events")

    assert response.status_code == 403
    event = db.add.call_args.args[0]
    assert isinstance(event, AuditEvent)
    assert event.action == "authz.permission_denied"
    assert event.result is AuditResult.DENIED
