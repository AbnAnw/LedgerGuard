from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from ledgerguard.models import Base, FinancialTransaction, IngestionBatch

EXPECTED_TABLES = {
    "accounts",
    "alerts",
    "auth_sessions",
    "audit_events",
    "case_alerts",
    "case_comments",
    "case_status_history",
    "cases",
    "fraud_rule_versions",
    "fraud_rules",
    "ingestion_batches",
    "ingestion_records",
    "reconciliation_result_settlements",
    "reconciliation_result_transactions",
    "reconciliation_results",
    "reconciliation_runs",
    "roles",
    "settlements",
    "transactions",
    "user_roles",
    "users",
}


def test_metadata_contains_complete_day_two_model() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_every_table_compiles_for_postgresql() -> None:
    dialect = postgresql.dialect()

    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert f"CREATE TABLE {table.name}" in ddl


def test_money_column_uses_fixed_precision() -> None:
    amount = FinancialTransaction.__table__.c.amount.type

    assert amount.precision == 20
    assert amount.scale == 6
    assert amount.asdecimal is True


def test_initial_migration_contains_audit_immutability_trigger() -> None:
    migration = (
        Path(__file__).parents[1] / "migrations" / "versions" / "20261007_0001_initial_schema.py"
    ).read_text(encoding="utf-8")

    assert "audit_events_append_only" in migration
    assert "BEFORE UPDATE OR DELETE ON audit_events" in migration
    assert "reject_audit_event_mutation" in migration


def test_ingestion_batch_has_database_idempotency_and_quality_guards() -> None:
    constraint_names = {constraint.name for constraint in IngestionBatch.__table__.constraints}

    assert "uq_ingestion_batches_idempotency" in constraint_names
    assert "ck_batches_idempotency_key" in constraint_names
    assert "ck_batches_terminal_totals" in constraint_names
