# Domain and Data Model

## Purpose

This document is the implementation contract for LedgerGuard's PostgreSQL schema. It supports the complete path from an authenticated user and source row through validation, immutable financial facts, reconciliation evidence, fraud evaluation, investigation, reporting, and audit review. SQLAlchemy models and versioned Alembic migrations implement this contract.

Related decisions: [ADR-0001: decimal money](../decisions/0001-decimal-money.md), [ADR-0002: identifiers](../decisions/0002-identifiers.md), and [ADR-0003: audit history](../decisions/0003-append-only-audit-history.md).

## Global conventions and invariants

- Table and column names use `snake_case`; enum values use stable lowercase strings.
- Domain primary keys are application-generated UUIDv4 values stored as PostgreSQL `UUID`, never user-supplied sequential identifiers.
- All persisted times use `TIMESTAMPTZ`, are normalised to UTC, and are named `*_at`. Business occurrence time is distinct from ingestion and processing time.
- Money uses `NUMERIC(20,6)`. Transaction and settlement amounts are strictly positive; economic direction is stored separately. Different currencies are never added or compared as equivalent.
- Currency is an uppercase three-character ISO 4217 code validated against an application allowlist and constrained to `[A-Z]{3}` in the database.
- Mutable aggregate roots carry `version INTEGER NOT NULL DEFAULT 1` for optimistic concurrency.
- Evidence-bearing facts are not overwritten. Corrections create a new source record, rule version, result, history row, or audit event.
- External source identifiers are unique within their documented source/account boundary, not assumed globally unique.
- JSONB is used only for versioned source/evidence snapshots whose keys are validated by application schemas. Searchable business fields remain typed columns.
- Every external request and background job carries a UUID `correlation_id`; each durable job uses its UUID as the Celery task ID.
- Foreign keys default to `RESTRICT`. Destructive cascades are prohibited for financial facts, evidence, cases, and audit history.
- Application writes that change multiple related records use one PostgreSQL transaction.

## Logical modules

| Module | Tables |
| --- | --- |
| Identity and access | `users`, `roles`, `user_roles`, `auth_sessions` |
| Source accounts and ingestion | `accounts`, `ingestion_batches`, `ingestion_records` |
| Financial facts | `transactions`, `settlements` |
| Reconciliation | `reconciliation_runs`, `reconciliation_results`, `reconciliation_result_transactions`, `reconciliation_result_settlements` |
| Background processing | `background_jobs` |
| Fraud monitoring | `fraud_rules`, `fraud_rule_versions`, `alerts` |
| Investigations | `cases`, `case_alerts`, `case_comments`, `case_status_history` |
| Audit | `audit_events` |

## Entity definitions

### `users`

Represents an authenticated human user. Demonstration users must use synthetic identities.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `UUID` | Primary key, UUIDv4 |
| `email` | `CITEXT` | Required, unique, normalised, maximum 320 characters |
| `display_name` | `VARCHAR(120)` | Required |
| `password_hash` | `TEXT` | Required for local authentication; never exposed or audited as a value |
| `status` | `user_status` | `active`, `disabled`, or `locked` |
| `failed_login_count` | `INTEGER` | Non-negative, default 0 |
| `locked_until` | `TIMESTAMPTZ` | Nullable; UTC |
| `last_login_at` | `TIMESTAMPTZ` | Nullable; UTC |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Required; UTC |
| `version` | `INTEGER` | Required, positive; optimistic concurrency |

`email` identifies a login but is not used as a foreign key. Disabling a user retains attribution history.

### `roles` and `user_roles`

`roles` is reference data keyed by `code VARCHAR(32)`: `administrator`, `operations_analyst`, and `auditor`. It also stores a human-readable description and `created_at`.

`user_roles` records grants instead of placing a single mutable role on `users`:

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `UUID` | Primary key |
| `user_id` | `UUID` | Required FK to `users` |
| `role_code` | `VARCHAR(32)` | Required FK to `roles.code` |
| `granted_by_user_id` | `UUID` | Required FK to `users` |
| `granted_at` | `TIMESTAMPTZ` | Required; UTC |
| `revoked_by_user_id` | `UUID` | Nullable FK to `users` |
| `revoked_at` | `TIMESTAMPTZ` | Nullable; both revoke fields are null or both populated |

