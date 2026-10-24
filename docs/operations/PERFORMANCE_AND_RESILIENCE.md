# Performance and resilience protocol

## Purpose

Day 17 measures one reproducible synthetic workload and exercises the recovery
behaviour that protects it. Results in this document are measurements from the
recorded local environment, not production capacity claims or service-level
objectives.

## Synthetic workload contract

The `performance-v1` dataset is deterministic and contains exactly 10,000
posted transactions for an isolated synthetic account:

- 8,000 transactions have one confirmed settlement with the same reference,
  currency, amount, and an eligible settlement time. Their expected outcome is
  `exact_match`.
- 2,000 transactions have no settlement. Their expected outcome is
  `missing_settlement`.
- Every identifier and reference is derived from its zero-based sequence
  number, every timestamp is UTC, and every amount is a decimal string with six
  fractional digits.
- No real names, account numbers, card details, or other personal or financial
  data are generated.

The generator must reject an unsupported dataset version or record count. A
test must prove the record count, expected outcome counts, determinism, UTC
timestamps, and decimal-safe values.

## Measurement method

The checked-in benchmark command records:

1. host platform, Docker server, Python, and logical CPU context;
2. dataset version, transaction and settlement counts, warm-up count, measured
   sample count, and UTC start time;
3. reconciliation-decision wall time and throughput in transactions per second;
4. API request latency samples with p50 and p95 calculated by nearest-rank,
   without interpolating or inventing observations;
5. worker elapsed time from durable `started_at` and `finished_at`, accepted
   record throughput, and terminal job failure rate.

Timing uses a monotonic high-resolution clock. The first algorithm run is a
warm-up and is excluded. All stored result values are written as JSON numbers
only when they are non-monetary measurements; monetary inputs remain decimal
strings. A run is invalid if the actual classification counts differ from the
dataset contract.

API and worker measurements require the local Compose platform. The pure
algorithm benchmark remains runnable without external services. Raw result JSON
is generated under `tmp/`, which is excluded from Git; this document publishes
the reviewed summary and test conditions.

## Measured bottleneck and proposed change

The baseline reconciliation candidate builder compares every transaction with
every settlement before checking reference and currency. For this workload that
means 80,000,000 candidate checks. The proposed optimization creates a local,
immutable lookup keyed by `(source_reference, currency)` and applies the same
time-window predicate only within the matching bucket.

The acceptance tests compare the optimized candidate graph against a retained
exhaustive reference implementation over a fixed randomized fixture, then run
the existing decision, ordering, evidence, and evidence-hash regression suite.
Performance results must report both the pre-change baseline and the post-change
measurement from the same host and dataset.

## Resilience drills

- **Worker restart:** queue an ingestion job while the worker is stopped, start
  a replacement worker, and require the same durable job to finish successfully.
- **Duplicate delivery:** deliver the same job identifier twice and require one
  ingestion batch and one set of accepted transaction facts.
- **Partial failure:** force a database error after writes have been flushed but
  before commit; require the transaction to roll back without partial financial
  facts or evidence.
- **Database reconnection:** restart PostgreSQL, observe readiness become
  unavailable, then require the existing API process to recover readiness and
  execute a fresh query. SQLAlchemy pool pre-ping remains enabled.

The orchestration script fails on any unmet invariant and leaves the normal
development stack running. It uses unique synthetic identifiers so reruns do
not collide and must not delete unrelated data or volumes.

## Acceptance criteria

- The deterministic generator produces at least 10,000 synthetic transactions
  with asserted known outcomes.
- Throughput, p50 latency, p95 latency, failure rate, and worker processing time
  are measured with method and environment recorded.
- Automated or scripted evidence covers worker restart, duplicate delivery,
  partial failure, and database reconnection.
- One measured bottleneck has a same-environment before/after comparison and a
  correctness-equivalence test.
- Formatting, linting, type checking, backend tests, frontend tests, production
  build, dependency/secret checks, migrations, Compose integration, and browser
  journeys pass before the day is committed.

## Results

Measured on Windows 11 build 26200 with 16 logical CPUs, Python 3.12.14, Docker Engine 29.8.2,
and the local Compose topology. The run used only synthetic data. Raw JSON was retained in the
ignored `tmp/` directory during verification and is reproducible with the documented commands.

### Reconciliation candidate optimization

The pre-change exhaustive implementation completed one `performance-v1` run in `10.515329`
seconds: `950.99` transactions/second, with 8,000 exact and 2,000 missing outcomes. On the same
host after indexing settlements by reference and currency, five measured samples after one
warm-up were `0.778196`, `0.727456`, `0.721596`, `0.819954`, and `0.829283` seconds. Nearest-rank
p50 was `0.778196` seconds, p95 was `0.829283` seconds, and p50 throughput was `12,850.23`
transactions/second. This is a measured 13.51-fold throughput improvement and 92.60% p50 elapsed
time reduction for this deliberately unique-reference workload; it is not a production capacity
claim.

The optimized graph matched the exhaustive candidate graph over the fixed randomized equivalence
fixture, while the complete reconciliation regression suite retained classification, ordering,
money, evidence, boundary-window, and evidence-hash behaviour.

### Live API and worker measurement

Run `D17-20261024185214` used a 2,209,010-byte JSON request containing 10,000 records. Twenty
idempotent submissions while the worker was stopped returned one durable job with 0 request
failures: nearest-rank API p50 was `2,193.137` ms and p95 was `2,299.534` ms. After starting the
worker, that original job succeeded in one attempt in `10.223361` seconds, or `978.15` accepted
transactions/second. PostgreSQL independently confirmed source/accepted/rejected/duplicate/
conflict counts of `10000/10000/0/0/0`; the worker failure rate was 0% for the one measured bulk
job. The small sample size is reported explicitly and does not establish an SLO.

### Resilience outcomes

- The queued bulk job completed after the worker container was stopped and restarted; 20
  idempotent deliveries retained one durable job and one ingestion batch.
- The real-database duplicate-delivery integration test processed the same job identifier twice
  and retained one batch and one financial fact.
- The injected post-flush, pre-commit SQLAlchemy failure left zero batches and zero transaction
  facts for its isolated account.
- Readiness reported unavailable while PostgreSQL was stopped. After PostgreSQL restarted, the
  same API process recovered readiness and successfully read the completed job; all seven
  long-running services finished healthy or running.
