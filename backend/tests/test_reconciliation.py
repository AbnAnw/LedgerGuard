from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ledgerguard.auth import AuthPrincipal, get_current_principal
from ledgerguard.db import get_db
from ledgerguard.main import app
from ledgerguard.models import ReconciliationClassification, ReconciliationRunStatus
from ledgerguard.reconciliation import (
    ALGORITHM_VERSION,
    ReconciliationRunRequest,
    ReconciliationRunResponse,
    ReconciliationSummary,
    SettlementFact,
    TransactionFact,
    build_reconciliation_decisions,
)

BASE_TIME = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def uid(value: int) -> UUID:
    return UUID(int=value)


def transaction(
    value: int,
    reference: str,
    amount: str,
    *,
    currency: str = "USD",
    occurred_at: datetime = BASE_TIME,
) -> TransactionFact:
    return TransactionFact(
        id=uid(value),
        source_record_id=f"TX-{value}",
        source_reference=reference,
        amount=Decimal(amount),
        currency=currency,
        occurred_at=occurred_at,
    )


def settlement(
    value: int,
    reference: str,
    amount: str,
    *,
    currency: str = "USD",
    settled_at: datetime = BASE_TIME + timedelta(hours=1),
) -> SettlementFact:
    return SettlementFact(
        id=uid(value),
        source_record_id=f"ST-{value}",
        source_reference=reference,
        amount=Decimal(amount),
        currency=currency,
        settled_at=settled_at,
    )


def principal(role: str) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email=f"{role}@ledgerguard.invalid",
        display_name=f"Synthetic {role}",
        roles=(role,),
    )


def empty_response(*, replayed: bool = False) -> ReconciliationRunResponse:
    return ReconciliationRunResponse(
        run_id=uid(900),
        account_id=uid(901),
        source_system="synthetic-demo",
        source_account_id="DEMO-ACCOUNT-001",
        algorithm_version=ALGORITHM_VERSION,
        input_cutoff_at=BASE_TIME,
        configuration={"match_window_hours": 72},
        replay_key="a" * 64,
        status=ReconciliationRunStatus.COMPLETED,
        replayed=replayed,
        summary=ReconciliationSummary(
            transaction_count=0,
            settlement_count=0,
            transaction_value="0",
            settlement_value="0",
            result_count=0,
            classification_counts={
                classification.value: 0 for classification in ReconciliationClassification
            },
        ),
        results=[],
    )


def test_seeded_scenario_produces_all_explainable_classifications() -> None:
    transactions = [
        transaction(1, "REF-EXACT", "100.000000"),
        transaction(2, "REF-PARTIAL", "100.000000"),
        transaction(3, "REF-MISSING", "30.000000"),
        transaction(4, "REF-DUPLICATE", "20.000000"),
    ]
    settlements = [
        settlement(101, "REF-EXACT", "100.000000"),
        settlement(102, "REF-PARTIAL", "60.000000"),
        settlement(103, "REF-DUPLICATE", "20.000000"),
        settlement(104, "REF-DUPLICATE", "20.000000", settled_at=BASE_TIME + timedelta(hours=2)),
        settlement(105, "REF-UNEXPLAINED", "15.000000"),
    ]

    decisions = build_reconciliation_decisions(transactions, settlements, 72)
    by_classification = {decision.classification: decision for decision in decisions}

    assert set(by_classification) == set(ReconciliationClassification)
    assert by_classification[ReconciliationClassification.EXACT_MATCH].reason_code == (
        "EXACT_REFERENCE_AMOUNT_CURRENCY_TIME"
    )
    partial = by_classification[ReconciliationClassification.PARTIAL_MATCH]
    assert partial.reason_code == "PARTIAL_AMOUNT_MISMATCH"
    assert partial.evidence["classification"] == "partial_match"
    assert partial.transaction_total == Decimal("100.000000")
    assert partial.settlement_total == Decimal("60.000000")
    assert partial.difference_amount == Decimal("-40.000000")
    duplicate = by_classification[ReconciliationClassification.DUPLICATE_CANDIDATE]
    assert len(duplicate.transactions) == 1
    assert len(duplicate.settlements) == 2
    assert duplicate.evidence["candidate_comparisons"] == [
        {
            "transaction_id": str(uid(4)),
            "settlement_id": str(uid(103)),
            "reference_equal": True,
            "currency_equal": True,
            "within_utc_window": True,
            "amount_equal": True,
        },
        {
            "transaction_id": str(uid(4)),
            "settlement_id": str(uid(104)),
            "reference_equal": True,
            "currency_equal": True,
            "within_utc_window": True,
            "amount_equal": True,
        },
    ]
    assert all(len(decision.evidence_sha256) == 64 for decision in decisions)
    assert sum(len(decision.transactions) for decision in decisions) == len(transactions)
    assert sum(len(decision.settlements) for decision in decisions) == len(settlements)


