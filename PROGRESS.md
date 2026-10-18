# LedgerGuard Progress

## Current roadmap day

**Day 14 — Comprehensive automated testing: Complete**

## Completed days

- **Day 1 (2026-10-06):** Created the repository on `main`; defined roles and workflows; documented acceptance criteria, scope, exclusions, success metrics, risks, architecture, engineering conventions, development environment, repository rules, and the complete delivery plan; added an automated structural validator.
- **Day 2 (2026-10-06):** Defined 20 database entities spanning identity, ingestion, financial facts, reconciliation, fraud monitoring, investigations, and audit; documented lifecycles, relationships, precision, UTC handling, constraints, indexes, retention assumptions, a Mermaid ER diagram, and accepted ADRs for money, identifiers, and audit history.
- **Day 3 (2026-10-07):** Implemented the FastAPI and React/TypeScript foundations; configured PostgreSQL, Redis, Celery, and a five-service Docker Compose stack; added validated settings, SQLAlchemy models, the explicit initial Alembic migration, idempotent synthetic seeding, health endpoints, pinned development tooling, automated checks, and clean-clone setup documentation.
- **Day 4 (2026-10-09):** Added Argon2id password hashing, opaque bearer sessions stored as keyed digests, PostgreSQL-backed expiry and logout revocation, login lockout handling, synthetic demonstration users, deny-by-default permissions, protected API boundaries, and a role-aware interface.
- **Day 5 (2026-10-13):** Added authenticated JSON and CSV transaction ingestion through one versioned validation pipeline; decimal-safe amounts, UTC normalization, identifier/currency/status validation, accepted financial facts, persisted rejection evidence, bounded uploads, published synthetic fixtures, and integration-proven role enforcement.
- **Day 6 (2026-10-13):** Added required client idempotency keys, canonical batch and row payload fingerprints, exact-retry replay, changed-payload conflict handling, normalized source-record duplicate/conflict classification, account-level concurrency serialization, deterministic batch-quality summaries, and reinforcing PostgreSQL checks.
- **Day 7 (2026-10-14):** Added deterministic transaction-to-settlement reconciliation with exact, partial, missing, duplicate-candidate, and unexplained classifications; stored canonical evidence and reason codes; replay-safe runs; role-protected create/read APIs; an isolated synthetic demonstration scenario; and exact-arithmetic database constraints.
- **Day 8 (2026-10-14):** Added an authenticated operational dashboard with decimal-safe reconciliation metrics, account-scoped batch quality, deterministic discrepancy prioritisation, filtering, evidence details, role-aware run controls, and explicit loading, empty, validation, forbidden, and recoverable-error states.
- **Day 9 (2026-10-15):** Moved JSON/CSV ingestion and reconciliation into durable Celery jobs; added PostgreSQL-backed progress, bounded retries and timeouts, safe failure evidence, cooperative cancellation, duplicate-delivery guards, job permissions and analyst progress controls; verified PostgreSQL, Redis, worker health, and a 10,000-row synthetic batch.
- **Day 10 (2026-10-16):** Added five configurable deterministic fraud-rule families, immutable activated versions, canonical alert evidence and replay deduplication, positive/negative synthetic scenarios, administrator/analyst/auditor permissions, and a role-aware fraud-monitoring interface.
- **Day 11 (2026-10-16):** Added version-protected investigation cases with alert claiming, valid assignment, append-only comments and status history, controlled review/escalation/resolution/reopening, linked-alert status effects, queue filters, role enforcement, database invariants, and an analyst/auditor case workspace.
- **Day 12 (2026-10-16):** Added structured audit evidence for authentication, authorization denials, sensitive reads, durable jobs, ingestion, reconciliation, rule versions, alerts, and cases; enforced validated/redacted event payloads and append-only PostgreSQL history; and added auditor-only filtering and transaction-to-case reconstruction in the API and interface.
- **Day 13 (2026-10-16):** Added account/date-scoped daily reconciliation summaries and cutoff-bounded unresolved-case reports; independently verified exact decimal totals against separate PostgreSQL aggregates; implemented fixed-field CSV exports with spreadsheet-formula neutralization; audited report views/exports; and added loading, empty, failure, and export interface states for all supported roles.
- **Day 14 (2026-10-19):** Published a risk-based automated test strategy; expanded exact-money, permission, reconciliation, fraud-boundary, case-concurrency, retry, database, and real-worker coverage; added Chromium journeys for all three roles; and configured GitHub Actions to run backend, frontend, integration, browser, migration, and production-build gates.

## Current architecture

LedgerGuard is a modular monolith with a React/TypeScript interface, FastAPI API, PostgreSQL system of record, and Redis/Celery worker. Docker Compose defines the five-service local platform. SQLAlchemy implements the domain model; nine Alembic revisions provide 22 application tables, revocable authentication sessions, structured ingestion/reconciliation/fraud/case evidence, durable background jobs, reinforcing constraints, immutable activated rule configuration, and an append-only audit trigger. FastAPI validates request envelopes and independently enforces least privilege. The reporting module builds read-only projections directly from authoritative facts, verifies row-level Python `Decimal` totals against independent SQL aggregates, fails closed on disagreement, emits fixed-field formula-safe CSV, and audits every view/export. The audit module provides bounded/redacted evidence and auditor-only reconstruction. Redis transports job identifiers while PostgreSQL remains authoritative for financial, job, rule, alert, case, audit, and report-source state. The interface preserves money as strings, labels UTC, hides controls by permission, and provides explicit loading, empty, held-report, and export states. A three-job GitHub Actions pipeline now separates backend and frontend quality gates from an isolated Compose integration/browser gate; Playwright validates administrator, analyst, and auditor journeys against the assembled application. Validated settings use safe local defaults and environment overrides. GCP-specific deployment concerns remain isolated.

