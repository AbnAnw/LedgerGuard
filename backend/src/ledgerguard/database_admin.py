"""One-shot database privilege provisioning for the migration identity."""

from __future__ import annotations

import os
import re

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

_ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def provision_runtime_role(
    admin_database_url: str,
    runtime_user: str,
    runtime_password: str,
) -> None:
    """Create/repair the non-owner runtime role and its least-privilege grants."""

    if not _ROLE_PATTERN.fullmatch(runtime_user):
        raise ValueError("DATABASE_RUNTIME_USER must be a simple lowercase PostgreSQL role name")
    if len(runtime_password) < 16:
        raise ValueError("DATABASE_RUNTIME_PASSWORD must contain at least 16 characters")

    url = make_url(admin_database_url)
    if url.get_backend_name() != "postgresql" or not url.database:
        raise ValueError("DATABASE_URL must identify a PostgreSQL database")

    role = sql.Identifier(runtime_user)
    database = sql.Identifier(url.database)
    with (
        psycopg.connect(
            dbname=url.database,
            host=url.host or "localhost",
            port=url.port or 5432,
            user=url.username or "",
            password=url.password or "",
            connect_timeout=5,
            autocommit=True,
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (runtime_user,))
        if cursor.fetchone() is None:
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOINHERIT NOREPLICATION PASSWORD {}"
                ).format(role, sql.Literal(runtime_password))
            )
        else:
            cursor.execute(
                sql.SQL(
                    "ALTER ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOINHERIT NOREPLICATION PASSWORD {}"
                ).format(role, sql.Literal(runtime_password))
            )

        cursor.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM {}").format(database, role))
        cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database, role))
        cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        cursor.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
            ).format(role)
        )
        cursor.execute(
            sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role)
        )
        cursor.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
            ).format(role)
        )
        cursor.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES TO {}"
            ).format(role)
        )
        cursor.execute(
            sql.SQL("REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_events FROM {}").format(role)
        )


def main() -> None:
    """Provision the runtime role using migration-only environment variables."""

    admin_database_url = os.environ.get("DATABASE_URL", "")
    runtime_user = os.environ.get("DATABASE_RUNTIME_USER", "ledgerguard_app")
    runtime_password = os.environ.get("DATABASE_RUNTIME_PASSWORD", "")
    provision_runtime_role(admin_database_url, runtime_user, runtime_password)


if __name__ == "__main__":
    main()
