import csv
import io
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ledgerguard.auth import AuthPrincipal, get_current_principal
from ledgerguard.db import get_db
from ledgerguard.main import app
from ledgerguard.models import CasePriority, CaseStatus
from ledgerguard.reports import (
    DAILY_CSV_FIELDS,
    UNRESOLVED_CSV_FIELDS,
    CurrencyTotals,
    DailyReconciliationReport,
    ExactTotal,
    ReportTotalMismatch,
    UnresolvedCaseReport,
    UnresolvedCaseRow,
    aggregate_exact_totals,
    daily_report_csv,
    neutralize_csv_cell,
    unresolved_report_csv,
    verify_exact_totals,
)

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def principal(role: str) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email=f"{role}@ledgerguard.invalid",
        display_name=f"Synthetic {role}",
        roles=(role,),
    )


def daily_report() -> DailyReconciliationReport:
    return DailyReconciliationReport(
        report_date=date(2026, 10, 16),
        window_start=datetime(2026, 10, 16, tzinfo=UTC),
        window_end=datetime(2026, 10, 17, tzinfo=UTC),
        generated_at=NOW,
        account_id=UUID(int=1),
        source_system="synthetic-reconciliation",
        source_account_id="DEMO-RECON-001",
        totals_verified=True,
        currency_totals=[
            CurrencyTotals(
                currency="USD",
                transaction_count=2,
                transaction_total="30.000000",
                settlement_count=1,
                settlement_total="10.000000",
                difference="-20.000000",
            )
        ],
        reconciliation_snapshot=None,
    )


def unresolved_report(*, title: str = "Synthetic unresolved case") -> UnresolvedCaseReport:
    return UnresolvedCaseReport(
        cutoff_at=NOW,
        generated_at=NOW,
        case_count=1,
        cases=[
            UnresolvedCaseRow(
                case_id=UUID(int=2),
                case_number=42,
                title=title,
                status=CaseStatus.IN_REVIEW,
                priority=CasePriority.HIGH,
                owner_user_id=None,
                owner_display_name=None,
                created_at=datetime(2026, 10, 15, 12, 0, tzinfo=UTC),
                age_hours=24,
                alert_count=2,
                rule_codes=["unusual_amount", "velocity"],
            )
        ],
    )


def test_exact_totals_use_decimal_and_preserve_currency_boundaries() -> None:
    totals = aggregate_exact_totals(
        [
            ("USD", Decimal("0.100000")),
            ("USD", Decimal("0.200000")),
            ("AUD", Decimal("12.345678")),
        ]
    )

    assert totals == {
        "USD": ExactTotal(2, Decimal("0.300000")),
        "AUD": ExactTotal(1, Decimal("12.345678")),
    }
    verify_exact_totals(totals, dict(totals))


def test_independent_total_mismatch_fails_closed() -> None:
    with pytest.raises(ReportTotalMismatch, match="do not match"):
        verify_exact_totals(
            {"USD": ExactTotal(1, Decimal("1.000000"))},
            {"USD": ExactTotal(1, Decimal("1.000001"))},
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=2+2", "'=2+2"),
        (" +SUM(A1:A2)", "' +SUM(A1:A2)"),
        ("-20.000000", "'-20.000000"),
        ("@IMPORT", "'@IMPORT"),
        ("\t=cmd", "'\t=cmd"),
        ("ordinary text", "ordinary text"),
        (None, ""),
    ],
)
def test_csv_formula_controls_are_neutralized(value: object | None, expected: str) -> None:
    assert neutralize_csv_cell(value) == expected


def test_daily_csv_uses_allowlisted_fields_and_verified_report_values() -> None:
    response = daily_report_csv(daily_report())
    rows = list(csv.DictReader(io.StringIO(response.body.decode("utf-8"))))

    assert tuple(rows[0]) == DAILY_CSV_FIELDS
    assert rows[0]["transaction_total"] == "30.000000"
    assert rows[0]["difference"] == "'-20.000000"
    assert rows[0]["totals_verified"] == "true"
    assert response.headers["content-disposition"] == (
        'attachment; filename="ledgerguard-daily-reconciliation.csv"'
    )


