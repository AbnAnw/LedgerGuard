from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ledgerguard.auth import AuthPrincipal, get_current_principal
from ledgerguard.dashboard import (
    DashboardMetrics,
    DashboardOverviewResponse,
    build_dashboard_overview,
    calculate_dashboard_metrics,
)
from ledgerguard.db import get_db
from ledgerguard.main import app
from ledgerguard.models import (
    Account,
    AccountStatus,
    AccountType,
    IngestionBatch,
    IngestionBatchStatus,
    IngestionRecordKind,
    ReconciliationClassification,
    ReconciliationRunStatus,
)
from ledgerguard.reconciliation import (
    ReconciliationResultResponse,
    ReconciliationRunResponse,
    ReconciliationSummary,
)

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def uid(value: int) -> UUID:
    return UUID(int=value)


def principal(role: str) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email=f"{role}@ledgerguard.invalid",
        display_name=f"Synthetic {role}",
        roles=(role,),
    )


def result(
    value: int,
    classification: ReconciliationClassification,
    transaction_total: str,
    settlement_total: str,
) -> ReconciliationResultResponse:
    difference = str(Decimal(settlement_total) - Decimal(transaction_total))
    return ReconciliationResultResponse(
        id=uid(value),
        classification=classification,
        reason_code=f"REASON-{value}",
        currency="USD",
        transaction_total=transaction_total,
        settlement_total=settlement_total,
        difference_amount=difference,
        evidence={},
        evidence_sha256=f"{value:064x}",
        transactions=[],
        settlements=[],
    )


def run_response() -> ReconciliationRunResponse:
    results = [
        result(1, ReconciliationClassification.EXACT_MATCH, "100.000000", "100.000000"),
        result(2, ReconciliationClassification.PARTIAL_MATCH, "100.000000", "60.000000"),
        result(3, ReconciliationClassification.MISSING_SETTLEMENT, "30.000000", "0"),
        result(4, ReconciliationClassification.DUPLICATE_CANDIDATE, "20.000000", "40.000000"),
        result(5, ReconciliationClassification.UNEXPLAINED_SETTLEMENT, "0", "15.000000"),
    ]
    return ReconciliationRunResponse(
        run_id=uid(100),
        account_id=uid(200),
        source_system="synthetic-reconciliation",
        source_account_id="DEMO-RECON-001",
        algorithm_version="reconciliation-v1.0.0",
        input_cutoff_at=NOW,
        configuration={"match_window_hours": 72},
        replay_key="a" * 64,
        status=ReconciliationRunStatus.COMPLETED,
        replayed=False,
        summary=ReconciliationSummary(
            transaction_count=4,
            settlement_count=5,
            transaction_value="250.000000",
            settlement_value="215.000000",
            result_count=5,
            classification_counts={
                classification.value: 1 for classification in ReconciliationClassification
            },
        ),
        results=results,
    )


def overview() -> DashboardOverviewResponse:
    return DashboardOverviewResponse(
        account_id=uid(200),
        source_system="synthetic-reconciliation",
        source_account_id="DEMO-RECON-001",
        display_name="Synthetic Reconciliation Demonstration Account",
        currency="USD",
        metrics=calculate_dashboard_metrics(run_response(), 2),
        latest_run=run_response(),
        batches=[],
    )


def test_dashboard_metrics_use_decimal_safe_documented_definitions() -> None:
    metrics = calculate_dashboard_metrics(run_response(), validation_failure_count=3)

    assert metrics.transaction_value == "250.000000"
    assert metrics.settlement_value == "215.000000"
    assert metrics.exact_matched_value == "100.000000"
    assert metrics.unresolved_value == "185.000000"
    assert metrics.match_rate_percent == "40.00"
    assert metrics.validation_failure_count == 3
    assert metrics.classification_counts == {
        classification.value: 1 for classification in ReconciliationClassification
    }


def test_empty_dashboard_metrics_are_explicit_zero_values() -> None:
    assert calculate_dashboard_metrics(None, 4) == DashboardMetrics(
        transaction_count=0,
        settlement_count=0,
        transaction_value="0",
        settlement_value="0",
        exact_matched_value="0",
        unresolved_value="0",
        match_rate_percent="0.00",
        validation_failure_count=4,
        classification_counts={
            classification.value: 0 for classification in ReconciliationClassification
        },
    )


def test_overview_scopes_batches_to_the_selected_account() -> None:
    account = Account(
        id=uid(200),
        source_system="synthetic-reconciliation",
        source_account_id="DEMO-RECON-001",
        display_name="Synthetic Reconciliation Demonstration Account",
        account_type=AccountType.MERCHANT,
        default_currency="USD",
        status=AccountStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )
    batch = IngestionBatch(
        id=uid(300),
        record_kind=IngestionRecordKind.TRANSACTION,
        source_system="synthetic-reconciliation-v1",
        schema_version="1.0",
        idempotency_key="dashboard-test",
        payload_sha256="b" * 64,
        status=IngestionBatchStatus.COMPLETED_WITH_ERRORS,
        source_count=3,
        accepted_count=2,
        rejected_count=1,
        duplicate_count=0,
        conflict_count=0,
        requested_by_user_id=uid(400),
        correlation_id=uid(401),
        started_at=NOW,
        finished_at=NOW,
        created_at=NOW,
        version=1,
    )
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [account, None, 1]
    transaction_batches = SimpleNamespace(all=lambda: [batch.id])
    settlement_batches = SimpleNamespace(all=lambda: [])
    batches = SimpleNamespace(all=lambda: [batch])
    db.scalars.side_effect = [transaction_batches, settlement_batches, batches]

    response = build_dashboard_overview(db, "synthetic-reconciliation", "DEMO-RECON-001", 10)

    assert response.latest_run is None
    assert response.metrics.validation_failure_count == 1
    assert [item.id for item in response.batches] == [batch.id]
    latest_run_statement = str(db.scalar.call_args_list[1].args[0])
    assert (
        "ORDER BY reconciliation_runs.input_cutoff_at DESC, "
        "reconciliation_runs.created_at DESC, reconciliation_runs.id DESC" in latest_run_statement
    )


def test_unknown_account_returns_not_found() -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = None

    with pytest.raises(HTTPException) as error:
        build_dashboard_overview(db, "synthetic-reconciliation", "UNKNOWN", 10)

    assert error.value.status_code == 404


@pytest.mark.parametrize("role", ["administrator", "operations_analyst", "auditor"])
def test_authorized_roles_can_read_dashboard(
    role: str, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal(role)
    app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(
        "ledgerguard.dashboard.build_dashboard_overview",
        lambda _db, _source_system, _source_account_id, _batch_limit: overview(),
    )

    response = client.get(
        "/api/v1/dashboard/overview",
        params={
            "source_system": "synthetic-reconciliation",
            "source_account_id": "DEMO-RECON-001",
        },
    )

    assert response.status_code == 200
    assert response.json()["metrics"]["match_rate_percent"] == "40.00"


def test_unknown_role_cannot_read_dashboard(client: TestClient) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal("unknown_role")
    app.dependency_overrides[get_db] = lambda: MagicMock(spec=Session)

    response = client.get(
        "/api/v1/dashboard/overview",
        params={
            "source_system": "synthetic-reconciliation",
            "source_account_id": "DEMO-RECON-001",
        },
    )

    assert response.status_code == 403
