"""Opt-in Day 9 checks against the real local service topology."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import redis
from sqlalchemy import select, text

from ledgerguard.config import get_settings
from ledgerguard.db import SessionLocal, engine
from ledgerguard.jobs import mark_job_for_retry
from ledgerguard.models import BackgroundJob, BackgroundJobKind, BackgroundJobStatus, User
from ledgerguard.worker import celery_app, ping

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


def test_worker_executes_a_real_broker_round_trip() -> None:
    result = ping.apply_async()
    payload = result.get(timeout=15)

    assert payload["status"] == "ok"
    assert payload["service"] == "ledgerguard-worker"
    assert datetime.fromisoformat(payload["checked_at"]).tzinfo is not None


def test_retry_state_is_durable_and_payload_is_removed_at_limit() -> None:
    job_id = uuid4()
    with SessionLocal() as db:
        requester_id = db.scalar(select(User.id).where(User.email == "analyst@ledgerguard.invalid"))
        assert requester_id is not None
        db.add(
            BackgroundJob(
                id=job_id,
                kind=BackgroundJobKind.RECONCILIATION,
                status=BackgroundJobStatus.RUNNING,
                deduplication_key=uuid4().hex + uuid4().hex,
                request_sha256=uuid4().hex + uuid4().hex,
                payload={"synthetic": True},
                requested_by_user_id=requester_id,
                correlation_id=uuid4(),
                celery_task_id=f"day14-{uuid4()}",
                progress_current=1,
                progress_total=3,
                attempt_count=1,
                max_attempts=2,
                started_at=datetime.now(UTC),
                version=1,
            )
        )
        db.commit()

    try:
        assert mark_job_for_retry(job_id) is True
        with SessionLocal() as db:
            job = db.get(BackgroundJob, job_id)
            assert job is not None
            assert job.status is BackgroundJobStatus.QUEUED
            assert job.failure_code == "RETRYABLE_DEPENDENCY_ERROR"
            assert job.payload == {"synthetic": True}
            job.status = BackgroundJobStatus.RUNNING
            job.attempt_count = 2
            db.commit()

        assert mark_job_for_retry(job_id) is False
        with SessionLocal() as db:
            job = db.get(BackgroundJob, job_id)
            assert job is not None
            assert job.status is BackgroundJobStatus.FAILED
            assert job.failure_code == "RETRY_LIMIT_EXCEEDED"
            assert job.payload == {}
            assert job.finished_at is not None
    finally:
        with SessionLocal() as db:
            job = db.get(BackgroundJob, job_id)
            if job is not None:
                db.delete(job)
                db.commit()
