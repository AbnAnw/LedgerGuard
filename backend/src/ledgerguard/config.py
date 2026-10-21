"""Validated application configuration."""

import re
from functools import lru_cache
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit

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
    max_request_body_bytes: int = Field(default=3_000_000, ge=65_536, le=25_000_000)
    rate_limit_enabled: bool = False
    rate_limit_requests_per_window: int = Field(default=120, ge=1, le=10_000)
    rate_limit_login_requests_per_window: int = Field(default=10, ge=1, le=1_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    synthetic_data_only: bool = True
    display_timezone: str = "UTC"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver", "api"]
    )

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

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("CORS_ORIGINS must contain at least one explicit origin")
        for value in values:
            parsed = urlsplit(value)
            try:
                _ = parsed.port
            except ValueError as error:
                raise ValueError("CORS_ORIGINS entries must contain valid ports") from error
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
            ):
                raise ValueError("CORS_ORIGINS entries must be explicit HTTP(S) origins")
            if (
                parsed.query
                or parsed.fragment
                or "*" in value
                or any(char.isspace() for char in value)
            ):
                raise ValueError("CORS_ORIGINS entries must not contain wildcards or URL extras")
        return values

    @field_validator("allowed_hosts")
    @classmethod
    def validate_allowed_hosts(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("ALLOWED_HOSTS must contain explicit host names without wildcards")
        dns_label = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.IGNORECASE)
        for value in values:
            try:
                ip_address(value)
                continue
            except ValueError:
                pass
            labels = value.split(".")
            if (
                len(value) > 253
                or not labels
                or any(not dns_label.fullmatch(label) for label in labels)
            ):
                raise ValueError("ALLOWED_HOSTS must contain explicit host names without wildcards")
        return values

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
        if self.app_env == "production":
            database = make_url(self.database_url)
            database_password = database.password or ""
            if (
                not database_password
                or "local-only" in database_password.lower()
                or "replace-with" in database_password.lower()
            ):
                raise ValueError(
                    "DATABASE_URL must contain a non-placeholder password in production"
                )
            if any(
                not value.startswith("rediss://")
                for value in (self.redis_url, self.celery_broker_url, self.celery_result_backend)
            ):
                raise ValueError("Redis and Celery URLs must use rediss:// in production")
            if self.otel_exporter_otlp_endpoint and not self.otel_exporter_otlp_endpoint.startswith(
                "https://"
            ):
                raise ValueError("OTEL_EXPORTER_OTLP_ENDPOINT must use HTTPS in production")
            if not self.rate_limit_enabled:
                raise ValueError("RATE_LIMIT_ENABLED must be true in production")
            if not self.synthetic_data_only:
                raise ValueError("SYNTHETIC_DATA_ONLY must remain true for this portfolio system")
            unsafe_hosts = {"localhost", "127.0.0.1", "testserver", "api"}
            if unsafe_hosts.intersection(host.lower() for host in self.allowed_hosts):
                raise ValueError("ALLOWED_HOSTS must name the production ingress host")
            if any(urlsplit(origin).scheme != "https" for origin in self.cors_origins):
                raise ValueError("CORS_ORIGINS must use HTTPS in production")
        return self

    @model_validator(mode="after")
    def validate_background_job_limits(self) -> "Settings":
        if (
            self.background_job_hard_time_limit_seconds
            <= self.background_job_soft_time_limit_seconds
        ):
            raise ValueError("BACKGROUND_JOB_HARD_TIME_LIMIT_SECONDS must exceed the soft limit")
        return self

    @model_validator(mode="after")
    def validate_request_size_limits(self) -> "Settings":
        multipart_overhead_allowance = 262_144
        if self.max_request_body_bytes < (
            self.ingestion_max_upload_bytes + multipart_overhead_allowance
        ):
            raise ValueError(
                "MAX_REQUEST_BODY_BYTES must exceed INGESTION_MAX_UPLOAD_BYTES by 262144 bytes"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings object per process."""

    return Settings()
