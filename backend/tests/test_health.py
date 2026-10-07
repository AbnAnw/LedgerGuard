from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from ledgerguard.health import ReadinessState, probe_dependencies
from ledgerguard.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_liveness_returns_version_and_utc_timestamp(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "alive"
    assert payload["service"] == "LedgerGuard"
    assert payload["version"] == "0.1.0"
    assert payload["checked_at"].endswith(("Z", "+00:00"))


def test_readiness_succeeds_when_dependencies_are_up(client: TestClient) -> None:
    ready: ReadinessState = {
        "status": "ready",
        "dependencies": {"database": {"status": "up"}, "redis": {"status": "up"}},
    }
    app.dependency_overrides[probe_dependencies] = lambda: ready

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == ready


def test_readiness_fails_closed_without_leaking_driver_errors(client: TestClient) -> None:
    unavailable: ReadinessState = {
        "status": "not_ready",
        "dependencies": {"database": {"status": "down"}, "redis": {"status": "up"}},
    }
    app.dependency_overrides[probe_dependencies] = lambda: unavailable

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": unavailable}
    assert "password" not in response.text.lower()
