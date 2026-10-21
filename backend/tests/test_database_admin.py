import pytest

from ledgerguard.database_admin import provision_runtime_role


def test_runtime_role_name_is_strictly_validated_before_connecting() -> None:
    with pytest.raises(ValueError, match="simple lowercase"):
        provision_runtime_role(
            "postgresql+psycopg://owner:password@localhost/ledgerguard",
            "ledgerguard-app; DROP ROLE owner",
            "runtime-password-long-enough",
        )


def test_runtime_role_password_has_a_minimum_length_before_connecting() -> None:
    with pytest.raises(ValueError, match="at least 16"):
        provision_runtime_role(
            "postgresql+psycopg://owner:password@localhost/ledgerguard",
            "ledgerguard_app",
            "too-short",
        )
