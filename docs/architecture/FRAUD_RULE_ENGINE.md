# Fraud Rule Engine

## Purpose and boundary

Day 10 adds a deterministic fraud-monitoring module inside the LedgerGuard modular monolith. It evaluates stored, synthetic transaction facts against immutable active rule versions and creates explainable alerts. It does not use machine learning, external enrichment, or hidden state.

## Evaluation contract

- Only `posted` transactions at or before the caller-supplied UTC cutoff are alert subjects.
- Context is limited to the same account and to facts at or before the subject transaction, preventing future-data leakage.
- Facts with equal timestamps are ordered by UUID so repeated evaluation has a stable result.
- Every active rule version is immutable. Updating a rule creates a new version; activating it retires the prior active version.
- An exact replay produces the same score, reason code, evidence document, SHA-256 digest, and deduplication key. The database uniqueness constraint prevents duplicate alerts.
- Money remains a decimal string in parameters and evidence and is evaluated with Python `Decimal`.

## Supported rules

| Rule type | Required parameters | Trigger |
| --- | --- | --- |
| `velocity` | `window_minutes`, `count_threshold` | At least the configured number of transactions for the account occur within the trailing window. |
| `unusual_amount` | `amount_threshold` | The subject amount is at least the configured threshold in its currency. |
| `repeated_failure` | `window_hours`, `count_threshold` | At least the configured number of prior or current `voided`/`reversed` facts share the subject instrument within the window. |
| `duplicate_instrument` | `window_hours`, `distinct_reference_threshold` | The subject instrument appears with at least the configured number of distinct references in the window. |
| `suspicious_timing` | `start_hour_utc`, `end_hour_utc` | The UTC occurrence hour falls in the half-open configured interval; a wrapped interval supports overnight windows. |

Rules are rejected if their parameters contain unknown keys, invalid ranges, binary floating-point numbers, or invalid decimal strings. Instrument-based rules cannot trigger when the fingerprint is absent.

## Evidence and scoring

Each alert stores the logical rule code, rule ID and version, subject identifiers, evaluated inputs, normalized parameters, matched context facts, trigger threshold, deterministic score from 0 through 100, severity snapshot, output (`triggered: true` and reason code), UTC evaluation cutoff, evidence schema version, and a canonical SHA-256 digest. The score measures threshold exceedance and is quantized to four decimal places; it is a triage signal, not a probability.

## Access control

- Administrators may read and version rules, run evaluations, and read alerts.
- Operations analysts may run evaluations and read alerts, but cannot change rules.
- Auditors may read rules and alerts, but cannot change rules or run evaluations.
- Unknown or unauthenticated roles receive no access.

The interface mirrors these controls, while the API remains authoritative.

## Failure and edge cases

- A missing or inactive account returns a stable input error without creating alerts.
- Naive timestamps are rejected; offset timestamps are normalized to UTC.
- A rule with malformed stored parameters fails closed and aborts the transaction rather than silently skipping a control.
- A concurrent replay may race at insert time; the unique deduplication key remains the final guard.
- Empty inputs and non-triggering facts return zero created alerts.

## Verification and acceptance criteria

- Unit tests cover all five positive paths, negative paths, decimal boundaries, overnight timing, deterministic replay, and parameter rejection.
- API tests prove administrator-only rule changes, analyst evaluation, auditor read-only access, and unauthenticated denial.
- PostgreSQL integration verifies version activation, alert persistence, evidence hashes, and replay idempotency.
- Synthetic seed data contains both triggering and non-triggering facts without real financial or personal data.
- Day 10 is complete only when the full backend and frontend quality suites, migration checks, structural validator, live Compose scenario, and repository safety checks pass.
