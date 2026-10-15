"""Reinforce immutable fraud configuration and alert evidence.

Revision ID: 20261016_0007
Revises: 20261014_0006
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261016_0007"
down_revision: str | None = "20261014_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_rule_versions_lifecycle",
        "fraud_rule_versions",
        "(status = 'draft' AND activated_by_user_id IS NULL AND activated_at IS NULL "
        "AND retired_at IS NULL) OR "
        "(status = 'active' AND activated_by_user_id IS NOT NULL AND activated_at IS NOT NULL "
        "AND retired_at IS NULL) OR "
        "(status = 'retired' AND activated_by_user_id IS NOT NULL AND activated_at IS NOT NULL "
        "AND retired_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_rule_versions_parameters_object",
        "fraud_rule_versions",
        "jsonb_typeof(parameters) = 'object'",
    )
    op.create_check_constraint(
        "ck_alerts_evidence_object",
        "alerts",
        "jsonb_typeof(evidence) = 'object'",
    )
    op.create_index(
        "ix_alerts_transaction_created",
        "alerts",
        ["transaction_id", "created_at"],
        postgresql_where="transaction_id IS NOT NULL",
    )
    op.execute(
        """
        CREATE FUNCTION prevent_rule_version_configuration_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status IN ('active', 'retired') AND
               (NEW.rule_id, NEW.version_number, NEW.rule_type, NEW.parameters, NEW.severity,
                NEW.created_by_user_id) IS DISTINCT FROM
               (OLD.rule_id, OLD.version_number, OLD.rule_type, OLD.parameters, OLD.severity,
                OLD.created_by_user_id) THEN
                RAISE EXCEPTION 'active or retired fraud rule configuration is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_fraud_rule_version_configuration_immutable
        BEFORE UPDATE ON fraud_rule_versions
        FOR EACH ROW EXECUTE FUNCTION prevent_rule_version_configuration_update()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_fraud_rule_version_configuration_immutable "
        "ON fraud_rule_versions"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_rule_version_configuration_update()")
    op.drop_index("ix_alerts_transaction_created", table_name="alerts")
    op.drop_constraint("ck_alerts_evidence_object", "alerts", type_="check")
    op.drop_constraint("ck_rule_versions_parameters_object", "fraud_rule_versions", type_="check")
    op.drop_constraint("ck_rule_versions_lifecycle", "fraud_rule_versions", type_="check")