## Important decisions

- Use only synthetic demonstration data; no real financial or personal information belongs in the repository.
- Keep a modular monolith and separate worker process until measured constraints justify another service boundary.
- Enforce least privilege in the API and mirror it in the interface.
- Use decimal-safe money handling end to end; never calculate monetary values with binary floating point.
- Store and exchange timezone-aware UTC timestamps; convert only for clearly labelled display.
- Use PostgreSQL constraints alongside application validation.
- Preserve versioned inputs and evidence for reconciliation outcomes, rules, alerts, cases, reports, and audit events.
- Keep ingestion and jobs idempotent and safe under retry or duplicate delivery.
- Treat AI explanations as optional evidence rendering with a deterministic fallback and mandatory abstention on missing support.
- Keep cloud integrations behind adapters/configuration so local development remains independent of GCP.
- Store monetary values as PostgreSQL `NUMERIC(20,6)`, Python `Decimal`, and JSON decimal strings; store economic direction separately.
- Use opaque UUIDv4 primary/correlation identifiers. Keep source identifiers scoped to account/source boundaries and use identity sequences only for audit ordering and human case numbers.
- Preserve reconciliation groups with separate transaction and settlement item tables so exact, partial, missing, unexplained, and duplicate-candidate outcomes share one evidence model.
- Make active fraud rule versions immutable and permit only one active version per logical rule.
- Give the runtime application role insert/read-only access to `audit_events`, reinforce append-only behaviour with a database trigger, and prohibit secrets or unrestricted payloads in audit metadata.
- Treat the documented retention periods as portfolio assumptions pending Day 16 security/policy review; implement no automatic purge before legal-hold and evidence tests exist.
- Represent lifecycle values with checked `VARCHAR` columns rather than PostgreSQL enum types so application and migration changes remain explicit and portable; see ADR 0004.
- Seed only idempotent roles, a clearly synthetic demonstration account, and three `.invalid` demonstration users. Refuse demonstration-user seeding in production.
- Keep liveness independent of infrastructure and return HTTP 503 from readiness until both PostgreSQL and Redis respond.
- Hash passwords with Argon2id. Return high-entropy opaque session tokens once, persist only HMAC-SHA-256 digests, expire them server-side, and revoke them on logout.
- Keep bearer tokens only in interface memory. Unknown roles receive no permissions; API checks remain authoritative regardless of interface visibility.
- Publish transaction schema `1.0` and require amounts to be positive decimal strings with no more than 14 integer and 6 fractional digits; normalize offset-aware timestamps to UTC before storage.
- Route JSON and UTF-8 CSV through the same strict record validator. Persist every readable row with a canonical SHA-256 payload digest, stable reason codes, structured field-level rejection details, and an accepted transaction link when applicable.
- Limit synchronous Day 5 requests to 10,000 records and CSV uploads to 2 MB by default. Generate an internal batch key until client retry/idempotency semantics are added on Day 6.
- Flush each ingestion batch, then accepted transactions, then record evidence within one database transaction so PostgreSQL foreign keys are always satisfied; roll back the entire unit on database error.
- Require a 1–200 character `Idempotency-Key`, scoped with `source_system`. Return the stored batch for an identical canonical payload hash and HTTP 409 for changed content; database uniqueness remains the final race guard.
- Compare normalized source reference, `Decimal` amount, currency, direction, status, UTC occurrence time, and fingerprint when classifying duplicate versus conflicting source identifiers. Neither outcome creates a new financial fact.
- Lock the active source-account row during classification so concurrent deliveries for one account cannot race past the existing-transaction check.
- Report clean/issues status, accepted/rejected/duplicate/conflict counts, issue count, a two-decimal string acceptance percentage, and deterministic reason counts without binary floating-point arithmetic.
- Reconcile only posted transactions and confirmed settlements at or before a caller-supplied UTC cutoff. Candidate settlements must have equal reference and currency and occur from zero through the configured 1–168 hour window after the transaction.
- Partition the candidate graph deterministically. One-to-one equal amounts are exact; connected non-duplicate groups are partial; isolated facts are missing/unexplained; multiple equal-amount counterparts are duplicate candidates.
- Hash the algorithm version, account, cutoff, configuration, and sorted immutable input facts into a unique replay key. Exact repeated runs return stored results without new rows.
- Store canonical evidence, stable reason codes, decimal totals, and every result-item link. PostgreSQL enforces exact difference arithmetic and unique evidence within each run.
- Select the dashboard snapshot by greatest effective UTC input cutoff, then creation time and UUID, so a later-created historical run cannot hide newer operational evidence.
- Calculate dashboard money and percentages with Python `Decimal`; keep money as strings in JSON and React, using scaled `BigInt` comparison instead of JavaScript `number` arithmetic.
- Prioritise non-exact outcomes before exact matches, then order by greatest unresolved exposure with classification and UUID tie-breakers. Auditors share the evidence view but never receive run controls.
- Commit the durable job row before publishing its UUID as the Celery task ID; an exact queued retry republishes safely when broker delivery was unavailable.
- Keep PostgreSQL as the authoritative job state and Redis as a delivery/result transport. Clear queued payloads at terminal state while retaining domain evidence and result links.
- Acknowledge tasks late, reject on worker loss, prefetch one, retry only transient SQLAlchemy failures with bounded backoff, and turn validation or product failures into stable sanitized terminal evidence.
- Guarantee cancellation while queued and use cooperative checkpoints while running so no worker is killed during a database commit. Auditors may read reconciliation jobs but never submit or cancel them.
- Evaluate only posted transaction subjects and use same-account historical context at or before each subject, with UUID tie-breaking for equal timestamps and no future-data leakage.
- Implement velocity, unusual amount, repeated failure, duplicate instrument, and suspicious UTC timing as strict versioned parameter contracts. Reject binary floating-point money thresholds and unknown configuration keys.
- Store rule/version identity, subject and matched facts, parameters, metric, threshold, reason, severity, deterministic score, cutoff, and output in canonical alert evidence. Treat the score as a triage signal, never a probability.
- Permit only administrators to create or version rules; administrators and analysts may evaluate; all three supported roles may read rules and alerts; auditors receive no mutation controls.
- Retire the prior active version atomically when a new version activates. PostgreSQL lifecycle checks and a trigger prevent configuration changes after activation while allowing the active-to-retired lifecycle transition.
- Require an expected case version on every mutation and return `CASE_VERSION_CONFLICT` for stale work; increment the aggregate once per successful assignment, comment, alert link, or transition.
- Permit an alert to enter only one case through the normal workflow. Resolve linked alerts as closed for confirmed issues and dismissed otherwise; reopening restores them to in-review and clears closure metadata.
- Restrict case ownership to active administrators or operations analysts. Auditors retain complete case evidence reads but receive no mutation endpoint or interface controls.
- Route security and domain events through one audit writer that validates action and target names, rejects secret-like keys and oversized evidence, stores only structured JSON objects, and participates in the same database transaction as the affected write.
- Treat audit reads as security-sensitive events themselves. Only auditors and administrators may query history; case reconstruction follows explicit case-alert-transaction links and never relies on free-text matching.
- Define daily financial scope as posted transactions by `occurred_at` and confirmed settlements by `settled_at` in a half-open UTC day, grouped without currency conversion.
- Calculate every daily count and amount from individual facts with `Decimal`, independently repeat the calculation with PostgreSQL `COUNT`/`SUM`, and return neither JSON nor CSV if currency sets, counts, or exact totals disagree.
- Export only fixed server-side fields. Neutralize cells whose first non-whitespace character is `=`, `+`, `-`, or `@` (and tab/line-control prefixes) before the standard CSV writer quotes them.
- Apply a risk-based test pyramid: keep deterministic domain cases at unit level, prove PostgreSQL/Redis/Celery differences through opt-in integration tests, and reserve Playwright for assembled role journeys.
- Keep browser selectors accessibility-oriented and role journeys independent. Run Chromium serially against the documented `http://localhost:5173` origin, retain diagnostics only on failure, and never commit browser artifacts.
- Split CI into independent locked backend/frontend jobs and a dependent isolated Compose job. Always tear down CI volumes; upload browser and service diagnostics only when the assembled gate fails.

