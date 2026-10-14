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
    assert revision == "20261014_0006"


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
