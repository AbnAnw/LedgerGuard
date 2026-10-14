# Background Processing Contract

## Scope

Day 9 moves transaction-row validation, CSV parsing, and reconciliation execution out of web
requests and into Celery workers. PostgreSQL remains the authoritative state store; Redis carries
task delivery and short-lived Celery metadata only. The API validates request envelopes, reserves
an idempotent job, publishes its identifier, and returns HTTP 202 without waiting for financial
processing.

## Durable job model

Every background request creates one `background_jobs` row with:

- kind: `transaction_ingestion` or `reconciliation`;
- state: `queued`, `running`, `succeeded`, `failed`, or `cancelled`;
- a unique deduplication key and canonical request SHA-256 digest;
- caller, correlation ID, Celery task ID, attempt count, and UTC lifecycle timestamps;
- bounded progress (`current <= total`), sanitized failure code/detail, and result links;
- the validated work envelope needed by the worker.

The payload is cleared after a terminal outcome. Financial records, ingestion evidence, and
reconciliation evidence remain in their dedicated tables.

## Submission and idempotency

- Existing JSON and CSV ingestion routes now return a job receipt with HTTP 202.
- Reconciliation submission requires `Idempotency-Key` and returns the same job for an exact retry.
- Ingestion retains its existing `(source_system, Idempotency-Key)` scope.
- Reusing a key with a different canonical request returns HTTP 409.
- The job UUID is also the Celery task ID. Duplicate broker delivery therefore targets the same
  durable row. Terminal delivery is a no-op; a running redelivery may resume the retained payload
  without increasing the logical attempt count. Account locks and domain idempotency serialize a
  concurrent duplicate and prevent duplicate financial evidence.
- Existing ingestion uniqueness and reconciliation replay keys remain the final financial guards.

## State transitions

```text
queued ──> running ──> succeeded
   │           └─────> failed
   └────────────────> cancelled
```

Queued cancellation is guaranteed before financial processing. Running cancellation is
cooperative: the worker checks the cancellation flag before parsing and before starting the
financial transaction. It never terminates a process mid-database-commit. A cancellation arriving
after the financial commit cannot rewrite a successful outcome.

## Retries, timeouts, and failures

- Tasks use late acknowledgement, reject-on-worker-loss, and a worker prefetch multiplier of one.
- Retryable database/transport failures retry with bounded backoff, reusing the same job.
- Soft and hard time limits are configurable and validated; timeout becomes `JOB_TIMEOUT`.
- Validation and product errors fail deterministically without retry.
- API responses and logs expose stable codes and sanitized summaries, never raw exception text or
  request payloads.
- A failed task retains its attempt count and failure evidence. A successful duplicate delivery is
  a no-op and returns the stored result link. Redelivery after worker loss can resume a running job
  from its durable payload.

## Access control

- Administrators may read and cancel all jobs.
- Operations analysts may read and cancel their ingestion/reconciliation jobs.
- Auditors may read reconciliation jobs but cannot submit or cancel them.
- Backend checks are authoritative; interface visibility is not an access-control boundary.

## Health and operations

The Compose worker health check uses a targeted Celery ping. PostgreSQL and Redis health remain
independent. Operational commands document queue inspection, worker ping, and graceful restart.
The worker uses UTC and JSON-only task serialization.

## Test contract

Day 9 verification covers:

- HTTP 202 submission without inline processing;
- exact retry and changed-payload conflict;
- queued, running, success, failure, retry, and cancellation transitions;
- duplicate task delivery creating no duplicate financial facts;
- role boundaries for reads and cancellation;
- 10,000 synthetic transactions accepted by the queue while the web request returns before worker
  completion;
- PostgreSQL-backed result persistence, Redis/Celery delivery, worker health, and restart-safe
  redelivery in the local integration stack.

Day 9 is complete when large synthetic input is processed by the worker without tying up the web
request and every terminal outcome is explainable through the durable job record.