## Commands required to run the system

From the repository root, copy `.env.example` to an untracked `.env`, then start the local stack:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose exec api ledgerguard-seed
```

Run the complete local quality suite after installing pinned dependencies:

```powershell
./scripts/bootstrap.ps1
./scripts/check.ps1
./scripts/validate-day-01.ps1
./scripts/validate-day-02.ps1
./scripts/validate-day-03.ps1
./scripts/validate-day-04.ps1
./scripts/validate-day-05.ps1
./scripts/validate-day-06.ps1
./scripts/validate-day-07.ps1
./scripts/validate-day-08.ps1
./scripts/validate-day-09.ps1
./scripts/validate-day-10.ps1
./scripts/validate-day-11.ps1
./scripts/validate-day-12.ps1
./scripts/validate-day-13.ps1
./scripts/validate-day-14.ps1
```

Configuration placeholders are documented in `.env.example`; `.env` must remain untracked.

Seed the isolated deterministic reconciliation scenario after the normal development seed:

```powershell
docker compose exec api ledgerguard-seed-reconciliation
docker compose exec api ledgerguard-seed-fraud
```

The unchanged Docker defaults seed `admin@ledgerguard.invalid`, `analyst@ledgerguard.invalid`, and `auditor@ledgerguard.invalid` with the local-only password `DemoOnly!ChangeMe123456`. Override `DEMO_USER_PASSWORD` in `.env` before sharing the environment.

Open `http://localhost:5173` after seeding and running reconciliation. The analyst account receives the operational dashboard and run controls; the auditor account receives the same evidence in read-only mode.

Install Chromium once and run the administrator, operations analyst, and auditor browser journeys
against the healthy seeded stack:

```powershell
cd frontend
npx playwright install chromium
npm run test:e2e
```

## Test and coverage results

