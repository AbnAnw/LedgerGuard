"""Reinforce deterministic reconciliation result invariants.

Revision ID: 20261014_0005
Revises: 20261013_0004
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261014_0005"
down_revision: str | None = "20261013_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_results_difference_exact",
        "reconciliation_results",
        "difference_amount = settlement_total - transaction_total",
    )
    op.create_unique_constraint(
        "uq_results_run_evidence",
        "reconciliation_results",
        ["run_id", "evidence_sha256"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_results_run_evidence", "reconciliation_results", type_="unique")
    op.drop_constraint("ck_results_difference_exact", "reconciliation_results", type_="check")
