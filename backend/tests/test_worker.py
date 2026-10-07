from ledgerguard.worker import ping


def test_worker_ping_is_side_effect_free_and_uses_utc() -> None:
    result = ping.run()

    assert result["status"] == "ok"
    assert result["service"] == "ledgerguard-worker"
    assert result["version"] == "0.1.0"
    assert result["checked_at"].endswith("+00:00")
