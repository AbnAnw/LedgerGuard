"""Validated application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    """Environment-backed settings shared by the API and worker."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "LedgerGuard"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    otel_exporter_otlp_endpoint: str | None = None
    otel_structured_log_exporter: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = (
        "postgresql+psycopg://ledgerguard:ledgerguard-local-only@localhost:5432/ledgerguard"
    )
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    background_job_max_attempts: int = Field(default=3, ge=1, le=10)
    background_job_soft_time_limit_seconds: int = Field(default=300, ge=30, le=3600)
    background_job_hard_time_limit_seconds: int = Field(default=330, ge=31, le=3660)
    auth_secret_key: SecretStr = SecretStr("local-development-secret-change-before-use-0001")
    access_token_expire_minutes: int = Field(default=30, ge=5, le=1440)
    login_max_failures: int = Field(default=5, ge=3, le=20)
    login_lock_minutes: int = Field(default=15, ge=1, le=1440)
    demo_user_password: SecretStr = SecretStr("DemoOnly!ChangeMe123456")
    ingestion_max_upload_bytes: int = Field(default=2_000_000, ge=1024, le=20_000_000)
    display_timezone: str = "UTC"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        url = make_url(value)
        if url.get_backend_name() != "postgresql":
            raise ValueError("DATABASE_URL must use PostgreSQL")
        return value

    @field_validator("redis_url", "celery_broker_url", "celery_result_backend")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("Redis URLs must use redis:// or rediss://")
        return value

    @field_validator("otel_exporter_otlp_endpoint", mode="before")
    @classmethod
    def validate_otel_endpoint(cls, value: object) -> object:
        if value in (None, ""):
            return None
        if not isinstance(value, str) or not value.startswith(("http://", "https://")):
            raise ValueError("OTEL_EXPORTER_OTLP_ENDPOINT must use http:// or https://")
        return value.rstrip("/")

    @model_validator(mode="after")
    def reject_development_secrets_in_production(self) -> "Settings":
        secret = self.auth_secret_key.get_secret_value().lower()
        if self.app_env == "production" and (
            "local-development" in secret or "replace-with" in secret or len(secret) < 32
        ):
            raise ValueError("AUTH_SECRET_KEY must be a non-placeholder secret in production")
        if (
            self.app_env == "production"
            and "demoonly" in self.demo_user_password.get_secret_value().lower()
        ):
            raise ValueError(
                "DEMO_USER_PASSWORD must not use the local demonstration value in production"
            )
        return self

    @model_validator(mode="after")
    def validate_background_job_limits(self) -> "Settings":
        if (
            self.background_job_hard_time_limit_seconds
            <= self.background_job_soft_time_limit_seconds
        ):
            raise ValueError("BACKGROUND_JOB_HARD_TIME_LIMIT_SECONDS must exceed the soft limit")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings object per process."""

    return Settings()