def test_decisions_and_evidence_hashes_are_input_order_independent() -> None:
    transactions = [transaction(2, "REF-B", "40"), transaction(1, "REF-A", "10")]
    settlements = [settlement(102, "REF-B", "30"), settlement(101, "REF-A", "10")]

    first = build_reconciliation_decisions(transactions, settlements, 72)
    second = build_reconciliation_decisions(
        list(reversed(transactions)), list(reversed(settlements)), 72
    )

    assert [decision.evidence for decision in first] == [decision.evidence for decision in second]
    assert [decision.evidence_sha256 for decision in first] == [
        decision.evidence_sha256 for decision in second
    ]


def test_time_window_boundaries_are_inclusive_and_outside_values_are_unexplained() -> None:
    transactions = [transaction(1, "REF-BOUNDARY", "25")]
    settlements = [
        settlement(101, "REF-BOUNDARY", "25", settled_at=BASE_TIME),
        settlement(102, "REF-BOUNDARY", "25", settled_at=BASE_TIME + timedelta(hours=72)),
        settlement(103, "REF-BOUNDARY", "25", settled_at=BASE_TIME - timedelta(seconds=1)),
        settlement(
            104,
            "REF-BOUNDARY",
            "25",
            settled_at=BASE_TIME + timedelta(hours=72, seconds=1),
        ),
    ]

    decisions = build_reconciliation_decisions(transactions, settlements, 72)

    duplicate = next(
        item
        for item in decisions
        if item.classification == ReconciliationClassification.DUPLICATE_CANDIDATE
    )
    unexplained = [
        item
        for item in decisions
        if item.classification == ReconciliationClassification.UNEXPLAINED_SETTLEMENT
    ]
    assert {fact.id for fact in duplicate.settlements} == {uid(101), uid(102)}
    assert {item.settlements[0].id for item in unexplained} == {uid(103), uid(104)}


def test_reference_and_currency_mismatches_never_match() -> None:
    decisions = build_reconciliation_decisions(
        [transaction(1, "REF-ONE", "10", currency="USD")],
        [
            settlement(101, "REF-TWO", "10", currency="USD"),
            settlement(102, "REF-ONE", "10", currency="EUR"),
        ],
        72,
    )

    assert (
        sum(
            item.classification == ReconciliationClassification.MISSING_SETTLEMENT
            for item in decisions
        )
        == 1
    )
    assert (
        sum(
            item.classification == ReconciliationClassification.UNEXPLAINED_SETTLEMENT
            for item in decisions
        )
        == 2
    )


def test_request_rejects_naive_cutoff_and_normalizes_offsets_to_utc() -> None:
    with pytest.raises(ValidationError, match="must include a UTC offset"):
        ReconciliationRunRequest(
            source_system="synthetic-demo",
            source_account_id="DEMO-ACCOUNT-001",
            input_cutoff_at=datetime(2026, 10, 14, 12, 0),
        )

    request = ReconciliationRunRequest(
        source_system="synthetic-demo",
        source_account_id="DEMO-ACCOUNT-001",
        input_cutoff_at="2026-10-14T20:00:00+08:00",
    )
    assert request.input_cutoff_at == datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def test_analyst_can_create_run_and_replay_returns_http_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal("operations_analyst")
    app.dependency_overrides[get_db] = lambda: object()
    responses = iter((empty_response(), empty_response(replayed=True)))
    monkeypatch.setattr(
        "ledgerguard.reconciliation.execute_reconciliation",
        lambda _db, _request, _principal: next(responses),
    )
    payload = {
        "source_system": "synthetic-demo",
        "source_account_id": "DEMO-ACCOUNT-001",
        "input_cutoff_at": "2026-10-14T09:00:00Z",
        "match_window_hours": 72,
    }

    created = client.post("/api/v1/reconciliation/runs", json=payload)
    replayed = client.post("/api/v1/reconciliation/runs", json=payload)

    assert created.status_code == 201
    assert created.json()["replayed"] is False
    assert replayed.status_code == 200
    assert replayed.json()["replayed"] is True


def test_auditor_cannot_create_reconciliation_run(client: TestClient) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal("auditor")

    response = client.post(
        "/api/v1/reconciliation/runs",
        json={
            "source_system": "synthetic-demo",
            "source_account_id": "DEMO-ACCOUNT-001",
            "input_cutoff_at": "2026-10-14T09:00:00Z",
        },
    )

    assert response.status_code == 403


def test_auditor_can_read_stored_reconciliation_evidence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = SimpleNamespace(account_id=uid(901))
    account = object()
    db = MagicMock(spec=Session)
    db.get.side_effect = [run, account]
    app.dependency_overrides[get_current_principal] = lambda: principal("auditor")
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(
        "ledgerguard.reconciliation.load_reconciliation_run_response",
        lambda _db, _run, _account, replayed: empty_response(replayed=replayed),
    )

    response = client.get(f"/api/v1/reconciliation/runs/{uid(900)}")

    assert response.status_code == 200
    assert response.json()["algorithm_version"] == ALGORITHM_VERSION
