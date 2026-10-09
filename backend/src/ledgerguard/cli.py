"""Administrative command-line entry points."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ledgerguard.auth import hash_password
from ledgerguard.config import get_settings
from ledgerguard.db import SessionLocal
from ledgerguard.models import (
    Account,
    AccountStatus,
    AccountType,
    Role,
    User,
    UserRole,
    UserStatus,
)

DEMONSTRATION_USERS = (
    ("admin@ledgerguard.invalid", "Synthetic Administrator", "administrator"),
    ("analyst@ledgerguard.invalid", "Synthetic Operations Analyst", "operations_analyst"),
    ("auditor@ledgerguard.invalid", "Synthetic Auditor", "auditor"),
)


def seed() -> None:
    """Idempotently seed reference data and local-only synthetic users."""

    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("Synthetic demonstration users cannot be seeded in production")

    role_rows = [
        {"code": "administrator", "description": "Manages users, rules, and configuration"},
        {"code": "operations_analyst", "description": "Ingests and investigates data"},
        {"code": "auditor", "description": "Reads evidence and audit history"},
    ]

    with SessionLocal.begin() as session:
        session.execute(
            insert(Role).values(role_rows).on_conflict_do_nothing(index_elements=["code"])
        )

        account_statement = (
            insert(Account)
            .values(
                source_system="synthetic-demo",
                source_account_id="DEMO-ACCOUNT-001",
                display_name="Synthetic Demonstration Account",
                account_type=AccountType.MERCHANT,
                default_currency="USD",
                status=AccountStatus.ACTIVE,
            )
            .on_conflict_do_nothing(index_elements=["source_system", "source_account_id"])
        )
        session.execute(account_statement)

        password = settings.demo_user_password.get_secret_value()
        users: dict[str, User] = {}
        for email, display_name, _ in DEMONSTRATION_USERS:
            session.execute(
                insert(User)
                .values(
                    email=email,
                    display_name=display_name,
                    password_hash=hash_password(password),
                    status=UserStatus.ACTIVE,
                )
                .on_conflict_do_nothing(index_elements=["email"])
            )
            user = session.scalar(select(User).where(User.email == email))
            if user is None:
                raise RuntimeError(f"Unable to seed synthetic user {email}")
            users[email] = user

        administrator = users[DEMONSTRATION_USERS[0][0]]
        for email, _, role_code in DEMONSTRATION_USERS:
            user = users[email]
            existing_role = session.scalar(
                select(UserRole.id).where(
                    UserRole.user_id == user.id,
                    UserRole.role_code == role_code,
                    UserRole.revoked_at.is_(None),
                )
            )
            if existing_role is None:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role_code=role_code,
                        granted_by_user_id=administrator.id,
                    )
                )

    print("Seed complete: roles, synthetic account, and three demonstration users are present.")