A partial unique index on `(user_id, role_code) WHERE revoked_at IS NULL` prevents duplicate active grants. At least one administrator must remain active; this cross-row invariant is enforced in the administrative service transaction and tested.

### `auth_sessions`

Stores revocable server-side sessions. The raw high-entropy bearer token is returned once and is never persisted; only its keyed SHA-256 digest is stored.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `UUID` | Primary key, UUIDv4 |
| `user_id` | `UUID` | Required FK to `users`; cascades only when a user is physically removed |
| `token_digest` | `VARCHAR(64)` | Required, unique keyed digest; never the bearer token |
| `created_at` | `TIMESTAMPTZ` | Required; UTC |
| `expires_at` | `TIMESTAMPTZ` | Required; strictly after creation |
| `revoked_at` | `TIMESTAMPTZ` | Nullable; when set, not before creation |

Authentication requires an unrevoked, unexpired session and an active user. Logout sets `revoked_at`; disabled or locked users fail closed even when a previously issued token has not expired.

### `accounts`

Represents a synthetic financial/source account whose transactions and settlements are reconciled. It is not a login account.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `UUID` | Primary key |
| `source_system` | `VARCHAR(80)` | Required |
| `source_account_id` | `VARCHAR(160)` | Required; unique with `source_system` |
| `display_name` | `VARCHAR(160)` | Required; synthetic label only |
| `account_type` | `account_type` | `merchant`, `clearing`, or `internal` |
| `default_currency` | `CHAR(3)` | Nullable; uppercase valid currency |
| `status` | `account_status` | `active` or `inactive` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Required; UTC |
| `version` | `INTEGER` | Required, positive |

Inactive accounts remain readable and retain all facts but reject new ingestion unless explicitly reactivated.

### `ingestion_batches`

Represents one CSV upload or JSON submission and is the boundary for request idempotency and quality reporting.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `UUID` | Primary key |
| `record_kind` | `ingestion_record_kind` | `transaction` or `settlement` |
| `source_system` | `VARCHAR(80)` | Required |
| `schema_version` | `VARCHAR(32)` | Required |
| `idempotency_key` | `VARCHAR(255)` | Required; unique with `source_system` |
| `payload_sha256` | `CHAR(64)` | Required lowercase hexadecimal digest |
| `original_filename` | `VARCHAR(255)` | Nullable, basename only, never trusted as a path |
| `status` | `ingestion_batch_status` | Lifecycle below |
| `source_count` | `INTEGER` | Nullable until parsed; non-negative |
| `accepted_count`, `rejected_count`, `duplicate_count`, `conflict_count` | `INTEGER` | Required, non-negative, default 0 |
| `requested_by_user_id` | `UUID` | Required FK to `users` |
| `correlation_id` | `UUID` | Required |
| `failure_code`, `failure_detail` | `VARCHAR(80)`, `TEXT` | Nullable; detail is redacted and size-limited |
| `created_at`, `started_at`, `finished_at` | `TIMESTAMPTZ` | UTC; processing times nullable |
| `version` | `INTEGER` | Required, positive |

For `completed` and `completed_with_errors`, PostgreSQL requires `source_count` to equal accepted + rejected + duplicate + conflict. Idempotency keys are non-blank and capped at 200 characters by both API and database checks. Reusing a `(source_system, idempotency_key)` with the same canonical payload hash returns the stored result; using it with another hash is a conflict, not a retry.

### `ingestion_records`

