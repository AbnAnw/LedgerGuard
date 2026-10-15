# LedgerGuard Project Plan

## Status legend

- **Not started:** no roadmap work has begun.
- **In progress:** implementation has begun but one or more completion gates remain.
- **Complete:** implementation, relevant tests, documentation, completion criteria, and the daily local commit are complete.

Only one roadmap day advances per user command of `Next`. Day statuses are updated in the same daily commit. Day 1 is recorded as complete in this initial commit.

## Roadmap status

| Day | Theme | Status |
| ---: | --- | --- |
| Day 1 | Product definition and repository creation | **Complete** |
| Day 2 | Domain and data model | **Complete** |
| Day 3 | Local platform foundation | **Complete** |
| Day 4 | Authentication and role-based access | **Complete** |
| Day 5 | Transaction ingestion | **Complete** |
| Day 6 | Idempotency and data-quality controls | **Complete** |
| Day 7 | Reconciliation engine version 1 | **Complete** |
| Day 8 | Analyst dashboard | **Complete** |
| Day 9 | Background processing | **Complete** |
| Day 10 | Fraud rule engine | **Complete** |
| Day 11 | Case-management workflow | **Not started** |
| Day 12 | Audit logging | **Not started** |
| Day 13 | Reporting and export | **Not started** |
| Day 14 | Comprehensive automated testing | **Not started** |
| Day 15 | Observability | **Not started** |
| Day 16 | Security and privacy review | **Not started** |
| Day 17 | Performance and resilience | **Not started** |
| Day 18 | Evidence-grounded AI explanation | **Not started** |
| Day 19 | Deployment preparation | **Not started** |
| Day 20 | Portfolio package | **Not started** |
| Day 21 | Release and retrospective | **Not started** |

## Detailed plan

### Day 1 — Product definition and repository creation

**Status: Complete**

- Initialise the Git repository on `main` and create the agreed project structure.
- Define administrator, operations analyst, and auditor workflows.
- Write acceptance criteria for ingestion, reconciliation, alerts, investigations, and reports.
- Document scope, exclusions, success metrics, risks, engineering constraints, and intended architecture.
- Add repository instructions, `PROJECT_PLAN.md`, `PROGRESS.md`, `README.md`, `.gitignore`, `.env.example`, local-development guidance, and a Day 1 validator.

**Completion criterion:** the repository contains a coherent, validated product specification and development plan, and the work is committed locally.

### Day 2 — Domain and data model

**Status: Complete**

- Model users, roles, accounts, transactions, settlements, ingestion batches, reconciliation runs, rules, alerts, cases, comments, and audit events.
- Define lifecycle statuses, relationships, ownership, money precision, UTC timestamps, indexes, uniqueness, and retention assumptions.
- Produce an entity-relationship diagram.
- Add architecture decision records for money handling, identifiers, and audit history.

**Completion criterion:** the documented model supports the complete transaction-to-case workflow and its invariants are reviewable before implementation.

### Day 3 — Local platform foundation

**Status: Complete**

- Create the FastAPI backend and React/TypeScript frontend.
- Configure PostgreSQL, Redis, Celery, Docker, and Docker Compose.
- Add validated configuration, SQLAlchemy, Alembic migrations, seed commands, and health endpoints.
- Add basic formatting, linting, type-checking, smoke tests, pinned tooling, and clean-clone setup instructions.

**Completion criterion:** the empty platform starts from a clean clone using documented commands and passes its baseline checks.

### Day 4 — Authentication and role-based access

**Status: Complete**

- Implement secure password storage, login, logout, token/session expiry, and synthetic demonstration-user seeding.
- Implement administrator, operations analyst, and auditor permissions with deny-by-default policies.
- Protect backend endpoints independently of frontend visibility.
- Test successful and failed authentication, expiry, disabled users, and role boundaries.

**Completion criterion:** automated tests prove least-privilege behaviour at the API boundary.