- Day 14 backend quality gates: Ruff formatting and linting passed across 43 source/test/migration files; strict mypy found no issues in 18 source files; the full isolated suite completed with 164 passed, 8 opt-in integration tests skipped, and one upstream Starlette/AnyIO deprecation warning in 9.13 seconds.
- Day 14 measured backend coverage: 74% overall (2,786 statements, 713 missed). This is a measured observation, not a project-wide coverage target or assurance claim.
- Day 14 live integration suite: 8 passed in 6.43 seconds against PostgreSQL revision `20261016_0009`, Redis, and Celery after a clean development-image rebuild. Coverage includes database invariants, broker/worker health, a real queued worker task, durable retry state, terminal payload removal, and cleanup.
- Day 14 frontend gates: ESLint and TypeScript checking passed; 21 Vitest tests passed across seven files in 8.25 seconds; the production build transformed 22 modules and produced a 191.01 kB JavaScript bundle (57.32 kB gzip) and 16.17 kB CSS bundle (4.17 kB gzip); the locked dependency audit found 0 known vulnerabilities.
- Day 14 Playwright journeys: 3 passed in Chromium in 6.1 seconds against the rebuilt live stack, covering administrator oversight, analyst investigation controls, and auditor read-only evidence access.
- Day 14 Compose reproducibility: `docker compose up -d --build --wait` rebuilt all application images, all five services reached their expected running/healthy state, all three synthetic seed commands completed idempotently, and the integration suite ran from the same development image used by CI.
- GitHub Actions now defines backend formatting/linting/type/test/coverage/migration gates, frontend lint/type/test/build gates, and an isolated Compose integration/Playwright gate with failure-only diagnostics and unconditional cleanup. The workflow will receive its first hosted run when this daily commit is pushed; no hosted result is claimed here.
- Day 1–14 structural validators, Markdown local-link validation, secret-pattern review, and Git whitespace/error checks passed with no findings.

- Day 13 complete quality suite: Ruff formatting and linting passed across 43 backend source/test/migration files; strict mypy found no issues in 18 source files; Alembic rendered all nine revisions offline through `20261016_0009`.
- Day 13 backend suite: 157 passed and 6 opt-in integration tests skipped in 8.67 seconds; one upstream Starlette/AnyIO deprecation warning remains. Measured statement coverage was 74% overall (2,786 statements, 715 missed) and 76% for the new reporting module.
- Day 13 focused report suite: 18 passed in 3.26 seconds, covering exact decimal aggregation, mismatch refusal, supported and unsupported roles, UTC validation, explicit CSV fields, formula controls, report auditing, and JSON/CSV behaviour.
- Day 13 live integration suite: 6 passed in 6.04 seconds against PostgreSQL revision `20261016_0009`, Redis, and the Celery worker.
- Day 13 frontend checks: ESLint and TypeScript checking passed; 21 tests passed across seven Vitest files in 8.04 seconds; the production build transformed 22 modules and produced a 191.01 kB JavaScript bundle (57.32 kB gzip) and 16.17 kB CSS bundle (4.17 kB gzip).
- Live daily report and independent SQL proof: four posted USD transactions totalled `250.000000`; five confirmed USD settlements totalled `215.000000`; both the API and direct PostgreSQL queries returned those exact values, and the report returned verified difference `-35.000000` plus a five-result reconciliation snapshot.
- Live safe-export proof: the daily CSV used its documented fixed header and neutralized the negative difference; an unresolved synthetic case titled `=2+2 synthetic export proof` was exported with an apostrophe prefix. Audit history recorded `report.daily.view`, `report.daily.export`, `report.unresolved.view`, and `report.unresolved.export`.
- Live platform smoke check: the frontend returned HTTP 200 and API readiness reported both PostgreSQL and Redis `up`.

- Day 12 backend quality checks: Ruff formatting and linting passed across 41 source/test/migration files; strict mypy found no issues in 17 source files.
- Day 12 backend suite: 139 passed and 6 opt-in integration tests skipped in 7.78 seconds; one upstream Starlette/AnyIO deprecation warning remains. Measured statement coverage was 74% overall (2,596 statements, 669 missed), 70% for the audit API, and 95% for the shared audit writer.
- Day 12 live integration suite: 6 passed in 5.94 seconds against PostgreSQL revision `20261016_0009`, including the audit constraints, append-only trigger, Redis connection, and worker checks.
- Day 12 frontend checks: ESLint and TypeScript checking passed; 18 tests passed across six Vitest files; the production build transformed 21 modules and produced a 182.53 kB JavaScript bundle (55.72 kB gzip) and 14.40 kB CSS bundle (3.84 kB gzip).
- Live audit reconstruction: a denied login returned HTTP 401, an ingestion job succeeded, a fresh synthetic transaction generated alert evidence, and its case reached resolved. Analyst audit access returned HTTP 403; the auditor timeline returned 6 events spanning `transaction.ingestion.completed`, `fraud.alert.created`, `case.created`, `case.transitioned`, and the sensitive timeline read.
- Live append-only safeguard: PostgreSQL rejected a controlled update of an audit event with `audit_events are append-only`; no audit row was changed.