Preserves the per-row validation decision, including rejected data, without requiring invalid rows to become financial facts.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `UUID` | Primary key |
| `batch_id` | `UUID` | Required FK to `ingestion_batches` |
| `row_number` | `INTEGER` | Required, positive, unique within batch |
| `source_record_id` | `VARCHAR(200)` | Nullable only when absent/invalid |
| `payload` | `JSONB` | Required schema-versioned synthetic source snapshot |
| `payload_sha256` | `CHAR(64)` | Required |
| `outcome` | `ingestion_record_outcome` | `accepted`, `rejected`, `duplicate`, or `conflict` |
| `reason_codes` | `JSONB` | Required array; empty only for accepted rows |
| `rejection_details` | `JSONB` | Required array of stable field/code/message objects; empty for accepted rows |
| `transaction_id` | `UUID` | Nullable unique FK to `transactions` |
| `settlement_id` | `UUID` | Nullable unique FK to `settlements` |
| `processed_at` | `TIMESTAMPTZ` | Required; UTC |

An accepted record links to exactly one fact matching the batch kind. A rejected, duplicate, or conflicting record links to no new fact. `reason_codes` supports stable aggregation, while `rejection_details` identifies each invalid field without echoing sensitive input into error messages. This conditional invariant is enforced in the ingestion transaction and tested; a deferred constraint trigger may reinforce it if ordinary checks cannot span the foreign rows cleanly.

### `transactions`

Stores an accepted transaction fact. A reversal is a new transaction linked to its original rather than destructive mutation.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `UUID` | Primary key |
| `account_id` | `UUID` | Required FK to `accounts` |
| `batch_id` | `UUID` | Required FK to `ingestion_batches` |
| `source_record_id` | `VARCHAR(200)` | Required; unique with `account_id` |
| `source_reference` | `VARCHAR(200)` | Required |
| `amount` | `NUMERIC(20,6)` | Required, greater than 0 |
| `currency` | `CHAR(3)` | Required, uppercase valid currency |
| `direction` | `money_direction` | `debit` or `credit` |
| `status` | `transaction_status` | `pending`, `posted`, `voided`, or `reversed` |
| `reversal_of_transaction_id` | `UUID` | Nullable FK to `transactions`; not self; same account/currency checked by service |
| `instrument_fingerprint` | `CHAR(64)` | Nullable one-way synthetic/demo fingerprint; never raw instrument data |
| `occurred_at` | `TIMESTAMPTZ` | Required business time in UTC |
| `created_at` | `TIMESTAMPTZ` | Required ingestion time in UTC |

Only `posted` and eligible reversing entries participate in reconciliation. Amount and currency are immutable after insertion.

### `settlements`

Stores an accepted settlement fact received from a settlement source.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `UUID` | Primary key |
| `account_id` | `UUID` | Required FK to `accounts` |
| `batch_id` | `UUID` | Required FK to `ingestion_batches` |
| `source_record_id` | `VARCHAR(200)` | Required; unique with `account_id` |
| `source_reference` | `VARCHAR(200)` | Required |
| `provider` | `VARCHAR(120)` | Required |
| `amount` | `NUMERIC(20,6)` | Required, greater than 0 |
| `currency` | `CHAR(3)` | Required, uppercase valid currency |
| `status` | `settlement_status` | `received`, `confirmed`, `voided`, or `reversed` |
| `settled_at` | `TIMESTAMPTZ` | Required business time in UTC |
| `created_at` | `TIMESTAMPTZ` | Required ingestion time in UTC |

Settlement amount/currency are immutable. Corrections arrive as new facts or explicit reversals.

### `reconciliation_runs`

Defines a reproducible reconciliation execution.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `UUID` | Primary key |
| `account_id` | `UUID` | Required FK to `accounts` |
| `algorithm_version` | `VARCHAR(40)` | Required |
| `configuration` | `JSONB` | Required validated snapshot, including UTC match window |
| `input_cutoff_at` | `TIMESTAMPTZ` | Required; freezes eligible input set |
| `replay_key` | `CHAR(64)` | Required unique hash of account, version, configuration, input cutoff, and sorted immutable inputs |
| `status` | `reconciliation_run_status` | Lifecycle below |
| `requested_by_user_id` | `UUID` | Required FK to `users` |
| `correlation_id` | `UUID` | Required |
| `failure_code`, `failure_detail` | `VARCHAR(80)`, `TEXT` | Nullable redacted failure evidence |
| `created_at`, `started_at`, `finished_at` | `TIMESTAMPTZ` | UTC |
| `version` | `INTEGER` | Required, positive |

