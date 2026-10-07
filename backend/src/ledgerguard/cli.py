"""Administrative command-line entry points."""

from sqlalchemy.dialects.postgresql import insert

from ledgerguard.db import SessionLocal
from ledgerguard.models import Account, AccountStatus, AccountType, Role


def seed() -> None:
    """Idempotently seed reference roles and one clearly synthetic account."""

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

    print("Seed complete: roles and synthetic demonstration account are present.")
