from __future__ import annotations

import random
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from ledgerguard.performance import (
    DATASET_VERSION,
    EXACT_MATCH_COUNT,
    MISSING_SETTLEMENT_COUNT,
    TRANSACTION_COUNT,
    benchmark_reconciliation,
    generate_performance_dataset,
)
from ledgerguard.reconciliation import (
    SettlementFact,
    TransactionFact,
    _candidate_edges,
    _is_candidate,
)


def test_performance_dataset_is_deterministic_decimal_safe_and_has_known_outcomes() -> None:
    first = generate_performance_dataset()
    second = generate_performance_dataset()

    assert first == second
    assert first.version == DATASET_VERSION
    assert len(first.transactions) == TRANSACTION_COUNT
    assert len(first.settlements) == EXACT_MATCH_COUNT
    assert first.expected_classification_counts == {
        "exact_match": EXACT_MATCH_COUNT,
        "missing_settlement": MISSING_SETTLEMENT_COUNT,
    }
    assert all(item.occurred_at.tzinfo is UTC for item in first.transactions)
    assert all(item.settled_at.tzinfo is UTC for item in first.settlements)
    assert all(item.amount.as_tuple().exponent == -6 for item in first.transactions)


@pytest.mark.parametrize(
    ("version", "count"),
    [("unknown", TRANSACTION_COUNT), (DATASET_VERSION, TRANSACTION_COUNT - 1)],
)
def test_performance_dataset_rejects_unsupported_contracts(version: str, count: int) -> None:
    with pytest.raises(ValueError):
        generate_performance_dataset(version=version, transaction_count=count)


def test_indexed_candidate_builder_matches_exhaustive_reference() -> None:
    generator = random.Random(1701)
    base_time = datetime(2026, 1, 1, tzinfo=UTC)
    references = [f"REF-{value}" for value in range(8)]
    currencies = ["AUD", "USD"]
    transactions = [
        TransactionFact(
            id=UUID(int=index + 1),
            source_record_id=f"TX-{index}",
            source_reference=generator.choice(references),
            amount=Decimal(generator.randint(1, 500)).quantize(Decimal("0.000001")),
            currency=generator.choice(currencies),
            occurred_at=base_time + timedelta(hours=generator.randint(0, 120)),
        )
        for index in range(120)
    ]
    settlements = [
        SettlementFact(
            id=UUID(int=1_000 + index),
            source_record_id=f"ST-{index}",
            source_reference=generator.choice(references),
            amount=Decimal(generator.randint(1, 500)).quantize(Decimal("0.000001")),
            currency=generator.choice(currencies),
            settled_at=base_time + timedelta(hours=generator.randint(0, 192)),
        )
        for index in range(100)
    ]
    ordered_transactions = sorted(transactions, key=lambda item: str(item.id))
    ordered_settlements = sorted(settlements, key=lambda item: str(item.id))
    window = timedelta(hours=72)
    expected_transactions: dict[UUID, list[UUID]] = defaultdict(list)
    expected_settlements: dict[UUID, list[UUID]] = defaultdict(list)
    for transaction in ordered_transactions:
        for settlement in ordered_settlements:
            if _is_candidate(transaction, settlement, window):
                expected_transactions[transaction.id].append(settlement.id)
                expected_settlements[settlement.id].append(transaction.id)

    actual_transactions, actual_settlements = _candidate_edges(
        ordered_transactions, ordered_settlements, window
    )

    assert actual_transactions == {
        item.id: tuple(sorted(expected_transactions[item.id], key=str))
        for item in ordered_transactions
    }
    assert actual_settlements == {
        item.id: tuple(sorted(expected_settlements[item.id], key=str))
        for item in ordered_settlements
    }


def test_benchmark_validates_all_ten_thousand_known_outcomes() -> None:
    result = benchmark_reconciliation(samples=1, warmups=0)

    assert result["dataset"]["transaction_count"] == TRANSACTION_COUNT
    assert result["results"]["failure_count"] == 0
    assert result["results"]["actual_classification_counts"] == {
        "exact_match": EXACT_MATCH_COUNT,
        "missing_settlement": MISSING_SETTLEMENT_COUNT,
    }
    assert result["results"]["throughput_transactions_per_second"] > 0
