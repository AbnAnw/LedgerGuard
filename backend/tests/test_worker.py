from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

import ledgerguard.jobs as jobs
from ledgerguard.worker import celery_app, ping, process_background_job


def test_worker_ping_is_side_effect_free_and_uses_utc() -> None:
    result = ping.run()

    assert result["status"] == "ok"
    assert result["service"] == "ledgerguard-worker"
    assert result["version"] == "0.1.0"
    assert result["checked_at"].endswith("+00:00")


def test_worker_delivery_is_loss_safe_and_fair() -> None:
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.worker_redirect_stdouts is False


def test_background_task_has_bounded_retry_and_time_limits() -> None:
    assert process_background_job.max_retries == 2
    assert process_background_job.soft_time_limit == 300
    assert process_background_job.time_limit == 330


def test_context_load_failure_uses_same_bounded_retry_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_context_load(job_id: object) -> None:
        del job_id
        raise OperationalError("SELECT", {}, Exception("synthetic database outage"))

    monkeypatch.setattr(jobs, "get_job_observability_context", fail_context_load)
    monkeypatch.setattr(jobs, "mark_job_for_retry", lambda job_id: False)

    result = process_background_job.run(str(uuid4()))

    assert result["status"] == "failed"
    assert result["failure_code"] == "RETRY_LIMIT_EXCEEDED"
