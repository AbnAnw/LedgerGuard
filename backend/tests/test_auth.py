from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ledgerguard.auth import (
    ROLE_PERMISSIONS,
    AuthPrincipal,
    Permission,
    authenticate_and_issue_session,
    digest_token,
    get_current_principal,
    hash_password,
    session_is_active,
    verify_password,
)
from ledgerguard.config import Settings, get_settings
from ledgerguard.db import get_db
from ledgerguard.main import app
from ledgerguard.models import AuditEvent, AuthSession, User, UserStatus


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_user(
    *, status: UserStatus = UserStatus.ACTIVE, password: str = "ValidPassphrase!42"
) -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid4(),
        email="person@ledgerguard.invalid",
        display_name="Synthetic Person",
        password_hash=hash_password(password),
        status=status,
        failed_login_count=0,
        created_at=now,
        updated_at=now,
        version=1,
    )


def make_principal(role: str) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email=f"{role}@ledgerguard.invalid",
        display_name=f"Synthetic {role}",
        roles=(role,),
    )


def test_passwords_use_argon2id_and_reject_wrong_values() -> None:
    encoded = hash_password("Correct horse battery staple!42")

    assert encoded.startswith("$argon2id$")
    assert verify_password("Correct horse battery staple!42", encoded)
    assert not verify_password("wrong", encoded)
    assert not verify_password("anything", "malformed-hash")


def test_token_digest_is_keyed_and_deterministic() -> None:
    assert digest_token("token", "secret-a") == digest_token("token", "secret-a")
    assert digest_token("token", "secret-a") != digest_token("token", "secret-b")
    assert digest_token("token", "secret-a") != digest_token("other", "secret-a")


def test_disabled_user_cannot_authenticate() -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = make_user(status=UserStatus.DISABLED)

    with pytest.raises(HTTPException) as error:
        authenticate_and_issue_session(
            db,
            "person@ledgerguard.invalid",
            "ValidPassphrase!42",
            Settings(_env_file=None),
        )

    assert error.value.status_code == 401
    assert error.value.detail == "Invalid email or password"
    event = db.add.call_args.args[0]
    assert isinstance(event, AuditEvent)
    assert event.action == "auth.login"
    assert event.result.value == "denied"
    db.commit.assert_called_once()


def test_failed_password_is_generic_and_counts_toward_lockout() -> None:
    user = make_user()
    db = MagicMock(spec=Session)
    db.scalar.return_value = user

    with pytest.raises(HTTPException, match="Invalid email or password"):
        authenticate_and_issue_session(
            db,
            user.email,
            "incorrect-password",
            Settings(login_max_failures=3, _env_file=None),
        )

    assert user.failed_login_count == 1
    db.commit.assert_called_once()


def test_repeated_failures_lock_the_user_for_the_configured_period() -> None:
    now = datetime.now(UTC)
    user = make_user()
    user.failed_login_count = 2
    db = MagicMock(spec=Session)
    db.scalar.return_value = user

    with pytest.raises(HTTPException, match="Invalid email or password"):
        authenticate_and_issue_session(
            db,
            user.email,
            "incorrect-password",
            Settings(login_max_failures=3, login_lock_minutes=20, _env_file=None),
            now=now,
        )

    assert user.status == UserStatus.LOCKED
    assert user.locked_until == now + timedelta(minutes=20)


def test_expired_revoked_and_disabled_sessions_fail_closed() -> None:
    now = datetime.now(UTC)
    user = make_user()
    auth_session = AuthSession(
        id=uuid4(),
        user_id=user.id,
        token_digest="a" * 64,
        created_at=now - timedelta(minutes=10),
        expires_at=now + timedelta(minutes=10),
    )

    assert session_is_active(auth_session, user, now)
    auth_session.expires_at = now
    assert not session_is_active(auth_session, user, now)
    auth_session.expires_at = now + timedelta(minutes=10)
    auth_session.revoked_at = now
    assert not session_is_active(auth_session, user, now)
    auth_session.revoked_at = None
    user.status = UserStatus.DISABLED
    assert not session_is_active(auth_session, user, now)


