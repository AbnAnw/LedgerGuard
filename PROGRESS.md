# LedgerGuard Progress

## Current roadmap day

**Day 1 — Product definition and repository creation: Complete**

## Completed days

- **Day 1 (2026-10-06):** Created the repository on `main`; defined roles and workflows; documented acceptance criteria, scope, exclusions, success metrics, risks, architecture, engineering conventions, development environment, repository rules, and the complete delivery plan; added an automated structural validator.

## Current architecture

LedgerGuard is planned as a modular monolith: a React/TypeScript interface calls a FastAPI API, PostgreSQL holds authoritative domain and audit data, and Redis/Celery runs idempotent asynchronous work. OpenTelemetry supplies correlated telemetry to Prometheus/Grafana. Docker Compose is the local reference; GCP-specific deployment concerns remain isolated. Application code begins after Day 2 formalises the domain model.

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

## Commands required to run the system

There is no application runtime on Day 1. Validate the repository from its root:

```powershell
./scripts/validate-day-01.ps1
```

Day 3 will add the clean-clone Docker Compose startup, migration, seed, lint, type-check, test, and build commands. Configuration placeholders are documented in `.env.example`; `.env` must remain untracked.

## Test and coverage results

- Day 1 structural/specification validation: passed; 19 required paths, 21 roadmap days, required product topics, placeholder environment values, synthetic-data notice, and `main` branch verified.
- Git whitespace/error check: passed with no findings.
- Markdown local-link validation: passed; 7 Markdown files checked with no broken local links.
- Secret-pattern review: passed; 20 candidate files checked with no matching private-key, AWS access-key, GitHub token, or OpenAI-style API-key patterns.
- Automated test coverage: not applicable yet; there is no executable product code on Day 1. No coverage percentage is claimed.

## Known issues

- Application code, containers, database schema, authentication, and runtime quality tooling intentionally begin on later roadmap days.
- Fraud thresholds are demonstration values to be defined later and must not be represented as validated risk policy.
- Data retention periods and the production queue choice require later decisions and documentation.
- A commit cannot embed its own final Git hash without changing that hash. This file therefore identifies the latest completed daily commit as `HEAD`; the exact short hash is reported after commit and can always be resolved with `git rev-parse --short HEAD`.

## Blockers

None for Day 1.

## Next day's objective

Day 2 will define the complete domain/data model, lifecycle statuses, relationships, decimal precision, UTC timestamp conventions, indexes, retention assumptions, an entity-relationship diagram, and ADRs for money, identifiers, and audit history.

## Latest commit hash

`HEAD` — the commit containing this progress record. Resolve with:

```powershell
git rev-parse --short HEAD
```
