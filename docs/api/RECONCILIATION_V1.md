# Reconciliation API and Algorithm v1

## Purpose

Day 7 adds a deterministic reconciliation engine that compares immutable posted transactions
with immutable confirmed settlements for one synthetic account. Every outcome stores the facts,
comparison criteria, reason code, algorithm version, configuration, and a canonical evidence
hash needed to reproduce the decision.

Day 9 runs this matching contract behind a durable Celery job. PostgreSQL remains authoritative
for job and reconciliation evidence; Redis transports the job identifier.
While `SYNTHETIC_DATA_ONLY=true`, `source_system` must begin with `synthetic-`.

## API contract

`POST /api/v1/reconciliation/runs` requires `reconciliation:write`, an `Idempotency-Key` header,
and accepts:

```json
{
  "source_system": "synthetic-reconciliation",
  "source_account_id": "DEMO-RECON-001",
  "input_cutoff_at": "2026-10-14T12:00:00Z",
  "match_window_hours": 72
}
```

- `input_cutoff_at` must contain a UTC offset and is normalized to UTC.
- `match_window_hours` is an integer from 1 through 168 and defaults to 72.
- Only transactions with status `posted` and `occurred_at <= input_cutoff_at` are eligible.
- Only settlements with status `confirmed` and `settled_at <= input_cutoff_at` are eligible.
- A settlement is a candidate for a transaction only when reference and currency are equal and
  its UTC timestamp is from zero through `match_window_hours` after the transaction timestamp.
- A newly committed job returns HTTP 202. Repeating the same key and request returns the original
  job with HTTP 200 and `replayed: true`; changed content under that key returns HTTP 409.
- `GET /api/v1/jobs/{job_id}` exposes bounded progress, attempts, sanitized failures, cancellation
  state, and the terminal `reconciliation_run_id` used to retrieve evidence.

`GET /api/v1/reconciliation/runs/{run_id}` requires `reconciliation:read`. Administrators and
operations analysts can create runs. Administrators, operations analysts, and auditors can read
stored run evidence and reconciliation job status. Auditors cannot submit or cancel jobs.

## Deterministic classification

Candidate edges form deterministic connected components, ordered by fact type and UUID. Each
eligible fact belongs to exactly one result in a run.

| Classification | Rule | Reason code |
| --- | --- | --- |
| `exact_match` | One transaction and one settlement have equal decimal amounts | `EXACT_REFERENCE_AMOUNT_CURRENCY_TIME` |
| `partial_match` | Both sides have candidates, but amounts differ or the component is an unambiguous aggregate | `PARTIAL_AMOUNT_MISMATCH` or `PARTIAL_GROUP_MATCH` |
| `missing_settlement` | A transaction has no eligible settlement | `NO_ELIGIBLE_SETTLEMENT` |
| `duplicate_candidate` | A fact has multiple equal-amount candidates | `DUPLICATE_EXACT_CANDIDATES` |
| `unexplained_settlement` | A settlement has no eligible transaction | `NO_ELIGIBLE_TRANSACTION` |

Money is compared and totalled only with `Decimal`. Different currencies never match or combine.
The stored difference is always `settlement_total - transaction_total`.

## Evidence contract

Every result stores:

- algorithm version and reason code;
- UTC window boundaries and the configured window size;
- transaction and settlement IDs, source IDs, references, decimal-string amounts, currencies,
  and UTC timestamps;
- every candidate comparison and its reference, currency, time-window, and amount predicates;
- exact transaction, settlement, and difference totals;
- canonical SHA-256 evidence digest.

`matched` item roles mean definitive membership in an outcome, including missing or unexplained
outcomes. `candidate` roles are reserved for ambiguous duplicate candidates. Allocation is set
only for a one-to-one exact match in v1.

## Idempotency and atomicity

The job deduplication key is scoped to reconciliation, source system, and caller-supplied
idempotency key. The domain replay key is SHA-256 over the algorithm version, account ID, normalized cutoff,
configuration, and the complete sorted immutable input set. The account row is locked while the
run is created. A unique replay key is the final duplicate-delivery guard. The run, results, and
item evidence commit atomically; failures roll back the complete unit.

## Edge cases and tests

- Boundary timestamps at exactly zero and exactly the configured maximum are eligible.
- Earlier settlements, later settlements, currency mismatches, and reference mismatches are not
  candidates.
- Pending/voided/reversed transactions and received/voided/reversed settlements are excluded.
- Equal source data inserted in a different input order produces byte-identical decisions and
  evidence hashes.
- Seeded data covers exact, partial, missing, duplicate-candidate, and unexplained outcomes.
- Permission tests cover analyst creation, auditor read access, and auditor write denial.
- Replay tests prove that repeated execution does not create duplicate results.

## Completion criteria

Day 7 is complete when all five classifications are produced from the published synthetic
scenario, every result has verifiable evidence, a repeated run reuses the stored outcome, API and
database permission/invariant paths pass, and the full repository quality suite remains green.