def test_role_permissions_are_least_privilege() -> None:
    assert Permission.USERS_MANAGE in ROLE_PERMISSIONS["administrator"]
    assert Permission.INGESTION_WRITE in ROLE_PERMISSIONS["operations_analyst"]
    assert Permission.USERS_MANAGE not in ROLE_PERMISSIONS["operations_analyst"]
    assert Permission.AUDIT_READ in ROLE_PERMISSIONS["auditor"]
    assert Permission.INGESTION_WRITE not in ROLE_PERMISSIONS["auditor"]


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("administrator", frozenset(Permission)),
        (
            "operations_analyst",
            frozenset(
                {
                    Permission.INGESTION_WRITE,
                    Permission.TRANSACTIONS_READ,
                    Permission.RECONCILIATION_READ,
                    Permission.RECONCILIATION_WRITE,
                    Permission.ALERTS_READ,
                    Permission.ALERTS_WRITE,
                    Permission.CASES_READ,
                    Permission.CASES_WRITE,
                    Permission.REPORTS_READ,
                }
            ),
        ),
        (
            "auditor",
            frozenset(
                {
                    Permission.TRANSACTIONS_READ,
                    Permission.RECONCILIATION_READ,
                    Permission.ALERTS_READ,
                    Permission.CASES_READ,
                    Permission.REPORTS_READ,
                    Permission.AUDIT_READ,
                }
            ),
        ),
        ("unknown_role", frozenset()),
    ],
)
def test_complete_permission_matrix_is_deny_by_default(
    role: str, expected: frozenset[Permission]
) -> None:
    assert make_principal(role).permissions == expected


@pytest.mark.parametrize(
    ("role", "admin_status", "operations_status", "audit_status"),
    [
        ("administrator", 200, 200, 200),
        ("operations_analyst", 403, 200, 403),
        ("auditor", 403, 403, 200),
        ("unknown_role", 403, 403, 403),
    ],
)
def test_api_enforces_role_boundaries(
    client: TestClient,
    role: str,
    admin_status: int,
    operations_status: int,
    audit_status: int,
) -> None:
    app.dependency_overrides[get_current_principal] = lambda: make_principal(role)
    app.dependency_overrides[get_db] = lambda: MagicMock(spec=Session)

    assert client.get("/api/v1/access/administration").status_code == admin_status
    assert client.get("/api/v1/access/operations").status_code == operations_status
    assert client.get("/api/v1/access/audit").status_code == audit_status


def test_protected_endpoint_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_successful_login_returns_session_and_user(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    principal = make_principal("auditor")
    expires_at = datetime.now(UTC) + timedelta(minutes=30)

    def issue_session(
        _db: Session,
        email: str,
        password: str,
        _settings: Settings,
    ) -> tuple[str, datetime, AuthPrincipal]:
        assert email == "auditor@ledgerguard.invalid"
        assert password == "ValidPassphrase!42"
        return "opaque-test-token", expires_at, principal

    monkeypatch.setattr("ledgerguard.auth.authenticate_and_issue_session", issue_session)
    app.dependency_overrides[get_db] = lambda: MagicMock(spec=Session)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "AUDITOR@ledgerguard.invalid", "password": "ValidPassphrase!42"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "opaque-test-token"
    assert response.json()["user"]["roles"] == ["auditor"]
    assert "audit:read" in response.json()["user"]["permissions"]
    assert "ingestion:write" not in response.json()["user"]["permissions"]


def test_logout_revokes_current_session(client: TestClient) -> None:
    principal = make_principal("administrator")
    auth_session = AuthSession(
        id=principal.session_id,
        user_id=principal.user_id,
        token_digest="b" * 64,
        created_at=datetime.now(UTC) - timedelta(minutes=1),
        expires_at=datetime.now(UTC) + timedelta(minutes=29),
    )
    db = MagicMock(spec=Session)
    db.get.return_value = auth_session
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db] = lambda: db

    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert auth_session.revoked_at is not None
    db.commit.assert_called_once()
