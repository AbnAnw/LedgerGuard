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
