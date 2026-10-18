from pathlib import Path

import yaml


def test_compose_declares_required_services_and_health_checks() -> None:
    compose_path = Path(__file__).parents[2] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = compose["services"]

    assert set(services) == {
        "postgres",
        "redis",
        "api",
        "worker",
        "frontend",
        "prometheus",
        "grafana",
    }
    for service_name in ("postgres", "redis", "api", "worker", "prometheus", "grafana"):
        assert "healthcheck" in services[service_name]

    assert services["api"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert services["worker"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert services["prometheus"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert services["grafana"]["depends_on"]["prometheus"]["condition"] == "service_healthy"


def test_compose_uses_named_persistent_data_volumes() -> None:
    compose_path = Path(__file__).parents[2] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    assert set(compose["volumes"]) == {
        "postgres-data",
        "redis-data",
        "prometheus-data",
        "grafana-data",
    }


def test_observability_services_use_provisioned_loopback_only_configuration() -> None:
    root = Path(__file__).parents[2]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))

    assert compose["services"]["prometheus"]["ports"] == ["127.0.0.1:${PROMETHEUS_PORT:-9090}:9090"]
    assert compose["services"]["grafana"]["ports"] == ["127.0.0.1:${GRAFANA_PORT:-3000}:3000"]
    prometheus = yaml.safe_load(
        (root / "infra" / "observability" / "prometheus.yml").read_text(encoding="utf-8")
    )
    assert prometheus["scrape_configs"][0]["static_configs"][0]["targets"] == ["api:8000"]

    dashboard = root / "infra" / "observability" / "grafana" / "dashboards"
    assert (dashboard / "ledgerguard-operations.json").is_file()