The unique replay key makes duplicate delivery return the existing run. A per-account row lock serializes input selection and persistence. Completed results never change when configuration or the eligible input set changes; a new run is created.

### `background_jobs`

Owns the durable state for asynchronous ingestion and reconciliation. Redis transports task
identifiers but is not the source of truth.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `UUID` | Primary key and Celery task ID |
| `kind` | `VARCHAR(23)` | `transaction_ingestion` or `reconciliation` |
| `status` | `VARCHAR(9)` | `queued`, `running`, `succeeded`, `failed`, or `cancelled` |
| `deduplication_key` | `CHAR(64)` | Required unique canonical scope hash |
| `request_sha256` | `CHAR(64)` | Required canonical request hash |
| `payload` | `JSONB` | Validated work envelope; cleared at terminal state |
| `requested_by_user_id` | `UUID` | Required FK to `users` |
| `correlation_id` | `UUID` | Required |
| `celery_task_id` | `VARCHAR(80)` | Required unique delivery identifier |
| `progress_current`, `progress_total` | `INTEGER` | Non-negative and bounded by total |
| `attempt_count`, `max_attempts` | `INTEGER` | Non-negative attempts; maximum from 1 through 10 |
| `status_message` | `VARCHAR(200)` | Nullable safe operational summary |
| `failure_code`, `failure_detail` | `VARCHAR(80)`, `VARCHAR(500)` | Nullable sanitized failure evidence |
| `cancellation_requested_at`, `started_at`, `finished_at` | `TIMESTAMPTZ` | Nullable UTC lifecycle evidence |
| `ingestion_batch_id` | `UUID` | Nullable FK to one ingestion result |
| `reconciliation_run_id` | `UUID` | Nullable FK to one reconciliation result |
| `created_at` | `TIMESTAMPTZ` | Required UTC creation time |
| `version` | `INTEGER` | Required, positive |

At most one result link may be present. Every terminal state requires `finished_at`. Row locking
serializes claim and cancellation decisions. Terminal deliveries are no-ops; a running redelivery
may resume the retained payload without increasing the logical attempt count, relying on the
domain's account locks and idempotency guards for concurrent duplicate safety.

### `reconciliation_results` and item tables

Each result is one explainable matching group. Separate item tables support one-to-one, one-to-many, many-to-one, missing, unexplained, and duplicate-candidate outcomes without polymorphic foreign keys.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `UUID` | Primary key |
| `run_id` | `UUID` | Required FK to `reconciliation_runs` |
| `classification` | `reconciliation_classification` | `exact_match`, `partial_match`, `missing_settlement`, `duplicate_candidate`, or `unexplained_settlement` |
| `reason_code` | `VARCHAR(80)` | Required stable code |
| `currency` | `CHAR(3)` | Required |
| `transaction_total`, `settlement_total` | `NUMERIC(20,6)` | Required, non-negative |
| `difference_amount` | `NUMERIC(20,6)` | Required; settlement total minus transaction total |
| `evidence` | `JSONB` | Required versioned comparisons and candidate rationale |
| `evidence_sha256` | `CHAR(64)` | Required digest over canonical evidence |
| `review_status` | `reconciliation_review_status` | `open`, `acknowledged`, or `resolved` |
| `created_at`, `reviewed_at` | `TIMESTAMPTZ` | UTC; review time nullable |
| `reviewed_by_user_id` | `UUID` | Nullable FK to `users`; paired with review time |
| `version` | `INTEGER` | Required, positive |

