"""Opt-in Day 9 checks against the real local service topology."""

import os

import pytest
import redis
from sqlalchemy import text

from ledgerguard.config import get_settings
from ledgerguard.db import engine
from ledgerguard.worker import celery_app

RUN_INTEGRATION = os.getenv("LEDGERGUARD_RUN_INTEGRATION") == "1"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not RUN_INTEGRATION,
        reason="set LEDGERGUARD_RUN_INTEGRATION=1 inside the Docker Compose stack",
    ),
]


def test_postgresql_has_durable_background_job_schema() -> None:
    with engine.connect() as connection:
        table_name = connection.scalar(text("SELECT to_regclass('public.background_jobs')"))
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))

    assert table_name == "background_jobs"
    assert revision == "20261016_0009"


def test_postgresql_has_case_workflow_invariants() -> None:
    with engine.connect() as connection:
        constraints = set(
            connection.scalars(
                text(
                    "SELECT conname FROM pg_constraint WHERE conname IN "
                    "('ck_cases_title_length', 'ck_cases_description_length', "
                    "'ck_cases_resolution_required', 'ck_cases_resolution_summary_length', "
                    "'ck_case_comments_body_length', 'ck_case_status_history_changed', "
                    "'ck_case_status_history_reason_length')"
                )
            )
        )

    assert constraints == {
        "ck_cases_title_length",
        "ck_cases_description_length",
        "ck_cases_resolution_required",
        "ck_cases_resolution_summary_length",
        "ck_case_comments_body_length",
        "ck_case_status_history_changed",
        "ck_case_status_history_reason_length",
    }


def test_postgresql_has_structured_append_only_audit_invariants() -> None:
    with engine.connect() as connection:
        constraints = set(
            connection.scalars(
                text(
                    "SELECT conname FROM pg_constraint WHERE conname IN "
                    "('ck_audit_actor_user_pair', 'ck_audit_action_format', "
                    "'ck_audit_target_type_format', 'ck_audit_before_state_object', "
                    "'ck_audit_after_state_object', 'ck_audit_metadata_object')"
                )
            )
        )
        trigger = connection.scalar(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgname = 'audit_events_append_only' "
                "AND NOT tgisinternal"
            )
        )

    assert constraints == {
        "ck_audit_actor_user_pair",
        "ck_audit_action_format",
        "ck_audit_target_type_format",
        "ck_audit_before_state_object",
        "ck_audit_after_state_object",
        "ck_audit_metadata_object",
    }
    assert trigger == "audit_events_append_only"


def test_postgresql_has_fraud_rule_and_evidence_invariants() -> None:
    with engine.connect() as connection:
        constraints = set(
            connection.scalars(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conname IN ('ck_rule_versions_lifecycle', "
                    "'ck_rule_versions_parameters_object', 'ck_alerts_evidence_object')"
                )
            )
        )
        trigger = connection.scalar(
            text(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgname = 'trg_fraud_rule_version_configuration_immutable' "
                "AND NOT tgisinternal"
            )
        )

    assert constraints == {
        "ck_rule_versions_lifecycle",
        "ck_rule_versions_parameters_object",
        "ck_alerts_evidence_object",
    }
    assert trigger == "trg_fraud_rule_version_configuration_immutable"


def test_redis_broker_is_reachable() -> None:
    client = redis.Redis.from_url(get_settings().redis_url)
    try:
        assert client.ping() is True
    finally:
        client.close()


def test_celery_worker_responds_to_health_probe() -> None:
    replies = celery_app.control.inspect(timeout=5).ping()

    assert replies
    assert all(reply == {"ok": "pong"} for reply in replies.values())