### Day 5 — Transaction ingestion

**Status: Complete**

- Implement CSV upload and JSON API ingestion.
- Publish the accepted, versioned transaction schema.
- Validate required fields, decimal amounts, currency, UTC timestamps, identifiers, and batch metadata.
- Store accepted and rejected records with stable rejection codes and clear reasons.

**Completion criterion:** valid and invalid synthetic sample batches produce deterministic, traceable results.

### Day 6 — Idempotency and data-quality controls

**Status: Complete**

- Add request idempotency keys, payload fingerprints, and source-record identifiers.
- Prevent duplicate batches and transactions using application logic and database constraints.
- Detect missing fields, invalid currencies, impossible amounts, malformed timestamps, and conflicting records.
- Produce a batch-level quality summary and test retries and conflicts.

**Completion criterion:** retry and duplicate-delivery tests cannot create duplicate financial records.

### Day 7 — Reconciliation engine version 1

**Status: Complete**

- Match transactions against settlements using reference, decimal amount, currency, and a documented UTC time window.
- Classify exact matches, partial matches, missing settlements, duplicate candidates, and unexplained settlements.
- Store candidate comparisons, algorithm version, reason codes, and matching evidence.
- Add deterministic unit tests for all seeded scenarios.

**Completion criterion:** seeded inputs produce explainable and reproducible results and totals.

### Day 8 — Analyst dashboard

**Status: Complete**

- Build authentication-aware navigation and role-specific screens.
- Add reconciliation summary cards, batch status, filters, sortable tables, and transaction details.
- Display totals, matched value, unresolved value, match rate, and validation failures without unsafe money arithmetic.
- Add accessible loading, empty, validation, forbidden, and error states.

**Completion criterion:** an analyst can efficiently locate and explain the highest-priority seeded discrepancy.

### Day 9 — Background processing

**Status: Complete**

- Move batch parsing and reconciliation into Celery jobs.
- Add queued/running/succeeded/failed/cancelled states, progress, retries, timeouts, failure reasons, and practical cancellation.
- Make tasks transactional and safe under retry and duplicate delivery.
- Add worker health checks and PostgreSQL/Redis integration tests.

**Completion criterion:** large synthetic batches process asynchronously without blocking web requests, and failure/retry paths are verified.

### Day 10 — Fraud rule engine

**Status: Complete**

- Create configurable rules for transaction velocity, unusual amount, repeated failures, duplicate instruments, and suspicious timing.
- Store rule version, evaluated inputs, evidence, score/severity, and output for every alert.
- Keep rules deterministic, idempotent, and independently testable.
- Add synthetic positive and negative scenarios.

**Completion criterion:** every alert clearly explains its origin and replaying the same version/evidence yields the same result.

### Day 11 — Case-management workflow

**Status: Not started**

- Allow analysts to assign, comment on, escalate, resolve, and reopen cases.
- Record case status history, linked alerts, ownership, and optimistic concurrency evidence.
- Enforce valid state transitions and role permissions in the API.
- Add filters for owner, priority, status, rule, and age.

**Completion criterion:** an alert can traverse a complete, audited investigation lifecycle while invalid transitions are rejected.

### Day 12 — Audit logging

**Status: Not started**

- Record authentication events and security-sensitive reads.
- Record every write affecting transactions, rules, reconciliation results, alerts, and cases.
- Include actor, UTC timestamp, target, action, result, correlation ID, and appropriate before/after evidence.
- Make audit history append-only through the normal application interface and test access controls.

**Completion criterion:** an auditor can reconstruct a seeded decision from ingestion to resolution.

### Day 13 — Reporting and export

**Status: Not started**

- Produce daily reconciliation summaries and unresolved-case reports with explicit scope and cutoff.
- Implement allowlisted CSV exports and prevent spreadsheet formula injection.
- Verify report totals with independent database calculations and fail closed on mismatch.
- Audit report generation and export.

