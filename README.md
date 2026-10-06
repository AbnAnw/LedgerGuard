# LedgerGuard

LedgerGuard is a production-oriented transaction reconciliation and fraud-monitoring platform. It will ingest financial transaction and settlement data, reject invalid records, prevent duplicate processing, produce explainable reconciliation outcomes, flag deterministic fraud signals, and give analysts an auditable case-management workflow.

The project uses synthetic demonstration data only. It must not contain real financial, customer, or personal information.

## Current state

Day 1 is complete: the product boundary, user workflows, acceptance criteria, architecture, risks, success measures, repository conventions, and 21-day delivery plan are documented. Runtime services begin on Day 3 after the domain model is designed on Day 2.

## Users and least privilege

| Role | Intended capabilities | Explicit restrictions |
| --- | --- | --- |
| Administrator | Manage users, access, fraud rules, and system configuration; review operational health and audit events | Does not silently bypass audit history; investigation actions require explicit permission |
| Operations analyst | Upload data, monitor batches, run reconciliation, investigate alerts, manage assigned cases, and export permitted reports | Cannot manage users or security settings; cannot mutate audit history |
| Auditor | Read transactions, reconciliation evidence, alerts, cases, reports, and audit history | Read-only; cannot upload, rerun, assign, comment, resolve, configure, or administer |

Authorization will be enforced by the API as the security boundary and mirrored in the interface for usability.

## Intended architecture

- React and TypeScript single-page application
- FastAPI modular monolith using SQLAlchemy and Alembic
- PostgreSQL as the system of record
- Redis-backed Celery workers for parsing, reconciliation, reporting, and fraud evaluation
- Docker Compose for local dependencies and service orchestration
- pytest and Playwright for backend, integration, and end-to-end coverage
- Ruff, ESLint, and TypeScript checks for static quality
- OpenTelemetry plus Prometheus and Grafana for traces, metrics, and operational dashboards
- GCP Cloud Run as the intended deployment target, isolated behind deployment configuration and adapters

See [the product specification](docs/PRODUCT_SPEC.md), [the architecture overview](docs/architecture/OVERVIEW.md), and [the complete roadmap](PROJECT_PLAN.md).

## Repository map

```text
backend/             FastAPI application (begins Day 3)
frontend/            React/TypeScript application (begins Day 3)
worker/              Celery task entry points and worker-specific code
tests/               Cross-service integration and end-to-end tests
docs/architecture/   System design and diagrams
docs/decisions/      Architecture decision records
docs/security/       Threat model, privacy, and security guidance
docs/operations/     Local and production runbooks
sample-data/         Synthetic input and expected outcomes only
scripts/             Repeatable developer and validation commands
infra/               Local and cloud deployment configuration
.github/workflows/   Continuous integration definitions
```

Empty implementation directories contain `.gitkeep` files so the planned layout is visible before code arrives.

## Getting started today

Day 1 has no application runtime or third-party dependencies. Validate the specification from PowerShell:

```powershell
./scripts/validate-day-01.ps1
```

For future local development, copy `.env.example` to `.env` and replace the local-only placeholders. Day 3 will add the supported Docker Compose startup and quality-check commands. Do not use production secrets locally or commit `.env`.

## Engineering principles

- Monetary values use decimal-safe representations end to end; binary floating point is forbidden for money.
- Timestamps are persisted and exchanged in UTC. User-selected display time zones are presentation-only and are shown explicitly.
- External input is schema-validated, while critical uniqueness and integrity rules are also enforced in PostgreSQL.
- Ingestion requests and worker tasks are idempotent and safe under retries or duplicate delivery.
- Reconciliation and fraud outputs retain inputs, rule/version metadata, decision reasons, and correlation identifiers.
- Structured logs carry request or job correlation IDs and redact secrets and sensitive values.
- Modules remain cohesive within a modular monolith until measured constraints justify another boundary.

## Documentation

- `PROJECT_PLAN.md` — Day 1–21 status and completion criteria
- `PROGRESS.md` — current state, commands, results, issues, and next objective
- `docs/PRODUCT_SPEC.md` — workflows, acceptance criteria, scope, metrics, and risks
- `docs/architecture/OVERVIEW.md` — intended components, trust boundaries, data flow, and deployment shape
- `docs/operations/LOCAL_DEVELOPMENT.md` — current development environment and safety rules

## License and usage

No license has been selected. Treat the repository as private unless the owner explicitly chooses otherwise.
