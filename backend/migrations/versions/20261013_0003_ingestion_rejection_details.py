"""Persist structured ingestion rejection details.

Revision ID: 20261013_0003
Revises: 20261009_0002
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_0003"
down_revision: str | None = "20261009_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingestion_records",
        sa.Column(
            "rejection_details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.alter_column("ingestion_records", "rejection_details", server_default=None)


def downgrade() -> None:
    op.drop_column("ingestion_records", "rejection_details")
