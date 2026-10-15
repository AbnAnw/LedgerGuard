"""Enforce case workflow text and lifecycle invariants.

Revision ID: 20261016_0008
Revises: 20261016_0007
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261016_0008"
down_revision: str | None = "20261016_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_cases_title_length", "cases", "length(btrim(title)) BETWEEN 1 AND 200"
    )
    op.create_check_constraint(
        "ck_cases_description_length",
        "cases",
        "description IS NULL OR length(description) <= 4000",
    )
    op.drop_constraint("ck_cases_resolution_required", "cases", type_="check")
    op.create_check_constraint(
        "ck_cases_resolution_required",
        "cases",
        "(status = 'resolved' AND resolution_code IS NOT NULL "
        "AND resolution_summary IS NOT NULL AND resolved_at IS NOT NULL) OR "
        "(status <> 'resolved' AND resolution_code IS NULL "
        "AND resolution_summary IS NULL AND resolved_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_cases_resolution_summary_length",
        "cases",
        "resolution_summary IS NULL OR "
        "length(btrim(resolution_summary)) BETWEEN 1 AND 4000",
    )
    op.create_check_constraint(
        "ck_case_comments_body_length",
        "case_comments",
        "length(btrim(body)) BETWEEN 1 AND 4000",
    )
    op.create_check_constraint(
        "ck_case_status_history_changed",
        "case_status_history",
        "from_status IS NULL OR from_status <> to_status",
    )
    op.create_check_constraint(
        "ck_case_status_history_reason_length",
        "case_status_history",
        "reason IS NOT NULL AND length(btrim(reason)) BETWEEN 1 AND 2000",
    )
    op.create_index(
        "ix_case_alerts_case_linked", "case_alerts", ["case_id", "linked_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_case_alerts_case_linked", table_name="case_alerts")
    op.drop_constraint(
        "ck_case_status_history_reason_length", "case_status_history", type_="check"
    )
    op.drop_constraint(
        "ck_case_status_history_changed", "case_status_history", type_="check"
    )
    op.drop_constraint("ck_case_comments_body_length", "case_comments", type_="check")
    op.drop_constraint("ck_cases_resolution_summary_length", "cases", type_="check")
    op.drop_constraint("ck_cases_resolution_required", "cases", type_="check")
    op.create_check_constraint(
        "ck_cases_resolution_required",
        "cases",
        "(status <> 'resolved') OR "
        "(resolution_code IS NOT NULL AND resolution_summary IS NOT NULL "
        "AND resolved_at IS NOT NULL)",
    )
    op.drop_constraint("ck_cases_description_length", "cases", type_="check")
    op.drop_constraint("ck_cases_title_length", "cases", type_="check")