- Day 11 backend quality checks: Ruff found no lint or formatting issues across 28 source/test files; strict mypy found no issues in 15 source files.
- Day 11 backend suite: 131 passed and 5 opt-in integration tests skipped in 2.94 seconds; one upstream Starlette/AnyIO deprecation warning remains. No coverage measurement was run or claimed for Day 11.
- Day 11 live integration suite: 5 passed in 6.07 seconds against PostgreSQL revision `20261016_0008`, Redis, and the Celery worker; all five Compose services were running and the API, database, Redis, and worker were healthy.
- Day 11 frontend checks: ESLint and TypeScript checking passed; 17 tests passed across five Vitest files; the production build transformed 20 modules and produced a 177.88 kB JavaScript bundle (54.96 kB gzip).
- Live case lifecycle: one synthetic alert produced a case that was assigned, commented, moved through in-review and escalation, resolved, and reopened. The result retained 5 status-history entries, closed the alert on confirmed resolution, returned it to in-review on reopen, and matched the combined owner/priority/status/rule/age filter.
- Live conflict and permission checks: a stale comment returned HTTP 409 and an auditor comment returned HTTP 403. The final reopened case was at version 7 with one append-only comment.

- Day 10 backend formatting and linting: Ruff reported 34 files formatted and no findings; strict mypy reported no issues in 14 source files.
- Day 10 complete backend suite: 110 passed and 4 opt-in integration tests skipped; measured statement coverage was 77% overall (2,089 statements, 472 missed), with the new fraud module at 69% and all SQLAlchemy model declarations exercised.
- Day 10 focused fraud suite: 15 passed, covering all five trigger families, negative cases, wrapped UTC windows, invalid configuration, determinism, and API permission denials.
- Day 10 frontend checks: ESLint and TypeScript checking passed; 15 tests passed across four Vitest files; the production build transformed 19 modules and produced a 167.78 kB JavaScript bundle (52.81 kB gzip); the locked dependency audit found 0 vulnerabilities.
- Complete Alembic offline render: passed through `20261016_0007`; the live database reported that revision at head. The new checks enforce rule lifecycle and JSON evidence shape, and PostgreSQL rejected an attempted active-rule severity change through the immutability trigger.
- Live fraud scenario: the idempotent seeder retained five active rule families and six synthetic facts after two runs. Initial evaluation produced nine explainable alerts; exact replay created zero and returned the same nine alert IDs, all with valid 64-character evidence hashes.
- Live role and version boundaries: analyst rule creation and auditor evaluation each returned HTTP 403; an administrator activated velocity rule version 2, leaving exactly one active and one retired version.
- Live platform check: PostgreSQL, Redis, API, and worker reported healthy; the worker returned `pong`, the frontend returned HTTP 200, and the Day 10 database integration checks passed.

- Day 9 backend formatting and linting: Ruff reported 31 files formatted and no findings; strict mypy reported no issues in 13 source files.
- Day 9 focused jobs, worker, ingestion, and reconciliation suite: 57 passed in 2.52 seconds; one upstream Starlette/AnyIO deprecation warning remains.
- Day 9 complete backend suite: 95 passed and 3 opt-in integration tests skipped in 5.15 seconds. Measured statement coverage was 80% overall (1,718 statements, 337 missed); configuration measured 98%, ingestion 97%, reconciliation 77%, jobs 54%, and worker 64%.
- Day 9 frontend checks: ESLint and TypeScript checking passed; 13 tests passed across three Vitest files in 33.12 seconds; the production build transformed 18 modules and produced a 162.96 kB JavaScript bundle (51.97 kB gzip); the locked dependency audit found 0 vulnerabilities.
- Day 9 PostgreSQL/Redis/Celery integration suite: 3 passed in 5.87 seconds against the live Compose network; Alembic reported `20261014_0006 (head)` and the worker returned `pong`.
- Complete Alembic offline render: passed; 595 SQL lines rendered all six revisions through `20261014_0006`. Docker Compose configuration validation also passed.
- Live asynchronous reconciliation: submission returned HTTP 202 and completed successfully in one attempt; an exact retry returned HTTP 200 with the same job, changed content under the same key returned HTTP 409, and duplicate Celery delivery retained one run and attempt count `1`. A simulated worker loss after durable claim resumed from `running` after restart, succeeded with a result, and retained logical attempt count `1`.
- Live job permissions and cancellation: auditor reconciliation-job read returned HTTP 200 and cancellation returned HTTP 403; a queued analyst job cancelled with HTTP 202, remained cancelled after worker restart, made zero attempts, and created no result.
- Live failure evidence: a queued request for a missing synthetic account reached `failed` in one attempt with sanitized `JOB_INPUT_REJECTED` evidence and a terminal timestamp.
- Live 10,000-row ingestion: a 1,890,108-byte synthetic JSON request returned HTTP 202 in 2,250 ms while initially queued; the worker completed in one attempt after 6,734 ms of polling, persisting 10,000 accepted transactions and 10,000 evidence rows with no rejections, duplicates, or conflicts. These are local development measurements, not production performance claims.
- Live platform check: PostgreSQL, Redis, API, and worker reported healthy; API readiness and the frontend returned HTTP 200.
- Day 1–9 structural validators: passed.
- Final Markdown local-link validation: passed; 23 Markdown files checked with no broken local links.
- Final secret-pattern review: passed; 106 tracked or unignored paths checked with no private-key, AWS access-key, GitHub token, OpenAI-style API-key, or Google API-key patterns.
- Final Git whitespace/error check: passed with no findings.

