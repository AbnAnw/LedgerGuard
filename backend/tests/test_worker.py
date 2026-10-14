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


def test_background_task_has_bounded_retry_and_time_limits() -> None:
    assert process_background_job.max_retries == 2
    assert process_background_job.soft_time_limit == 300
    assert process_background_job.time_limit == 330
