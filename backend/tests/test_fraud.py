from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ledgerguard.auth import AuthPrincipal, get_current_principal
from ledgerguard.db import get_db
from ledgerguard.fraud import (
    FraudRuleSpec,
    FraudTransactionFact,
    build_fraud_decisions,
    evaluate_rule,
    normalize_rule_parameters,
)
from ledgerguard.main import app
from ledgerguard.models import AlertSeverity, FraudRuleType, TransactionStatus

BASE_TIME = datetime(2026, 1, 20, 2, 0, tzinfo=UTC)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def uid(value: int) -> UUID:
    return UUID(int=value)


def fact(
    value: int,
    *,
    minutes: int,
    amount: str = "20.000000",
    reference: str | None = None,
    transaction_status: TransactionStatus = TransactionStatus.POSTED,
    fingerprint: str | None = "synthetic-fingerprint-a",
) -> FraudTransactionFact:
    return FraudTransactionFact(
        id=uid(value),
        source_record_id=f"FRAUD-TX-{value}",
        source_reference=reference or f"REF-{value}",
        amount=Decimal(amount),
        currency="USD",
        status=transaction_status,
        instrument_fingerprint=fingerprint,
        occurred_at=BASE_TIME + timedelta(minutes=minutes),
    )


def rule(value: int, rule_type: FraudRuleType, parameters: dict[str, object]) -> FraudRuleSpec:
    return FraudRuleSpec(
        id=uid(100 + value),
        rule_id=uid(200 + value),
        rule_code=f"synthetic_{rule_type.value}",
        version_number=1,
        rule_type=rule_type,
        parameters=parameters,
        severity=AlertSeverity.HIGH,
    )


def principal(role: str) -> AuthPrincipal:
    return AuthPrincipal(
        user_id=uuid4(),
        session_id=uuid4(),
        email=f"{role}@ledgerguard.invalid",
        display_name=f"Synthetic {role}",
        roles=(role,),
    )


def test_all_five_rules_create_explainable_deterministic_decisions() -> None:
    facts = (
        fact(1, minutes=-40, transaction_status=TransactionStatus.REVERSED),
        fact(2, minutes=-30, transaction_status=TransactionStatus.VOIDED),
        fact(3, minutes=-20, reference="REF-FIRST"),
        fact(4, minutes=-10, reference="REF-SECOND"),
        fact(5, minutes=0, amount="1250.000000", reference="REF-SUBJECT"),
    )
    rules = (
        rule(1, FraudRuleType.VELOCITY, {"window_minutes": 60, "count_threshold": 3}),
        rule(2, FraudRuleType.UNUSUAL_AMOUNT, {"amount_threshold": "1000.000000"}),
        rule(3, FraudRuleType.REPEATED_FAILURE, {"window_hours": 24, "count_threshold": 2}),
        rule(
            4,
            FraudRuleType.DUPLICATE_INSTRUMENT,
            {"window_hours": 24, "distinct_reference_threshold": 3},
        ),
        rule(5, FraudRuleType.SUSPICIOUS_TIMING, {"start_hour_utc": 0, "end_hour_utc": 5}),
    )

    first = build_fraud_decisions(rules, facts, BASE_TIME)
    second = build_fraud_decisions(rules, tuple(reversed(facts)), BASE_TIME)

    reason_codes = {decision.reason_code for decision in first}
    assert {
        "VELOCITY_THRESHOLD_MET",
        "UNUSUAL_AMOUNT_THRESHOLD_MET",
        "REPEATED_FAILURE_THRESHOLD_MET",
        "DUPLICATE_INSTRUMENT_THRESHOLD_MET",
        "SUSPICIOUS_UTC_TIME_WINDOW",
    } <= reason_codes
    assert [decision.evidence_sha256 for decision in first] == [
        decision.evidence_sha256 for decision in second
    ]
    assert all(decision.evidence["output"]["triggered"] is True for decision in first)
    assert all(decision.evidence["rule"]["version_number"] == 1 for decision in first)
    assert all(Decimal("0") <= decision.score <= Decimal("100") for decision in first)