- Day 8 backend formatting: passed after Ruff formatted the new dashboard regression assertion; 27 source, test, and migration files are formatted.
- Day 8 backend linting: passed with no Ruff findings.
- Day 8 strict type checking: passed; no issues in 12 source files.
- Day 8 focused dashboard/reconciliation tests: 16 passed in 1.34 seconds; the final dashboard-only rerun passed 8 tests in 1.43 seconds. One upstream Starlette/AnyIO deprecation warning remains.
- Day 8 complete backend suite: 76 passed in 5.33 seconds. Measured statement coverage was 86% overall (1,371 statements, 193 missed); the new dashboard module measured 100% (75 statements), reconciliation 77%, and ingestion 97%.
- Day 8 frontend checks: ESLint and TypeScript checking passed; 12 tests passed across three Vitest files in 1.98 seconds; the production build transformed 18 modules and produced a 161.85 kB JavaScript bundle (51.68 kB gzip); the locked dependency audit found 0 known vulnerabilities.
- Day 8 live API path: analyst dashboard read returned HTTP 200; analyst run creation returned HTTP 201; auditor dashboard read returned HTTP 200; unauthenticated read returned HTTP 401. Effective-cutoff ordering retained the five-result evidence snapshot after a later-created historical run.
- Day 8 live dashboard values: transaction value `250.000000`, exact matched value `100.000000`, unresolved value `185.000000`, match rate `40.00`, two related batches, and one result in each of the five reconciliation classifications.
- Complete Alembic offline render: passed; 537 SQL lines rendered all five revisions through `20261014_0005`. Runtime Alembic reported `20261014_0005 (head)`.
- Synthetic reconciliation reseed: passed idempotently without adding duplicate financial facts.
- Day 1–8 structural validators: passed.
- Final Markdown local-link validation: passed; 21 Markdown files checked with no broken local links.
- Final secret-pattern review: passed; 100 tracked or unignored paths checked with no matching private-key, AWS access-key, GitHub token, OpenAI-style API-key, or Google API-key patterns.
- Final Git whitespace/error check: passed with no findings.
- Day 7 backend formatting: passed; 25 source, test, and migration files were already formatted after the implementation corrections.
- Day 7 backend linting: passed with no Ruff findings.
- Day 7 strict type checking: passed; no issues in 11 source files.
- Day 7 focused reconciliation/model tests: 14 passed in 1.56 seconds on Python 3.12.8.
- Day 7 complete backend suite: 68 passed in 5.80 seconds. Measured statement coverage was 85% overall (1,294 statements, 193 missed), 77% for reconciliation (266 statements, 62 missed), and 97% for ingestion. One upstream Starlette/AnyIO deprecation warning remains.
- Day 7 frontend regression checks: ESLint and TypeScript checking passed; 4 tests passed in one Vitest file; the production build transformed 16 modules and produced a 147.11 kB JavaScript bundle (48.08 kB gzip); the locked dependency audit found 0 known vulnerabilities.
- Complete Alembic offline render: passed; 537 SQL lines rendered all five revisions through `20261014_0005`, including exact-difference and per-run evidence uniqueness constraints.
- Day 7 migration and seed: Alembic reported `20261014_0005 (head)`; both the base seed and isolated reconciliation seed completed successfully, and running the reconciliation seed twice created no duplicate facts.
- Live seeded reconciliation: HTTP 201 created five results covering exact, partial, missing, duplicate-candidate, and unexplained classifications exactly once; four transactions totalled `250.000000` USD and five settlements totalled `215.000000` USD.
- Live replay path: an identical request returned HTTP 200, the original run ID, and `replayed: true`; PostgreSQL retained one completed run for that replay key with five results, four unique transaction links, and five unique settlement links.
- Live role boundaries: an auditor read the stored evidence with HTTP 200 and was denied run creation with HTTP 403.
- Live database safeguards: PostgreSQL rejected an incorrect difference through `ck_results_difference_exact`, retained zero invalid differences, and rejected a repeated evidence digest through `uq_results_run_evidence`.
- Live platform check: all five Compose services started; API, PostgreSQL, Redis, and worker reported healthy.
- Day 1–7 structural validators: passed.
- Final Markdown local-link validation: passed; 21 Markdown files checked with no broken local links.
- Final secret-pattern review: passed; 92 tracked or unignored paths checked with no matching private-key, AWS access-key, GitHub token, OpenAI-style API-key, or Google API-key patterns.
- Final Git whitespace/error check: passed with no findings.

