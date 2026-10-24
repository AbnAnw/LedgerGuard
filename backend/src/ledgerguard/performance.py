"""Deterministic Day 17 performance workload and benchmark runner."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID

from ledgerguard.models import ReconciliationClassification
from ledgerguard.reconciliation import (
    SettlementFact,
    TransactionFact,
    build_reconciliation_decisions,
)

DATASET_VERSION = "performance-v1"
TRANSACTION_COUNT = 10_000
EXACT_MATCH_COUNT = 8_000
MISSING_SETTLEMENT_COUNT = 2_000
MATCH_WINDOW_HOURS = 72
BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class PerformanceDataset:
    version: str
    transactions: tuple[TransactionFact, ...]
    settlements: tuple[SettlementFact, ...]
    expected_classification_counts: dict[str, int]


def generate_performance_dataset(
    *, version: str = DATASET_VERSION, transaction_count: int = TRANSACTION_COUNT
) -> PerformanceDataset:
    """Build the one supported, deterministic, synthetic performance fixture."""

    if version != DATASET_VERSION:
        raise ValueError(f"Unsupported performance dataset version: {version}")
    if transaction_count != TRANSACTION_COUNT:
        raise ValueError(f"{DATASET_VERSION} requires exactly {TRANSACTION_COUNT} transactions")

    transactions: list[TransactionFact] = []
    settlements: list[SettlementFact] = []
    for index in range(transaction_count):
        amount = Decimal((index % 997) + 1).quantize(Decimal("0.000001"))
        occurred_at = BASE_TIME + timedelta(seconds=index)
        reference = f"PERF-{index:05d}"
        transactions.append(
            TransactionFact(
                id=UUID(int=index + 1),
                source_record_id=f"PERF-TX-{index:05d}",
                source_reference=reference,
                amount=amount,
                currency="AUD",
                occurred_at=occurred_at,
            )
        )
        if index < EXACT_MATCH_COUNT:
            settlements.append(
                SettlementFact(
                    id=UUID(int=TRANSACTION_COUNT + index + 1),
                    source_record_id=f"PERF-ST-{index:05d}",
                    source_reference=reference,
                    amount=amount,
                    currency="AUD",
                    settled_at=occurred_at + timedelta(hours=1),
                )
            )

    return PerformanceDataset(
        version=version,
        transactions=tuple(transactions),
        settlements=tuple(settlements),
        expected_classification_counts={
            ReconciliationClassification.EXACT_MATCH.value: EXACT_MATCH_COUNT,
            ReconciliationClassification.MISSING_SETTLEMENT.value: MISSING_SETTLEMENT_COUNT,
        },
    )


def _nearest_rank(values: list[float], percentile: int) -> float:
    if not values:
        raise ValueError("At least one measurement is required")
    ordered = sorted(values)
    rank = max(1, (percentile * len(ordered) + 99) // 100)
    return ordered[rank - 1]


def benchmark_reconciliation(*, samples: int = 5, warmups: int = 1) -> dict[str, Any]:
    """Measure the pure decision engine and assert every known outcome."""

    if samples < 1 or warmups < 0:
        raise ValueError("samples must be positive and warmups cannot be negative")
    dataset = generate_performance_dataset()
    elapsed_samples: list[float] = []
    actual_counts: dict[str, int] = {}
    for sample_index in range(warmups + samples):
        started = perf_counter()
        decisions = build_reconciliation_decisions(
            list(dataset.transactions), list(dataset.settlements), MATCH_WINDOW_HOURS
        )
        elapsed = perf_counter() - started
        actual_counts = dict(Counter(item.classification.value for item in decisions))
        if actual_counts != dataset.expected_classification_counts:
            raise RuntimeError(
                f"Outcome mismatch: expected {dataset.expected_classification_counts}, "
                f"received {actual_counts}"
            )
        if sample_index >= warmups:
            elapsed_samples.append(elapsed)

    p50 = _nearest_rank(elapsed_samples, 50)
    p95 = _nearest_rank(elapsed_samples, 95)
    return {
        "schema_version": "day-17-benchmark-v1",
        "measured_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpu_count": os.cpu_count(),
        },
        "dataset": {
            "version": dataset.version,
            "transaction_count": len(dataset.transactions),
            "settlement_count": len(dataset.settlements),
            "expected_classification_counts": dataset.expected_classification_counts,
        },
        "method": {
            "clock": "time.perf_counter",
            "warmup_count": warmups,
            "sample_count": samples,
            "match_window_hours": MATCH_WINDOW_HOURS,
            "percentile_method": "nearest-rank",
        },
        "results": {
            "latency_seconds": [round(value, 6) for value in elapsed_samples],
            "p50_latency_seconds": round(p50, 6),
            "p95_latency_seconds": round(p95, 6),
            "throughput_transactions_per_second": round(TRANSACTION_COUNT / p50, 2),
            "failure_count": 0,
            "failure_rate_percent": 0,
            "actual_classification_counts": actual_counts,
        },
    }


def write_ingestion_payload(path: Path) -> None:
    """Write the transaction half of the fixture using the public ingestion contract."""

    dataset = generate_performance_dataset()
    run_id = os.getenv("LEDGERGUARD_PERFORMANCE_RUN_ID", "LOCAL")
    if re.fullmatch(r"[A-Z0-9-]{1,32}", run_id) is None:
        raise ValueError(
            "LEDGERGUARD_PERFORMANCE_RUN_ID must use 1-32 uppercase letters, digits, or -"
        )
    payload = {
        "schema_version": "1.0",
        "source_system": "synthetic-performance",
        "source_account_id": f"PERFORMANCE-{run_id}",
        "records": [
            {
                "source_record_id": f"{run_id}-{item.source_record_id}",
                "source_reference": f"{run_id}-{item.source_reference}",
                "amount": format(item.amount, "f"),
                "currency": item.currency,
                "direction": "debit",
                "status": "posted",
                "occurred_at": item.occurred_at.isoformat().replace("+00:00", "Z"),
            }
            for item in dataset.transactions
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def seed_performance_account() -> None:
    """Create the isolated account selected by LEDGERGUARD_PERFORMANCE_RUN_ID."""

    from sqlalchemy.dialects.postgresql import insert

    from ledgerguard.config import get_settings
    from ledgerguard.db import SessionLocal
    from ledgerguard.models import Account, AccountStatus, AccountType

    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("Synthetic performance data cannot be seeded in production")
    run_id = os.getenv("LEDGERGUARD_PERFORMANCE_RUN_ID", "LOCAL")
    if re.fullmatch(r"[A-Z0-9-]{1,32}", run_id) is None:
        raise ValueError(
            "LEDGERGUARD_PERFORMANCE_RUN_ID must use 1-32 uppercase letters, digits, or -"
        )
    source_account_id = f"PERFORMANCE-{run_id}"
    with SessionLocal.begin() as session:
        session.execute(
            insert(Account)
            .values(
                source_system="synthetic-performance",
                source_account_id=source_account_id,
                display_name=f"Synthetic Performance Account {run_id}",
                account_type=AccountType.MERCHANT,
                default_currency="AUD",
                status=AccountStatus.ACTIVE,
            )
            .on_conflict_do_nothing(index_elements=["source_system", "source_account_id"])
        )
    print(f"Synthetic performance account ready: {source_account_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ingestion-payload", type=Path)
    args = parser.parse_args()

    if args.ingestion_payload is not None:
        write_ingestion_payload(args.ingestion_payload)
    result = benchmark_reconciliation(samples=args.samples, warmups=args.warmups)
    encoded = json.dumps(result, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{encoded}\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
