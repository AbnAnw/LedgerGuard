from pathlib import Path

import yaml


def test_compose_declares_required_services_and_health_checks() -> None:
    compose_path = Path(__file__).parents[2] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = compose["services"]

    assert set(services) == {"postgres", "redis", "api", "worker", "frontend"}
    for service_name in ("postgres", "redis", "api", "worker"):
        assert "healthcheck" in services[service_name]

    assert services["api"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert services["worker"]["depends_on"]["api"]["condition"] == "service_healthy"


def test_compose_uses_named_persistent_data_volumes() -> None:
    compose_path = Path(__file__).parents[2] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    assert set(compose["volumes"]) == {"postgres-data", "redis-data"}
