# LedgerGuard

LedgerGuard is a production-oriented transaction reconciliation and fraud-monitoring platform. It will ingest financial transaction and settlement data, reject invalid records, prevent duplicate processing, produce explainable reconciliation outcomes, flag deterministic fraud signals, and give analysts an auditable case-management workflow.

The project uses synthetic demonstration data only. It must not contain real financial, customer, or personal information.

## Current state

Day 16 is complete: the security review now documents trust boundaries, threats, retention,
repairs, and residual risks. The API enforces host, body-size, secure-header, synthetic-source, and
Redis-backed request-rate controls; logs receive wider key/value redaction; and Compose separates
the schema-owning migration identity from the non-owner API/worker database role. CI now performs
Python and npm dependency audits plus a tracked-file credential-pattern scan.

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

The detailed [domain/data model](docs/architecture/DATA_MODEL.md), [entity-relationship diagram](docs/architecture/ERD.md), [authentication/access design](docs/security/AUTHENTICATION_AND_ACCESS.md), [security and privacy review](docs/security/SECURITY_AND_PRIVACY.md), [transaction ingestion schema](docs/api/TRANSACTION_INGESTION_V1.md), [idempotency/data-quality contract](docs/api/IDEMPOTENCY_AND_DATA_QUALITY.md), [reconciliation contract](docs/api/RECONCILIATION_V1.md), [background-processing contract](docs/architecture/BACKGROUND_PROCESSING.md), [case-management contract](docs/architecture/CASE_MANAGEMENT.md), [audit-logging contract](docs/architecture/AUDIT_LOGGING.md), [reporting/export contract](docs/architecture/REPORTING_AND_EXPORT.md), [automated test strategy](docs/architecture/TEST_STRATEGY.md), [observability contract](docs/architecture/OBSERVABILITY.md), [analyst dashboard contract](docs/ui/ANALYST_DASHBOARD.md), and architecture decision records under `docs/decisions/` define the current contracts.

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

Open the interface at `http://localhost:5173`, API documentation at
`http://localhost:8000/docs`, Prometheus at `http://localhost:9090`, and the provisioned
read-only Grafana dashboard at `http://localhost:3000`. Seed reference roles, one synthetic
account, and the three synthetic users with:

```powershell
docker compose exec api ledgerguard-seed
```

For the unchanged local Docker defaults, sign in with `admin@ledgerguard.invalid`, `analyst@ledgerguard.invalid`, or `auditor@ledgerguard.invalid` and the local-only password `DemoOnly!ChangeMe123456`. Override `DEMO_USER_PASSWORD` in an untracked `.env` before sharing the environment. These credentials are blocked from production use.

For native tooling, install dependencies and run all checks:

```powershell
./scripts/bootstrap.ps1
./scripts/check.ps1
```

With the seeded Docker stack running, install Chromium once and run the three role journeys:

```powershell
cd frontend
npx playwright install chromium
npm run test:e2e
```

See [local development](docs/operations/LOCAL_DEVELOPMENT.md) for service, migration, health, configuration, and shutdown details. `.env` is optional for the safe local defaults and must never be committed.

After signing in as the synthetic analyst, submit either published fixture under `sample-data/` to the matching `/api/v1/ingestion/transactions/json` or `/api/v1/ingestion/transactions/csv` endpoint. The [version 1 ingestion contract](docs/api/TRANSACTION_INGESTION_V1.md) documents exact fields, outcomes, and stable rejection codes.

Run `docker compose exec api ledgerguard-seed-reconciliation` to add the isolated synthetic Day 7 scenario, then queue a run through `POST /api/v1/reconciliation/runs` with an `Idempotency-Key`. Poll the returned `/api/v1/jobs/{job_id}` link until it reaches a terminal state. The [version 1 reconciliation contract](docs/api/RECONCILIATION_V1.md) documents matching and evidence; the [background-processing contract](docs/architecture/BACKGROUND_PROCESSING.md) documents delivery, retries, progress, cancellation, and permissions.

Run `docker compose exec api ledgerguard-seed-fraud` to add the isolated Day 10 rules and positive/negative transaction scenarios. Use the Fraud alerts workspace or `POST /api/v1/fraud/evaluations`; an exact repeat is idempotent. The [fraud-rule engine contract](docs/architecture/FRAUD_RULE_ENGINE.md) defines parameters, deterministic context, scores, evidence, edge cases, and access boundaries.

After fraud evaluation, use the Cases workspace to create a case from an unclaimed synthetic alert. Analysts can filter by owner, status, priority, rule, and age; assign the case to themselves; add investigation notes; and apply only the next valid lifecycle actions. The [case-management contract](docs/architecture/CASE_MANAGEMENT.md) defines concurrency, transitions, resolution effects, and role boundaries.

Sign in as the synthetic auditor and open Audit history to filter immutable events or reconstruct a case from transaction ingestion through alert generation and resolution. The [audit-logging contract](docs/architecture/AUDIT_LOGGING.md) defines required fields, redaction, append-only enforcement, and access boundaries.

Open Reports as any supported role to select a UTC date, review independently verified transaction and settlement totals, inspect the latest reconciliation snapshot, and export safe daily or unresolved-case CSV files. A fresh reconciliation seed places its fixed source facts on `2026-01-15` UTC. The [reporting/export contract](docs/architecture/REPORTING_AND_EXPORT.md) defines scope, cutoff, total verification, explicit fields, and spreadsheet-injection controls.

After the seed and first reconciliation run, sign in through `http://localhost:5173` as the synthetic analyst to review the operational dashboard. Non-exact results are prioritised by decimal-safe unresolved exposure; search, classification, and sort controls lead to the canonical evidence panel. The synthetic auditor sees the same evidence without run controls.

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
- `docs/security/SECURITY_AND_PRIVACY.md` — threat model, repaired findings, retention, and residual risks
- `docs/api/TRANSACTION_INGESTION_V1.md` — versioned JSON/CSV ingestion contract and rejection catalogue
- `docs/api/IDEMPOTENCY_AND_DATA_QUALITY.md` — retry, duplicate, conflict, fingerprint, and quality-summary semantics
- `docs/api/RECONCILIATION_V1.md` — deterministic matching, evidence, replay, and permission contract
- `docs/architecture/BACKGROUND_PROCESSING.md` — durable jobs, delivery, retries, cancellation, and worker operations
- `docs/architecture/CASE_MANAGEMENT.md` — investigation aggregate, lifecycle, concurrency, queue, and permission contract
- `docs/architecture/AUDIT_LOGGING.md` — structured event vocabulary, evidence limits, append-only enforcement, and auditor timeline contract
- `docs/architecture/REPORTING_AND_EXPORT.md` — UTC report scope, independent total verification, fixed CSV fields, and spreadsheet safety
- `docs/architecture/TEST_STRATEGY.md` — risk matrix, test layers, role journeys, CI isolation, and acceptance gates
- `docs/architecture/OBSERVABILITY.md` — log, correlation, metric, trace, health, dashboard, and failure-drill contracts
- `docs/ui/ANALYST_DASHBOARD.md` — dashboard metrics, states, role behaviour, prioritisation, and acceptance matrix

## License and usage

No license has been selected. Treat the repository as private unless the owner explicitly chooses otherwise.