The database requires `difference_amount = settlement_total - transaction_total` and unique `(run_id, evidence_sha256)` values. `reconciliation_result_transactions` has composite PK `(result_id, transaction_id)` plus `item_role` (`matched` or `candidate`) and nullable positive `allocated_amount`. `reconciliation_result_settlements` mirrors it with `settlement_id`. All matched items share the result currency. A result must contain the entity sides required by its classification; the reconciliation service enforces this atomically and tests every shape.

### `fraud_rules` and `fraud_rule_versions`

`fraud_rules` is the stable named rule identity: UUID `id`, unique `code VARCHAR(80)`, `name`, optional `description`, `created_by_user_id`, `created_at`, and optimistic `version`.

Each immutable `fraud_rule_versions` row contains:

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `UUID` | Primary key |
| `rule_id` | `UUID` | Required FK to `fraud_rules` |
| `version_number` | `INTEGER` | Required positive; unique with `rule_id` |
| `rule_type` | `fraud_rule_type` | `velocity`, `unusual_amount`, `repeated_failure`, `duplicate_instrument`, or `suspicious_timing` |
| `parameters` | `JSONB` | Required, validated per type |
| `severity` | `alert_severity` | `low`, `medium`, `high`, or `critical` |
| `status` | `rule_version_status` | `draft`, `active`, or `retired` |
| `created_by_user_id`, `activated_by_user_id` | `UUID` | Required creator; activator nullable |
| `created_at`, `activated_at`, `retired_at` | `TIMESTAMPTZ` | UTC, lifecycle-dependent |

Activated versions are immutable. A partial unique index permits only one active version per rule.

### `alerts`

Stores one deterministic rule evaluation that produced an alert.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `UUID` | Primary key |
| `rule_version_id` | `UUID` | Required FK to `fraud_rule_versions` |
| `transaction_id` | `UUID` | Nullable FK to `transactions` |
| `reconciliation_result_id` | `UUID` | Nullable FK to `reconciliation_results` |
| `deduplication_key` | `CHAR(64)` | Required unique fingerprint of rule version and evidence scope |
| `severity` | `alert_severity` | Required snapshot from rule version |
| `score` | `NUMERIC(7,4)` | Nullable, constrained from 0 through 100 |
| `status` | `alert_status` | `open`, `in_review`, `closed`, or `dismissed` |
| `reason_code` | `VARCHAR(80)` | Required |
| `evidence` | `JSONB` | Required exact evaluated inputs and outputs |
| `evidence_sha256` | `CHAR(64)` | Required |
| `correlation_id` | `UUID` | Required |
| `created_at`, `closed_at` | `TIMESTAMPTZ` | UTC; close time nullable |
| `closed_by_user_id` | `UUID` | Nullable FK to `users`; paired with close time |
| `version` | `INTEGER` | Required, positive |

At least one of transaction or reconciliation result is required. Alert status is not a finding of fraud; closure/dismissal requires a case disposition or documented reason.

### `cases`, `case_alerts`, `case_comments`, and `case_status_history`

`cases` is the investigation aggregate root:

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `UUID` | Primary key |
| `case_number` | `BIGINT GENERATED ALWAYS AS IDENTITY` | Unique human-facing sequence; not an external security identifier |
| `title` | `VARCHAR(200)` | Required; synthetic content only |
| `description` | `TEXT` | Nullable, size-limited |
| `status` | `case_status` | `open`, `in_review`, `escalated`, `resolved`, or `reopened` |
| `priority` | `case_priority` | `low`, `medium`, `high`, or `critical` |
| `owner_user_id` | `UUID` | Nullable FK to `users`; only active analysts/admins may own |
| `resolution_code`, `resolution_summary` | `VARCHAR(80)`, `TEXT` | Required only when resolved; summary size-limited |
| `created_by_user_id` | `UUID` | Required FK to `users` |
| `created_at`, `updated_at`, `resolved_at` | `TIMESTAMPTZ` | UTC |
| `version` | `INTEGER` | Required, positive |

`case_alerts` has composite PK `(case_id, alert_id)`, plus `linked_by_user_id` and `linked_at`. An alert may be linked to more than one case only with an explicit audited justification; the normal workflow prevents it through a unique active-case policy.

