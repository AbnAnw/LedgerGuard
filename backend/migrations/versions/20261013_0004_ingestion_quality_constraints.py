"""Reinforce ingestion idempotency and terminal quality totals.

Revision ID: 20261013_0004
Revises: 20261013_0003
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261013_0004"
down_revision: str | None = "20261013_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_batches_idempotency_key",
        "ingestion_batches",
        "length(btrim(idempotency_key)) BETWEEN 1 AND 200",
    )
    op.create_check_constraint(
        "ck_batches_terminal_totals",
        "ingestion_batches",
        "status NOT IN ('completed', 'completed_with_errors') OR "
        "source_count = accepted_count + rejected_count + duplicate_count + conflict_count",
    )


def downgrade() -> None:
    op.drop_constraint("ck_batches_terminal_totals", "ingestion_batches", type_="check")
    op.drop_constraint("ck_batches_idempotency_key", "ingestion_batches", type_="check")
