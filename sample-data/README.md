# Synthetic sample data

All files in this directory are invented for LedgerGuard demonstrations and tests. They contain no real customer, payment, account, or instrument information.

## Transaction ingestion v1.0

- [`transactions-valid-v1.json`](transactions-valid-v1.json) — two accepted JSON records.
- [`transactions-mixed-v1.json`](transactions-mixed-v1.json) — one accepted record and two rejected records with deterministic validation codes.
- [`transactions-valid-v1.csv`](transactions-valid-v1.csv) — two accepted CSV rows.
- [`transactions-mixed-v1.csv`](transactions-mixed-v1.csv) — one accepted CSV row and two rejected rows.
- [`transactions-quality-v1.json`](transactions-quality-v1.json) — one accepted row, one normalized duplicate, one conflicting source record, and one rejected row; expected acceptance rate `25.00` percent.

The authoritative field contract is [Transaction Ingestion Schema v1.0](../docs/api/TRANSACTION_INGESTION_V1.md).