`case_comments` contains UUID `id`, required `case_id`, `author_user_id`, size-limited `body`, and `created_at`. Comments are append-only through the application; corrections are new comments.

`case_status_history` contains UUID `id`, required `case_id`, `from_status` (nullable only at creation), `to_status`, `reason`, `changed_by_user_id`, `correlation_id`, and `changed_at`. A unique `(case_id, changed_at, id)` index gives stable timeline ordering.

### `audit_events`

Provides the security and business decision trail described in ADR-0003.

| Column | Type | Rules |
| --- | --- | --- |
| `sequence_number` | `BIGINT GENERATED ALWAYS AS IDENTITY` | Primary key, stable database order |
| `id` | `UUID` | Required unique public event identifier |
| `occurred_at` | `TIMESTAMPTZ` | Required UTC event time, default database clock |
| `actor_user_id` | `UUID` | Nullable FK to `users` for system/unknown actors |
| `actor_type` | `audit_actor_type` | `user`, `system`, or `anonymous` |
| `action` | `VARCHAR(100)` | Required stable action name |
| `target_type` | `VARCHAR(80)` | Required |
| `target_id` | `UUID` | Nullable when no persisted target exists |
| `result` | `audit_result` | `success`, `denied`, or `failure` |
| `correlation_id` | `UUID` | Required |
| `request_id`, `job_id` | `UUID` | Nullable origin identifiers |
| `before_state`, `after_state` | `JSONB` | Nullable allowlisted/redacted snapshots |
| `metadata` | `JSONB` | Required validated, redacted context |

The application role has `SELECT` and `INSERT` only. Updates and deletes are rejected by a database trigger. Password hashes, tokens, raw credentials, and unrestricted payloads are forbidden in audit JSON.

## Lifecycle definitions

| Aggregate | Allowed transitions |
| --- | --- |
| User | `active -> locked`, `locked -> active`, `active/locked -> disabled`, `disabled -> active` by administrator |
| Ingestion batch | `received -> queued -> processing -> completed/completed_with_errors/failed`; `received/queued -> cancelled`; terminal states do not transition |
| Transaction | `pending -> posted/voided`; `posted -> reversed`; correction uses a linked reversal fact |
| Settlement | `received -> confirmed/voided`; `confirmed -> reversed`; correction uses a new fact |
| Reconciliation run | `pending -> queued -> running -> completed/failed`; `pending/queued -> cancelled`; terminal states do not transition |
| Reconciliation review | `open -> acknowledged -> resolved`; a new run supersedes, rather than mutates, classification evidence |
| Rule version | `draft -> active -> retired`; activation retires the prior active version in one transaction |
| Alert | `open -> in_review -> closed/dismissed`; terminal reopening creates an audited transition back to `in_review` only through case workflow |
| Case | `open -> in_review/escalated/resolved`; `in_review -> escalated/resolved`; `escalated -> in_review/resolved`; `resolved -> reopened -> in_review` |
| Audit event | No transitions; append only |

Every rejected transition returns a stable conflict/error code and produces an audit event where security or evidence integrity is relevant.

## Index and query plan

