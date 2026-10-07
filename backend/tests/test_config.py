import pytest
from pydantic import ValidationError

from ledgerguard.config import Settings


def test_default_settings_are_valid_for_local_development() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.cors_origins == ["http://localhost:5173"]


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