- Day 1 structural/specification validation: passed; 19 required paths, 21 roadmap days, required product topics, placeholder environment values, synthetic-data notice, and `main` branch verified.
- Git whitespace/error check: passed with no findings.
- Markdown local-link validation: passed; 7 Markdown files checked with no broken local links.
- Secret-pattern review: passed; 20 candidate files checked with no matching private-key, AWS access-key, GitHub token, or OpenAI-style API-key patterns.
- Day 2 model/ERD/ADR validation: passed; 5 required files, 20 entities, required conventions, Mermaid ER diagram, 3 accepted ADRs, and roadmap status verified.
- Markdown local-link validation after Day 2: passed; 12 Markdown files checked with no broken local links.
- Git whitespace/error check after Day 2: passed with no findings.
- Secret-pattern review after Day 2: passed; 26 candidate files checked with no matching private-key, AWS access-key, GitHub token, or OpenAI-style API-key patterns.
- Backend formatting: passed; 15 files already formatted.
- Backend linting: passed with no Ruff findings.
- Backend strict type checking: passed; no issues in 8 source files.
- Backend automated tests: 13 passed in 2.31 seconds on Python 3.12.8 in the Linux development image. Measured statement coverage was 93% (480 statements, 32 missed).
- Alembic offline migration render: passed for revision `20261007_0001`; generated SQL contained the complete initial schema.
- Frontend linting and TypeScript checking: passed with no findings.
- Frontend automated tests: 2 passed in one test file with Vitest 5.0.3.
- Frontend production build: passed with Vite 8.3.3; 16 modules transformed and a 143.11 kB JavaScript bundle produced (46.75 kB gzip).
- Frontend locked-dependency audit: passed with 0 known vulnerabilities, including development dependencies.
- Native API smoke check: `/health/live` returned HTTP 200; `/health/ready` returned the expected HTTP 503 while PostgreSQL and Redis were unavailable.
- Docker Compose configuration validation: passed with Docker 29.8.2 and Compose 5.5.1.
- Full Docker stack validation: passed. PostgreSQL, Redis, FastAPI, React/Vite, and Celery started together; the API and infrastructure services reported healthy, the frontend returned HTTP 200, and the worker returned `pong`.
- Runtime migration and seed validation: Alembic reported `20261007_0001 (head)`; PostgreSQL contained 21 public tables including `alembic_version`; running the seed twice left exactly 3 roles and 1 synthetic account.
- Day 3 structural validation: passed; application foundations, five Compose services, 20-table migration, quality tooling, environment contract, and roadmap status verified.
- Final Markdown local-link validation: passed; 15 Markdown files checked with no broken local links.
- Final secret-pattern review: passed; 67 tracked or unignored candidate files checked with no matching private-key, AWS access-key, GitHub token, OpenAI-style API-key, or Google API-key patterns.
- Final Git whitespace/error check: passed with no findings.
- Day 6 backend formatting: passed; 22 source, test, and migration files were formatted.
- Day 6 backend linting: passed with no Ruff findings.
- Day 6 strict type checking: passed; no issues in 10 source files.
- Day 6 backend automated tests: 59 passed in 8.24 seconds on Python 3.12.8. Measured statement coverage was 90% overall (992 statements, 97 missed) and 97% for the ingestion module (297 statements, 10 missed). One upstream Starlette/AnyIO deprecation warning remains.
- Day 6 frontend regression checks: ESLint and TypeScript checking passed; 4 tests passed in one Vitest file; the production build transformed 16 modules and produced a 147.11 kB JavaScript bundle (48.08 kB gzip); the locked dependency audit found 0 known vulnerabilities.
- Complete Alembic offline render: passed; 455 SQL lines rendered all four revisions through `20261013_0004`, including idempotency-key and terminal-total checks.
- Day 6 migration and seed: Alembic reported `20261013_0004 (head)` and the synthetic seed completed successfully.
- Live idempotency path: the first four-row quality request returned HTTP 201 with accepted/rejected/duplicate/conflict counts `1/1/1/1` and acceptance rate `25.00`; its exact retry returned HTTP 200, the same batch ID, and `idempotent_replay: true`.
- Live changed-payload path: reusing the key with changed content returned HTTP 409 and `IDEMPOTENCY_KEY_REUSED`.
- Live prior-batch quality path: a new key for the same payload returned HTTP 201 with counts `0/1/2/1`; only one `JSON-QUALITY-*` financial transaction existed across both batches.
- Live retry persistence proof: the exact-retry key had exactly one batch, four evidence rows, and one transaction after retry.
- Live database safeguards: PostgreSQL rejected an impossible terminal total through `ck_batches_terminal_totals` and a duplicate `(account_id, source_record_id)` through `uq_transactions_source`.
- Live platform check: API readiness reported PostgreSQL and Redis `up`, the frontend returned HTTP 200, the Celery worker returned `pong`, and all five Compose services were running with API/PostgreSQL/Redis/worker healthy.
- Day 1–6 structural validators: passed.
- Final Markdown local-link validation: passed; 19 Markdown files checked with no broken local links.
- Final secret-pattern review: passed; 86 tracked or unignored paths checked with no matching private-key, AWS access-key, GitHub token, OpenAI-style API-key, or Google API-key patterns.
- Final Git whitespace/error check: passed with no findings.
- Day 5 backend formatting: passed; 21 source, test, and migration files were already formatted after the import-order correction.
- Day 5 backend linting: passed with no Ruff findings.
- Day 5 strict type checking: passed; no issues in 10 source files.
- Day 5 backend automated tests: 50 passed in 4.13 seconds on Python 3.12.8. Measured statement coverage was 90% overall (908 statements, 94 missed) and 97% for the ingestion module (213 statements, 7 missed). One upstream Starlette/AnyIO deprecation warning remains.
- Day 5 frontend regression checks: ESLint and TypeScript checking passed; 4 tests passed in one Vitest file; the production build transformed 16 modules and produced a 147.11 kB JavaScript bundle (48.08 kB gzip); the locked dependency audit found 0 known vulnerabilities.
- Complete Alembic offline render: passed; 451 SQL lines rendered all three revisions through `20261013_0003`, including the non-null `rejection_details` JSONB column and final commit.
- Day 5 migration and seed: Alembic reported `20261013_0003 (head)`; the synthetic seed completed successfully twice.
- Live JSON ingestion: HTTP 201 with one accepted and one rejected row; the rejected row deterministically returned `INVALID_AMOUNT`, `INVALID_CURRENCY`, and `INVALID_TIMESTAMP`.
- Live CSV ingestion: HTTP 201 with two accepted and zero rejected rows from the published valid fixture. PostgreSQL contained exactly two evidence rows and two transactions for that batch.
- Live persistence evidence: the mixed batch stored exactly two evidence rows and one transaction; `42.125000` remained exact and `2026-10-13T10:00:00+08:00` was stored as `2026-10-13 02:00:00+00`.
- Live least-privilege check: the auditor ingestion request returned HTTP 403.
- Live platform check: API readiness reported PostgreSQL and Redis `up`, the frontend returned HTTP 200, the Celery worker returned `pong`, and all five Compose services were running with API/PostgreSQL/Redis/worker healthy.
- Day 1–5 structural validators: passed.
- Final Markdown local-link validation: passed; 18 Markdown files checked with no broken local links.
- Final secret-pattern review: passed; 82 tracked or unignored paths checked with no matching private-key, AWS access-key, GitHub token, OpenAI-style API-key, or Google API-key patterns.
- Final Git whitespace/error check: passed with no findings.
- Day 4 backend formatting: passed; 18 files already formatted after applying Ruff to 4 new/changed files.
- Day 4 backend linting: passed with no Ruff findings.
- Day 4 strict type checking: passed; no issues in 9 source files.
- Day 4 backend automated tests: 28 passed in 6.95 seconds on Python 3.12.8. Measured statement coverage was 87% (691 statements, 87 missed).
- Day 4 frontend linting and TypeScript checking: passed with no findings.
- Day 4 frontend automated tests: 4 passed in one file with Vitest 5.0.3.
- Day 4 frontend production build: passed with Vite 8.3.3; 16 modules transformed and a 147.11 kB JavaScript bundle produced (48.08 kB gzip).
- Day 4 frontend locked-dependency audit: passed with 0 known vulnerabilities, including development dependencies.
- Complete Alembic offline render: passed; 513 SQL lines rendered both revisions through `20261009_0002` and committed the revision update.
- Day 4 migration and seed: Alembic reported `20261009_0002 (head)`; running the seed twice left exactly 3 users and 3 active role grants.
- Live authentication matrix: bad and disabled logins returned 401; expired and revoked sessions returned 401; administrator access was 200/200/200, analyst access 403/200/403, and auditor access 403/403/200 for administration/operations/audit respectively.
- Live application smoke check: frontend returned HTTP 200 and API readiness returned `ready`.
- Persistence and worker checks: all three user password hashes matched the Argon2id format, all stored session digests were 64 characters, and the Celery worker returned `pong` while all five services were healthy.
- Day 1–4 structural validators: passed.
- Final Markdown local-link validation: passed; 16 Markdown files checked with no broken local links.
- Final secret-pattern review: passed with no matching private-key, AWS access-key, GitHub token, OpenAI-style API-key, or Google API-key patterns.
- Final Git whitespace/error check: passed with no findings.

