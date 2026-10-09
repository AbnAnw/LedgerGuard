# LedgerGuard Progress

## Current roadmap day

**Day 4 — Authentication and role-based access: Complete**

## Completed days

- **Day 1 (2026-10-06):** Created the repository on `main`; defined roles and workflows; documented acceptance criteria, scope, exclusions, success metrics, risks, architecture, engineering conventions, development environment, repository rules, and the complete delivery plan; added an automated structural validator.
- **Day 2 (2026-10-06):** Defined 20 database entities spanning identity, ingestion, financial facts, reconciliation, fraud monitoring, investigations, and audit; documented lifecycles, relationships, precision, UTC handling, constraints, indexes, retention assumptions, a Mermaid ER diagram, and accepted ADRs for money, identifiers, and audit history.
- **Day 3 (2026-10-07):** Implemented the FastAPI and React/TypeScript foundations; configured PostgreSQL, Redis, Celery, and a five-service Docker Compose stack; added validated settings, SQLAlchemy models, the explicit initial Alembic migration, idempotent synthetic seeding, health endpoints, pinned development tooling, automated checks, and clean-clone setup documentation.
- **Day 4 (2026-10-09):** Added Argon2id password hashing, opaque bearer sessions stored as keyed digests, PostgreSQL-backed expiry and logout revocation, login lockout handling, synthetic demonstration users, deny-by-default permissions, protected API boundaries, and a role-aware interface.

## Current architecture

LedgerGuard is a modular monolith with a React/TypeScript interface, FastAPI API, PostgreSQL system of record, and Redis/Celery worker. Docker Compose defines the five-service local platform. SQLAlchemy implements the domain model; two Alembic revisions provide the 20-table initial schema plus revocable authentication sessions, database constraints, and an append-only audit trigger. FastAPI is the authorization boundary, while the interface mirrors role access without persisting bearer tokens in browser storage. Validated settings use safe local defaults and environment overrides. GCP-specific deployment concerns remain isolated.

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
```

Configuration placeholders are documented in `.env.example`; `.env` must remain untracked.

The unchanged Docker defaults seed `admin@ledgerguard.invalid`, `analyst@ledgerguard.invalid`, and `auditor@ledgerguard.invalid` with the local-only password `DemoOnly!ChangeMe123456`. Override `DEMO_USER_PASSWORD` in `.env` before sharing the environment.

## Test and coverage results

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
- Authentication attempts are not yet written to append-only audit history; security-event auditing is scheduled for Day 12.
- Fraud thresholds are demonstration values to be defined later and must not be represented as validated risk policy.
- Retention periods are unratified design assumptions pending Day 16; the production queue choice remains a Day 19 decision.
- Some cross-row invariants (for example, retaining one administrator and classification-specific reconciliation membership) require transactional service checks and concurrency tests in the relevant later feature days.
- The pinned Starlette test client emits one upstream AnyIO deprecation warning. It does not fail the test suite.
- A commit cannot embed its own final Git hash without changing that hash. This file therefore identifies the latest completed daily commit as `HEAD`; the exact short hash is reported after commit and can always be resolved with `git rev-parse --short HEAD`.

## Blockers

None for Day 4.

## Notion synchronization

Pending for Day 4. No authenticated Notion workspace is available in this task. This progress record contains the concise status, decisions, measured tests, blockers, commit reference, and next-day objective needed for later synchronization.

## Next day's objective

Day 5 will implement versioned CSV and JSON transaction ingestion, strict external-input validation, accepted/rejected record persistence with stable reason codes, and deterministic synthetic batch tests.

## Latest commit hash

`HEAD` — the commit containing this progress record. Resolve with:

```powershell
git rev-parse --short HEAD
```