@pytest.mark.parametrize(
    ("rule_type", "parameters"),
    [
        (FraudRuleType.VELOCITY, {"window_minutes": 15, "count_threshold": 2}),
        (FraudRuleType.UNUSUAL_AMOUNT, {"amount_threshold": "100.000000"}),
        (FraudRuleType.REPEATED_FAILURE, {"window_hours": 1, "count_threshold": 1}),
        (
            FraudRuleType.DUPLICATE_INSTRUMENT,
            {"window_hours": 1, "distinct_reference_threshold": 2},
        ),
        (FraudRuleType.SUSPICIOUS_TIMING, {"start_hour_utc": 20, "end_hour_utc": 1}),
    ],
)
def test_non_triggering_scenarios_do_not_create_decisions(
    rule_type: FraudRuleType, parameters: dict[str, object]
) -> None:
    subject = fact(10, minutes=0, amount="10.000000", fingerprint=None)
    assert evaluate_rule(rule(10, rule_type, parameters), subject, (subject,), BASE_TIME) is None


def test_wrapped_suspicious_time_window_is_half_open() -> None:
    overnight = rule(
        1,
        FraudRuleType.SUSPICIOUS_TIMING,
        {"start_hour_utc": 22, "end_hour_utc": 3},
    )
    at_two = fact(1, minutes=0)
    at_three = fact(2, minutes=60)
    assert evaluate_rule(overnight, at_two, (at_two,), at_two.occurred_at) is not None
    assert evaluate_rule(overnight, at_three, (at_three,), at_three.occurred_at) is None


def test_unusual_amount_uses_exact_decimal_threshold_boundary() -> None:
    amount_rule = rule(
        1,
        FraudRuleType.UNUSUAL_AMOUNT,
        {"amount_threshold": "100.000001"},
    )
    below = fact(1, minutes=0, amount="100.000000")
    at_threshold = fact(2, minutes=1, amount="100.000001")

    assert evaluate_rule(amount_rule, below, (below,), BASE_TIME) is None
    decision = evaluate_rule(amount_rule, at_threshold, (at_threshold,), BASE_TIME)
    assert decision is not None
    assert decision.evidence["evaluated_inputs"]["metric"] == "100.000001"
    assert decision.evidence["evaluated_inputs"]["threshold"] == "100.000001"


@pytest.mark.parametrize(
    ("rule_type", "parameters"),
    [
        (FraudRuleType.UNUSUAL_AMOUNT, {"amount_threshold": 10.5}),
        (FraudRuleType.UNUSUAL_AMOUNT, {"amount_threshold": "0.000000"}),
        (FraudRuleType.VELOCITY, {"window_minutes": 0, "count_threshold": 2}),
        (
            FraudRuleType.DUPLICATE_INSTRUMENT,
            {"window_hours": 24, "distinct_reference_threshold": 2, "extra": 1},
        ),
        (FraudRuleType.SUSPICIOUS_TIMING, {"start_hour_utc": 5, "end_hour_utc": 5}),
    ],
)
def test_rule_parameter_contract_rejects_unsafe_values(
    rule_type: FraudRuleType, parameters: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        normalize_rule_parameters(rule_type, parameters)


def test_auditor_can_read_rules_but_cannot_run_evaluation(client: TestClient) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal("auditor")
    db = MagicMock(spec=Session)
    db.scalars.return_value = []
    app.dependency_overrides[get_db] = lambda: db

    assert client.get("/api/v1/fraud/rules").status_code == 200
    denied = client.post(
        "/api/v1/fraud/evaluations",
        json={
            "source_system": "synthetic-fraud",
            "source_account_id": "DEMO-FRAUD-001",
            "input_cutoff_at": BASE_TIME.isoformat(),
        },
    )
    assert denied.status_code == 403


def test_analyst_cannot_change_rule_configuration(client: TestClient) -> None:
    app.dependency_overrides[get_current_principal] = lambda: principal("operations_analyst")
    response = client.post(
        "/api/v1/fraud/rules",
        json={
            "code": "amount_review",
            "name": "Amount review",
            "rule_type": "unusual_amount",
            "parameters": {"amount_threshold": "1000.000000"},
            "severity": "high",
        },
    )
    assert response.status_code == 403


def test_unauthenticated_alert_read_is_denied(client: TestClient) -> None:
    assert client.get("/api/v1/fraud/alerts").status_code == 401