## Known issues

- MFA, password reset, external identity-provider integration, and authentication rate limiting are not implemented; rate limiting and the wider threat review are scheduled for Day 16.
- The unresolved-case report is intentionally a current-state queue bounded by case creation cutoff; it is not a historical status-as-of reconstruction. A historical snapshot would require replaying case status history and is outside Day 13 scope.
- Fraud thresholds and scores are deterministic demonstration controls, not validated fraud policy, probability estimates, or claims of detection accuracy.
- Retention periods are unratified design assumptions pending Day 16; the production queue choice remains a Day 19 decision.
- Some cross-row invariants (for example, retaining one administrator and classification-specific reconciliation membership) require transactional service checks and concurrency tests in the relevant later feature days.
- The pinned Starlette test client emits one upstream AnyIO deprecation warning. It does not fail the test suite.
- Running-job cancellation is cooperative at defined safe checkpoints; work already inside an atomic financial commit is allowed to finish rather than being terminated mid-transaction.
- The current local Redis/Celery topology is suitable for development. The managed production queue and recovery runbook remain a Day 19 deployment decision.
- The JSON ingestion envelope accepts at most 10,000 records and CSV uploads remain capped at 2 MB by default. Day 17 will publish controlled throughput and resilience measurements rather than extrapolating from the Day 9 local smoke measurement.
- The isolated Day 7 settlement facts are loaded by a production-blocked synthetic seeder. A public settlement-ingestion contract is not yet implemented and must exist before production deployment.
- No manual rendered screenshot was captured for Day 11; interface behaviour was exercised through 17 component tests, a production build, and live API/role checks.
- Playwright browser binaries are intentionally not part of the repository; local browser journeys require the documented one-time `npx playwright install chromium` download. CI installs Chromium in its isolated runner.
- A commit cannot embed its own final Git hash without changing that hash. This file therefore identifies the latest completed daily commit as `HEAD`; the exact short hash is reported after commit and can always be resolved with `git rev-parse --short HEAD`.

## Blockers

None for Day 14. Automated unit, component, API, PostgreSQL, Redis, Celery, Chromium, container-build, and production-build verification completed using synthetic data.

## Notion synchronization

Day 14 Notion synchronization remains explicitly pending. A previous connector attempt rejected exporting project, test, and commit details without direct authorization for that payload and destination; this repository record remains authoritative until the user authorizes that external write.

## Next day's objective

Day 15 will add structured and redacted logs, request/job correlation, metrics, traces, dependency-aware health checks, an operational dashboard, and a demonstrated API-to-worker failure trace.

## Latest commit hash

`HEAD` — the commit containing this progress record. Resolve with:

```powershell
git rev-parse --short HEAD
```