**Completion criterion:** reports reconcile with stored transaction/settlement totals and unsafe CSV values are neutralised.

### Day 14 — Comprehensive automated testing

**Status: Not started**

- Expand unit tests for matching, rules, permissions, transitions, money handling, and idempotency.
- Add database and worker integration tests including failures and retries.
- Add Playwright journeys for administrators, analysts, and auditors.
- Configure GitHub Actions for formatting, linting, type-checking, backend/frontend tests, and production builds.

**Completion criterion:** critical workflows run automatically and reliably in CI, with exact results documented.

### Day 15 — Observability

**Status: Not started**

- Add structured redacted logs, request IDs, job IDs, metrics, traces, and dependency-aware health checks.
- Track API latency/error rate, queue depth, worker failures, ingestion throughput, and reconciliation throughput.
- Create a basic Prometheus/Grafana operational dashboard or document a justified lightweight alternative.
- Demonstrate tracing a failed job from API request to worker error.

**Completion criterion:** an important seeded failure is diagnosable through telemetry without attaching a debugger.

### Day 16 — Security and privacy review

**Status: Not started**

- Create a threat model for authentication, privilege escalation, malicious uploads, injection, excessive resource use, secret exposure, and audit tampering.
- Add rate limits, upload limits, secure headers, dependency/secret scanning, and log redaction.
- Review database privileges, application secrets, synthetic-data enforcement, and access boundaries.
- Document data retention assumptions, findings, repairs, and residual risks.

**Completion criterion:** critical findings are repaired and remaining risks and owners are recorded honestly.

### Day 17 — Performance and resilience

**Status: Not started**

- Generate at least 10,000 synthetic transactions with known reconciliation outcomes.
- Measure throughput, p50/p95 latency, failure rate, and worker processing time with environment and method recorded.
- Test worker restart, duplicate delivery, partial failure, and database reconnection.
- Identify and optimise one measured bottleneck, then compare before and after.

**Completion criterion:** reproducible measurements and resilience outcomes are published without invented claims.

### Day 18 — Evidence-grounded AI explanation

**Status: Not started**

- Add an optional provider interface for analyst explanations of flagged transactions.
- Generate only from stored transaction, rule, and reconciliation evidence, citing exact fields and rules.
- Keep a deterministic non-AI explanation available and abstain when evidence is insufficient.
- Create an evaluation set covering answerable, ambiguous, and unsupported cases.
- When no credential exists, use fixtures/mocks and the deterministic fallback without a paid API dependency.

**Completion criterion:** tests show grounded citations and abstention rather than invented evidence.

### Day 19 — Deployment preparation

**Status: Not started**

- Prepare production containers and isolated infrastructure documentation/configuration.
- Document migrations, HTTPS assumptions, managed PostgreSQL, queue service, monitoring, backups, and secret injection.
- Add deployment smoke tests, rollback instructions, and Cloud Run operational caveats.
- Deploy only if credentials and explicit authorisation are available.

**Completion criterion:** the system is deployable through a documented repeatable process, or all non-credential work and exact external blockers are recorded.

### Day 20 — Portfolio package

**Status: Not started**

- Create architecture, sequence, deployment, and data-flow diagrams aligned with implementation.
- Document threat model, test strategy, observability, measured performance, limitations, and trade-offs.
- Add safe screenshots and synthetic demo credentials where appropriate.
- Prepare a two-to-three-minute demonstration script and two truthful resume bullets using measured outcomes only.

**Completion criterion:** a recruiter can quickly understand the system's engineering depth and verify its claims.

### Day 21 — Release and retrospective

**Status: Not started**

- Run complete setup and the demonstration workflow from a clean clone.
- Run all quality checks and inspect the repository for credentials, private data, and generated secrets.
- Tag a stable local `v1.0.0` release without pushing it.
- Document known limitations, lessons learned, and the next three improvements.

**Completion criterion:** the project is stable, reproducible, honest, application-ready, committed, and locally tagged.