def test_unresolved_csv_neutralizes_user_controlled_title() -> None:
    response = unresolved_report_csv(unresolved_report(title='=HYPERLINK("bad")'))
    rows = list(csv.DictReader(io.StringIO(response.body.decode("utf-8"))))

    assert tuple(rows[0]) == UNRESOLVED_CSV_FIELDS
    assert rows[0]["title"] == '\'=HYPERLINK("bad")'
    assert rows[0]["rule_codes"] == "unusual_amount|velocity"


@pytest.mark.parametrize("role", ["administrator", "operations_analyst", "auditor"])
def test_supported_roles_can_read_verified_daily_report(
    role: str, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = MagicMock(spec=Session)
    app.dependency_overrides[get_current_principal] = lambda: principal(role)
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(
        "ledgerguard.reports.build_daily_reconciliation_report",
        lambda *_args, **_kwargs: daily_report(),
    )

    response = client.get(
        "/api/v1/reports/daily-reconciliation",
        params={
            "report_date": "2026-10-16",
            "source_system": "synthetic-reconciliation",
            "source_account_id": "DEMO-RECON-001",
        },
    )

    assert response.status_code == 200
    assert response.json()["totals_verified"] is True
    assert db.add.call_args.args[0].action == "report.daily.view"
    db.commit.assert_called_once()


def test_unknown_role_is_denied_report_access(client: TestClient) -> None:
    db = MagicMock(spec=Session)
    db.get.return_value = None
    app.dependency_overrides[get_current_principal] = lambda: principal("unknown_role")
    app.dependency_overrides[get_db] = lambda: db

    response = client.get(
        "/api/v1/reports/daily-reconciliation",
        params={
            "report_date": "2026-10-16",
            "source_system": "synthetic-reconciliation",
            "source_account_id": "DEMO-RECON-001",
        },
    )

    assert response.status_code == 403
    assert db.add.call_args.args[0].action == "authz.permission_denied"


def test_daily_total_mismatch_returns_no_partial_report(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = MagicMock(spec=Session)
    app.dependency_overrides[get_current_principal] = lambda: principal("auditor")
    app.dependency_overrides[get_db] = lambda: db

    def mismatch(*_args: object, **_kwargs: object) -> DailyReconciliationReport:
        raise ReportTotalMismatch("synthetic independent mismatch")

    monkeypatch.setattr("ledgerguard.reports.build_daily_reconciliation_report", mismatch)
    response = client.get(
        "/api/v1/reports/daily-reconciliation.csv",
        params={
            "report_date": "2026-10-16",
            "source_system": "synthetic-reconciliation",
            "source_account_id": "DEMO-RECON-001",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "REPORT_TOTAL_MISMATCH"
    db.add.assert_not_called()


def test_unresolved_export_is_audited_and_formula_safe(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = MagicMock(spec=Session)
    app.dependency_overrides[get_current_principal] = lambda: principal("operations_analyst")
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(
        "ledgerguard.reports.build_unresolved_case_report",
        lambda *_args, **_kwargs: unresolved_report(title="=2+2"),
    )

    response = client.get(
        "/api/v1/reports/unresolved-cases.csv",
        params={"cutoff_at": NOW.isoformat()},
    )

    assert response.status_code == 200
    assert "'=2+2" in response.text
    assert db.add.call_args.args[0].action == "report.unresolved.export"


def test_unresolved_report_requires_offset_aware_cutoff(client: TestClient) -> None:
    db = MagicMock(spec=Session)
    app.dependency_overrides[get_current_principal] = lambda: principal("auditor")
    app.dependency_overrides[get_db] = lambda: db

    response = client.get(
        "/api/v1/reports/unresolved-cases",
        params={"cutoff_at": "2026-10-16T12:00:00"},
    )

    assert response.status_code == 422
    assert "UTC offset" in response.json()["detail"]
