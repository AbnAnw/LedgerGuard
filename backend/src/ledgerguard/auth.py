"""Authentication, revocable sessions, and deny-by-default authorization."""

from __future__ import annotations

import hmac
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, NoReturn
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ledgerguard.config import Settings, get_settings
from ledgerguard.db import get_db
from ledgerguard.models import AuthSession, User, UserRole, UserStatus

password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)
_dummy_password_hash = password_hasher.hash("LedgerGuard constant-time invalid-user check")
bearer_scheme = HTTPBearer(auto_error=False)


class Permission(StrEnum):
    USERS_MANAGE = "users:manage"
    RULES_MANAGE = "rules:manage"
    CONFIGURATION_MANAGE = "configuration:manage"
    INGESTION_WRITE = "ingestion:write"
    TRANSACTIONS_READ = "transactions:read"
    RECONCILIATION_READ = "reconciliation:read"
    RECONCILIATION_WRITE = "reconciliation:write"
    ALERTS_READ = "alerts:read"
    ALERTS_WRITE = "alerts:write"
    CASES_READ = "cases:read"
    CASES_WRITE = "cases:write"
    REPORTS_READ = "reports:read"
    AUDIT_READ = "audit:read"


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "administrator": frozenset(Permission),
    "operations_analyst": frozenset(
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
    "auditor": frozenset(
        {
            Permission.TRANSACTIONS_READ,
            Permission.RECONCILIATION_READ,
            Permission.ALERTS_READ,
            Permission.CASES_READ,
            Permission.REPORTS_READ,
            Permission.AUDIT_READ,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    user_id: UUID
    session_id: UUID
    email: str
    display_name: str
    roles: tuple[str, ...]

    @property
    def permissions(self) -> frozenset[Permission]:
        granted: set[Permission] = set()
        for role in self.roles:
            granted.update(ROLE_PERMISSIONS.get(role, frozenset()))
        return frozenset(granted)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
            raise ValueError("email must be a valid address")
        return normalized


class UserResponse(BaseModel):
    id: UUID
    email: str
    display_name: str
    roles: list[str]
    permissions: list[str]


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserResponse


class AccessResponse(BaseModel):
    area: str
    mode: str


def hash_password(password: str) -> str:
    """Hash a password with the Argon2id profile used by LedgerGuard."""

    return password_hasher.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a password without leaking malformed-hash errors."""

    try:
        return password_hasher.verify(encoded_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def digest_token(token: str, secret_key: str) -> str:
    """Create the keyed digest persisted instead of the bearer credential."""

    return hmac.digest(secret_key.encode(), token.encode(), "sha256").hex()


def _reject_authentication(detail: str = "Invalid email or password") -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _roles_for_user(db: Session, user_id: UUID) -> tuple[str, ...]:
    roles = db.scalars(
        select(UserRole.role_code)
        .where(UserRole.user_id == user_id, UserRole.revoked_at.is_(None))
        .order_by(UserRole.role_code)
    ).all()
    return tuple(roles)


def _response_user(principal: AuthPrincipal) -> UserResponse:
    return UserResponse(
        id=principal.user_id,
        email=principal.email,
        display_name=principal.display_name,
        roles=list(principal.roles),
        permissions=sorted(permission.value for permission in principal.permissions),
    )


def authenticate_and_issue_session(
    db: Session,
    email: str,
    password: str,
    settings: Settings,
    now: datetime | None = None,
) -> tuple[str, datetime, AuthPrincipal]:
    """Validate credentials and create one revocable server-side session."""

    checked_at = now or datetime.now(UTC)
    user = db.scalar(select(User).where(User.email == email.strip().lower()))

    if user is None:
        verify_password(password, _dummy_password_hash)
        _reject_authentication()

    if user.status == UserStatus.LOCKED and user.locked_until is not None:
        if user.locked_until <= checked_at:
            user.status = UserStatus.ACTIVE
            user.failed_login_count = 0
            user.locked_until = None
        else:
            _reject_authentication()

    if user.status != UserStatus.ACTIVE:
        _reject_authentication()

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_max_failures:
            user.status = UserStatus.LOCKED
            user.locked_until = checked_at + timedelta(minutes=settings.login_lock_minutes)
        user.updated_at = checked_at
        db.commit()
        _reject_authentication()

    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = checked_at
    user.updated_at = checked_at

    raw_token = secrets.token_urlsafe(32)
    expires_at = checked_at + timedelta(minutes=settings.access_token_expire_minutes)
    auth_session = AuthSession(
        user_id=user.id,
        token_digest=digest_token(raw_token, settings.auth_secret_key.get_secret_value()),
        expires_at=expires_at,
    )
    db.add(auth_session)
    db.flush()
    roles = _roles_for_user(db, user.id)
    db.commit()

    principal = AuthPrincipal(
        user_id=user.id,
        session_id=auth_session.id,
        email=user.email,
        display_name=user.display_name,
        roles=roles,
    )
    return raw_token, expires_at, principal


def session_is_active(auth_session: AuthSession, user: User, now: datetime) -> bool:
    """Apply expiry, revocation, and user-status checks consistently."""

    return (
        auth_session.revoked_at is None
        and auth_session.expires_at > now
        and user.status == UserStatus.ACTIVE
    )


def load_principal(
    db: Session,
    token: str,
    settings: Settings,
    now: datetime | None = None,
) -> AuthPrincipal:
    """Resolve a bearer credential to an active principal."""

    checked_at = now or datetime.now(UTC)
    token_digest = digest_token(token, settings.auth_secret_key.get_secret_value())
    auth_session = db.scalar(select(AuthSession).where(AuthSession.token_digest == token_digest))
    if auth_session is None:
        _reject_authentication("Invalid or expired session")

    user = db.get(User, auth_session.user_id)
    if user is None or not session_is_active(auth_session, user, checked_at):
        _reject_authentication("Invalid or expired session")

    return AuthPrincipal(
        user_id=user.id,
        session_id=auth_session.id,
        email=user.email,
        display_name=user.display_name,
        roles=_roles_for_user(db, user.id),
    )


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthPrincipal:
    """FastAPI dependency that authenticates a bearer session."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        _reject_authentication("Authentication required")
    return load_principal(db, credentials.credentials, settings)


def require_permissions(
    *required: Permission,
) -> Callable[[AuthPrincipal], AuthPrincipal]:
    """Build a deny-by-default dependency for an endpoint permission set."""

    def dependency(
        principal: Annotated[AuthPrincipal, Depends(get_current_principal)],
    ) -> AuthPrincipal:
        if not set(required).issubset(principal.permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return principal

    return dependency


auth_router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
access_router = APIRouter(prefix="/api/v1/access", tags=["authorization"])


@auth_router.post("/login", response_model=LoginResponse)
def login(
    request: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginResponse:
    token, expires_at, principal = authenticate_and_issue_session(
        db,
        request.email,
        request.password.get_secret_value(),
        settings,
    )
    return LoginResponse(
        access_token=token,
        expires_at=expires_at,
        user=_response_user(principal),
    )


@auth_router.get("/me", response_model=UserResponse)
def current_user(
    principal: Annotated[AuthPrincipal, Depends(get_current_principal)],
) -> UserResponse:
    return _response_user(principal)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    principal: Annotated[AuthPrincipal, Depends(get_current_principal)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    auth_session = db.get(AuthSession, principal.session_id)
    if auth_session is not None and auth_session.revoked_at is None:
        auth_session.revoked_at = datetime.now(UTC)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@access_router.get("/administration", response_model=AccessResponse)
def administration_access(
    _: Annotated[AuthPrincipal, Depends(require_permissions(Permission.USERS_MANAGE))],
) -> AccessResponse:
    return AccessResponse(area="administration", mode="manage")


@access_router.get("/operations", response_model=AccessResponse)
def operations_access(
    _: Annotated[AuthPrincipal, Depends(require_permissions(Permission.INGESTION_WRITE))],
) -> AccessResponse:
    return AccessResponse(area="operations", mode="manage")


@access_router.get("/audit", response_model=AccessResponse)
def audit_access(
    _: Annotated[AuthPrincipal, Depends(require_permissions(Permission.AUDIT_READ))],
) -> AccessResponse:
    return AccessResponse(area="audit", mode="read_only")
