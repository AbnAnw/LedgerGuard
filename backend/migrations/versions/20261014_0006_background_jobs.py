"""Add durable background job state.

Revision ID: 20261014_0006
Revises: 20261014_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0006"
down_revision: str | None = "20261014_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("kind", sa.String(length=23), nullable=False),
        sa.Column("status", sa.String(length=9), nullable=False),
        sa.Column("deduplication_key", sa.String(length=64), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("celery_task_id", sa.String(length=80), nullable=False),
        sa.Column("progress_current", sa.Integer(), server_default="0", nullable=False),
        sa.Column("progress_total", sa.Integer(), server_default="1", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("status_message", sa.String(length=200), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_detail", sa.String(length=500), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingestion_batch_id", sa.Uuid(), nullable=True),
        sa.Column("reconciliation_run_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "kind IN ('transaction_ingestion', 'reconciliation')",
            name="background_job_kind",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="background_job_status",
        ),
        sa.CheckConstraint(
            "deduplication_key ~ '^[0-9a-f]{64}$'", name="ck_jobs_deduplication_key"
        ),
        sa.CheckConstraint("request_sha256 ~ '^[0-9a-f]{64}$'", name="ck_jobs_request_hash"),
        sa.CheckConstraint(
            "progress_total >= 1 AND progress_current >= 0 "
            "AND progress_current <= progress_total",
            name="ck_jobs_progress",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 10",
            name="ck_jobs_attempts",
        ),
        sa.CheckConstraint(
            "NOT (ingestion_batch_id IS NOT NULL AND reconciliation_run_id IS NOT NULL)",
            name="ck_jobs_single_result",
        ),
        sa.CheckConstraint(
            "status NOT IN ('succeeded', 'failed', 'cancelled') OR finished_at IS NOT NULL",
            name="ck_jobs_terminal_finished",
        ),
        sa.CheckConstraint("version > 0", name="ck_jobs_version_positive"),
        sa.ForeignKeyConstraint(
            ["ingestion_batch_id"], ["ingestion_batches.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["reconciliation_run_id"], ["reconciliation_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("celery_task_id"),
        sa.UniqueConstraint("deduplication_key"),
    )
    op.create_index("ix_jobs_status_created", "background_jobs", ["status", "created_at"])
    op.create_index(
        "ix_jobs_requester_created",
        "background_jobs",
        ["requested_by_user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_requester_created", table_name="background_jobs")
    op.drop_index("ix_jobs_status_created", table_name="background_jobs")
    op.drop_table("background_jobs")
