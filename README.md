# LedgerGuard

LedgerGuard is a production-oriented transaction reconciliation and fraud-monitoring platform. It will ingest financial transaction and settlement data, reject invalid records, prevent duplicate processing, produce explainable reconciliation outcomes, flag deterministic fraud signals, and give analysts an auditable case-management workflow.

The project uses synthetic demonstration data only. It must not contain real financial, customer, or personal information.

## Current state

Day 3 is complete: the FastAPI API, React/TypeScript interface, PostgreSQL schema, Redis/Celery worker foundation, Docker Compose environment, idempotent reference seed, health endpoints, and baseline quality toolchains are implemented.

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

The detailed [domain/data model](docs/architecture/DATA_MODEL.md), [entity-relationship diagram](docs/architecture/ERD.md), and architecture decision records under `docs/decisions/` are the contract for the Day 3 schema foundation.

## Repository map

```text
backend/             FastAPI, SQLAlchemy, Alembic, Celery, and backend tests
frontend/            React/TypeScript application, tests, and production build
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

## Getting started today

With Docker Engine and Docker Compose v2 installed, start from a clean clone:

```powershell
docker compose up --build
```

Open the interface at `http://localhost:5173` and API documentation at `http://localhost:8000/docs`. Seed reference roles and one clearly synthetic account with:

```powershell
docker compose exec api ledgerguard-seed
```

For native tooling, install dependencies and run all checks:

```powershell
./scripts/bootstrap.ps1
./scripts/check.ps1
```

See [local development](docs/operations/LOCAL_DEVELOPMENT.md) for service, migration, health, configuration, and shutdown details. `.env` is optional for the safe local defaults and must never be committed.

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
- `docs/architecture/DATA_MODEL.md` — entities, constraints, lifecycles, indexes, and retention assumptions
- `docs/architecture/ERD.md` — transaction-to-case relationship diagram
- `docs/decisions/` — accepted decisions for money, identifiers, audit history, and checked lifecycle values
- `docs/operations/LOCAL_DEVELOPMENT.md` — current development environment and safety rules

## License and usage

No license has been selected. Treat the repository as private unless the owner explicitly chooses otherwise.
