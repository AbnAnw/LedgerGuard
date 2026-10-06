# LedgerGuard Progress

## Current roadmap day

**Day 2 — Domain and data model: Complete**

## Completed days

- **Day 1 (2026-10-06):** Created the repository on `main`; defined roles and workflows; documented acceptance criteria, scope, exclusions, success metrics, risks, architecture, engineering conventions, development environment, repository rules, and the complete delivery plan; added an automated structural validator.
- **Day 2 (2026-10-06):** Defined 20 database entities spanning identity, ingestion, financial facts, reconciliation, fraud monitoring, investigations, and audit; documented lifecycles, relationships, precision, UTC handling, constraints, indexes, retention assumptions, a Mermaid ER diagram, and accepted ADRs for money, identifiers, and audit history.

## Current architecture

LedgerGuard is a planned modular monolith: a React/TypeScript interface calls a FastAPI API, PostgreSQL holds authoritative domain and audit data, and Redis/Celery runs idempotent asynchronous work. The documented data model separates source-row outcomes from accepted financial facts, represents many-to-many reconciliation evidence without polymorphic foreign keys, versions fraud rules, preserves case timelines, and orders append-only audit events. OpenTelemetry supplies correlated telemetry to Prometheus/Grafana. Docker Compose is the local reference; GCP-specific deployment concerns remain isolated. Day 3 will implement the platform and initial migration from this contract.

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

## Commands required to run the system

There is no application runtime through Day 2. Validate the completed documentation milestones from the repository root:

```powershell
./scripts/validate-day-01.ps1
./scripts/validate-day-02.ps1
```

Day 3 will add the clean-clone Docker Compose startup, migration, seed, lint, type-check, test, and build commands. Configuration placeholders are documented in `.env.example`; `.env` must remain untracked.

## Test and coverage results

- Day 1 structural/specification validation: passed; 19 required paths, 21 roadmap days, required product topics, placeholder environment values, synthetic-data notice, and `main` branch verified.
- Git whitespace/error check: passed with no findings.
- Markdown local-link validation: passed; 7 Markdown files checked with no broken local links.
- Secret-pattern review: passed; 20 candidate files checked with no matching private-key, AWS access-key, GitHub token, or OpenAI-style API-key patterns.
- Day 2 model/ERD/ADR validation: passed; 5 required files, 20 entities, required conventions, Mermaid ER diagram, 3 accepted ADRs, and roadmap status verified.
- Markdown local-link validation after Day 2: passed; 12 Markdown files checked with no broken local links.
- Git whitespace/error check after Day 2: passed with no findings.
- Secret-pattern review after Day 2: passed; 26 candidate files checked with no matching private-key, AWS access-key, GitHub token, or OpenAI-style API-key patterns.
- Automated test coverage: not applicable yet; there is no executable product code through Day 2. No coverage percentage is claimed.

## Known issues

- Application code, containers, executable database schema, authentication, and runtime quality tooling intentionally begin on later roadmap days.
- Fraud thresholds are demonstration values to be defined later and must not be represented as validated risk policy.
- Retention periods are unratified design assumptions pending Day 16; the production queue choice remains a Day 19 decision.
- Some cross-row invariants (for example, retaining one administrator and classification-specific reconciliation membership) require transactional service checks and concurrency tests; Day 3 will decide whether any also justify deferred constraint triggers.
- A commit cannot embed its own final Git hash without changing that hash. This file therefore identifies the latest completed daily commit as `HEAD`; the exact short hash is reported after commit and can always be resolved with `git rev-parse --short HEAD`.

## Blockers

None for Day 2.

## Next day's objective

Day 3 will create the FastAPI and React/TypeScript applications, PostgreSQL/Redis/Celery services, Docker Compose environment, validated configuration, SQLAlchemy/Alembic foundation, initial schema migration, synthetic seed command, health endpoints, and baseline formatting, linting, typing, and smoke tests.

## Latest commit hash

`HEAD` — the commit containing this progress record. Resolve with:

```powershell
git rev-parse --short HEAD
```