| Table | Indexes beyond primary/unique constraints | Intended query |
| --- | --- | --- |
| `users` | `(status)`, lower/CI unique email | Login and administration filters |
| `user_roles` | `(user_id) WHERE revoked_at IS NULL`, `(role_code) WHERE revoked_at IS NULL` | Authorization checks and role membership |
| `accounts` | `(status)`, unique `(source_system, source_account_id)` | Active source selection and deduplication |
| `ingestion_batches` | `(status, created_at DESC)`, `(requested_by_user_id, created_at DESC)`, unique `(source_system, idempotency_key)` | Queue/dashboard and idempotency |
| `ingestion_records` | `(batch_id, outcome)`, `(source_record_id)`, GIN on `reason_codes` only if measured need | Batch-quality drill-down |
| `transactions` | `(account_id, occurred_at DESC)`, `(account_id, source_reference, currency, amount, occurred_at)`, `(instrument_fingerprint, occurred_at)` where non-null | Reconciliation candidates and fraud windows |
| `settlements` | `(account_id, settled_at DESC)`, `(account_id, source_reference, currency, amount, settled_at)` | Reconciliation candidates |
| `reconciliation_runs` | `(account_id, created_at DESC)`, `(status, created_at)`, unique `replay_key` | Run history, queue, duplicate delivery |
| `reconciliation_results` | `(run_id, classification)`, `(review_status, created_at)`, `(classification, ABS(difference_amount) DESC)` | Summary and discrepancy priority |
| Result item tables | Reverse index on the fact ID | Fact-to-result traceability |
| `fraud_rule_versions` | unique `(rule_id, version_number)`, unique `(rule_id) WHERE status='active'` | Active version lookup and replay |
| `alerts` | `(status, severity, created_at)`, `(rule_version_id, created_at)`, unique `deduplication_key` | Triage and idempotency |
| `cases` | `(status, priority, updated_at)`, `(owner_user_id, status, updated_at)`, `(resolved_at)` | Analyst work queues and age filters |
| `case_alerts` | `(alert_id)`, `(case_id, linked_at)` | Bidirectional investigation trace |
| `case_comments` | `(case_id, created_at, id)` | Stable comment timeline |
| `case_status_history` | `(case_id, changed_at, id)` | Stable state timeline |
| `audit_events` | `(target_type, target_id, sequence_number)`, `(actor_user_id, sequence_number)`, `(correlation_id, sequence_number)`, `(occurred_at)` | Decision reconstruction and time retention |

Large time-ordered tables (`audit_events`, and later possibly transactions/settlements) may be range-partitioned only after Day 17 measurements justify it. Premature partitioning is avoided.

## Retention assumptions

These are design assumptions for a synthetic portfolio system, not claims of regulatory compliance. Day 16 will threat-model and ratify them before any deletion automation is implemented.

| Data | Assumed minimum | Behaviour |
| --- | ---: | --- |
| Transactions, settlements, reconciliation runs/results | 7 years | Retain evidence together; no application delete endpoint |
| Alerts, cases, comments, case history | 7 years after case resolution | Legal-hold capability must override expiry |
| Audit events | 7 years | Append-only to application; privileged retention job only after policy approval |
| Accepted source snapshots | 1 year after batch completion | Typed financial facts/evidence remain for 7 years |
| Rejected source snapshots | 90 days | Keep reason codes/counts longer; delete payload only through audited privileged job |
| Authentication/security events | 1 year | Security review may extend |
| Generated exports | 30 days maximum | Prefer on-demand generation; audit metadata outlives file |
| Application logs/traces | 30 days | Redacted and separated from authoritative audit history |

No automated purge is added before policy, legal-hold, referential-integrity, and evidence-preservation tests exist.

## Transaction-to-case evidence chain

1. `ingestion_batches` and `ingestion_records` prove what was submitted and why each row was accepted or rejected.
2. An accepted record links to one immutable `transaction` or `settlement` fact.
3. A `reconciliation_run` freezes algorithm/configuration/input cutoff; results and item tables link every candidate and comparison.
4. A versioned fraud rule evaluates typed facts/results and records exact alert evidence and a deduplication key.
5. `case_alerts`, comments, and status history preserve the analyst investigation and disposition.
6. `audit_events` tie user/system actions together using target and correlation identifiers.

This chain is traversable in both directions without relying on log text or mutable display names.

## Deferred implementation details

- Exact SQL enum versus checked text representation will be selected during the Day 3 migration; stable values above are normative either way.
- Currency allowlist updates and currency-specific scale validation belong to versioned application reference data; the database still constrains the basic shape.
- Cross-row invariants that are awkward as ordinary constraints will first be protected by service transactions and concurrency tests, then reinforced with deferred triggers only where the operational value exceeds complexity.
- Tenant identifiers are intentionally absent because version 1 is single-organisation. Multi-tenancy requires a separate threat model and migration, not an implicit nullable column.
