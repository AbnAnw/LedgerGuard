"""Reinforce structured append-only audit evidence.

Revision ID: 20261016_0009
Revises: 20261016_0008
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261016_0009"
down_revision: str | None = "20261016_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLAlchemy's default JSONB serializer stored Python ``None`` as the JSON
    # literal ``null`` in earlier releases.  Normalise those legacy values to
    # SQL NULL before enforcing the object-only evidence contract.  The
    # append-only trigger is suspended only inside this transactional migration
    # and restored immediately after the one-time normalisation.
    op.execute("DROP TRIGGER audit_events_append_only ON audit_events")
    op.execute(
        "UPDATE audit_events SET before_state = NULL " "WHERE jsonb_typeof(before_state) = 'null'"
    )
    op.execute(
        "UPDATE audit_events SET after_state = NULL " "WHERE jsonb_typeof(after_state) = 'null'"
    )
    op.execute(
        "CREATE TRIGGER audit_events_append_only "
        "BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()"
    )
    op.create_check_constraint(
        "ck_audit_actor_user_pair",
        "audit_events",
        "(actor_type = 'user') = (actor_user_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_audit_action_format",
        "audit_events",
        "action ~ '^[a-z][a-z0-9_.]{2,99}$'",
    )
    op.create_check_constraint(
        "ck_audit_target_type_format",
        "audit_events",
        "target_type ~ '^[a-z][a-z0-9_]{1,79}$'",
    )
    op.create_check_constraint(
        "ck_audit_before_state_object",
        "audit_events",
        "before_state IS NULL OR jsonb_typeof(before_state) = 'object'",
    )
    op.create_check_constraint(
        "ck_audit_after_state_object",
        "audit_events",
        "after_state IS NULL OR jsonb_typeof(after_state) = 'object'",
    )
    op.create_check_constraint(
        "ck_audit_metadata_object",
        "audit_events",
        "jsonb_typeof(metadata) = 'object' AND metadata <> '{}'::jsonb",
    )
    op.create_index("ix_audit_result_occurred", "audit_events", ["result", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_result_occurred", table_name="audit_events")
    op.drop_constraint("ck_audit_metadata_object", "audit_events", type_="check")
    op.drop_constraint("ck_audit_after_state_object", "audit_events", type_="check")
    op.drop_constraint("ck_audit_before_state_object", "audit_events", type_="check")
    op.drop_constraint("ck_audit_target_type_format", "audit_events", type_="check")
    op.drop_constraint("ck_audit_action_format", "audit_events", type_="check")
    op.drop_constraint("ck_audit_actor_user_pair", "audit_events", type_="check")
