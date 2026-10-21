import pytest
from pydantic import ValidationError

from ledgerguard.config import Settings


def test_default_settings_are_valid_for_local_development() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.background_job_max_attempts == 3
    assert settings.background_job_soft_time_limit_seconds == 300
    assert settings.background_job_hard_time_limit_seconds == 330
    assert settings.otel_exporter_otlp_endpoint is None
    assert settings.max_request_body_bytes == 3_000_000
    assert settings.rate_limit_enabled is False
    assert settings.synthetic_data_only is True


def test_non_postgresql_database_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must use PostgreSQL"):
        Settings(database_url="sqlite:///ledgerguard.db", _env_file=None)


def test_production_rejects_development_secret() -> None:
    with pytest.raises(ValidationError, match="non-placeholder secret"):
        Settings(
            app_env="production",
            auth_secret_key="local-development-secret-change-before-use-0001",
            _env_file=None,
        )


def test_production_rejects_local_demo_password() -> None:
    with pytest.raises(ValidationError, match="demonstration value"):
        Settings(
            app_env="production",
            auth_secret_key="production-shaped-secret-with-at-least-32-characters",
            demo_user_password="DemoOnly!ChangeMe123456",
            _env_file=None,
        )


def test_background_job_hard_limit_must_exceed_soft_limit() -> None:
    with pytest.raises(ValidationError, match="must exceed the soft limit"):
        Settings(
            background_job_soft_time_limit_seconds=300,
            background_job_hard_time_limit_seconds=300,
            _env_file=None,
        )


def test_otel_endpoint_must_use_http_transport() -> None:
    with pytest.raises(ValidationError, match="must use http"):
        Settings(otel_exporter_otlp_endpoint="grpc://collector:4317", _env_file=None)

    settings = Settings(
        otel_exporter_otlp_endpoint="https://collector.example.invalid:4318/", _env_file=None
    )
    assert settings.otel_exporter_otlp_endpoint == "https://collector.example.invalid:4318"


def test_request_body_limit_must_allow_multipart_overhead() -> None:
    with pytest.raises(ValidationError, match="must exceed INGESTION_MAX_UPLOAD_BYTES"):
        Settings(
            ingestion_max_upload_bytes=2_000_000,
            max_request_body_bytes=2_100_000,
            _env_file=None,
        )


@pytest.mark.parametrize(
    "origin",
    [
        "https://user:password@ledgerguard.example",
        "https://ledgerguard.example/",
        "https://ledgerguard.example:99999",
        "https://*.ledgerguard.example",
    ],
)
def test_cors_origins_must_be_explicit_and_well_formed(origin: str) -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        Settings(cors_origins=[origin], _env_file=None)


@pytest.mark.parametrize(
    "host",
    ["*.ledgerguard.example", "ledgerguard.example:443", "-ledgerguard.example", "bad host"],
)
def test_allowed_hosts_must_be_host_names_or_ip_addresses(host: str) -> None:
    with pytest.raises(ValidationError, match="ALLOWED_HOSTS"):
        Settings(allowed_hosts=[host], _env_file=None)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"rate_limit_enabled": False}, "RATE_LIMIT_ENABLED"),
        ({"synthetic_data_only": False}, "SYNTHETIC_DATA_ONLY"),
        ({"allowed_hosts": ["localhost"]}, "production ingress host"),
        ({"cors_origins": ["http://ledgerguard.example"]}, "HTTPS"),
        ({"redis_url": "redis://redis:6379/0"}, "rediss"),
        (
            {"database_url": "postgresql+psycopg://app:ledgerguard-local-only@db/app"},
            "DATABASE_URL",
        ),
    ],
)
def test_production_rejects_unsafe_security_configuration(
    override: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "app_env": "production",
        "auth_secret_key": "production-auth-secret-with-more-than-32-characters",
        "demo_user_password": "unused-production-demo-password",
        "database_url": "postgresql+psycopg://app:strong-production-db-password@db/app",
        "redis_url": "rediss://redis:6379/0",
        "celery_broker_url": "rediss://redis:6379/0",
        "celery_result_backend": "rediss://redis:6379/1",
        "rate_limit_enabled": True,
        "allowed_hosts": ["ledgerguard.example"],
        "cors_origins": ["https://ledgerguard.example"],
    }
    values.update(override)
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **values)
