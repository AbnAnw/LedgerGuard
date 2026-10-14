# Local Development

## Supported environment

- Docker Engine with Docker Compose v2 (supported clean-clone path)
- Python 3.12 for native backend development
- Node.js 20.19.x or 22.13 through 22.x, plus npm, for native frontend development
- Git plus PowerShell 7 or Windows PowerShell 5.1 for repository scripts

Runtime images are pinned to Python 3.12.8, Node 22.13.1, PostgreSQL 16.4, Redis 7.4.1, and Nginx 1.27.3. Application dependencies are exactly pinned in `backend/pyproject.toml` and `frontend/package-lock.json`.

## Clean-clone startup with Docker Compose

No `.env` file is required for the synthetic local defaults. To customise ports or credentials, copy `.env.example` to `.env` and replace the placeholders first.

```powershell
docker compose up --build
```

The API container waits for PostgreSQL and Redis, applies the Alembic migration, then starts FastAPI. The worker starts after the API becomes healthy. Host ports bind only to the loopback interface. The frontend is available at `http://localhost:5173`, OpenAPI at `http://localhost:8000/docs`, liveness at `http://localhost:8000/health/live`, and dependency readiness at `http://localhost:8000/health/ready`.

Seed the three roles, a synthetic demonstration account, and three synthetic users after the stack is healthy:

```powershell
docker compose exec api ledgerguard-seed
```

The seed is idempotent. The local Docker default password is `DemoOnly!ChangeMe123456` for `admin@ledgerguard.invalid`, `analyst@ledgerguard.invalid`, and `auditor@ledgerguard.invalid`. Set `DEMO_USER_PASSWORD` in an untracked `.env` to replace it. The seed refuses to run when `APP_ENV=production`.

## Try transaction ingestion

Sign in as the synthetic operations analyst and retain the returned bearer token:

```powershell
$login = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth/login -ContentType 'application/json' -Body (@{
    email = 'analyst@ledgerguard.invalid'
    password = 'DemoOnly!ChangeMe123456'
} | ConvertTo-Json)
$headers = @{ Authorization = "Bearer $($login.access_token)" }
```

Submit the valid JSON fixture:

```powershell
$headers['Idempotency-Key'] = 'local-json-example-001'
$job = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/ingestion/transactions/json -Headers $headers -ContentType 'application/json' -InFile ./sample-data/transactions-valid-v1.json
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/v1/jobs/$($job.job_id)" -Headers $headers
```

The CSV endpoint accepts `schema_version`, `source_system`, and `source_account_id` as form fields alongside a `file` upload. OpenAPI at `http://localhost:8000/docs` provides an interactive form. Both endpoints use the same validation rules documented in the [version 1 ingestion contract](../api/TRANSACTION_INGESTION_V1.md).

The API validates the envelope and returns HTTP 202 with a durable job receipt; row validation and CSV parsing run in Celery. JSON batches remain limited to 10,000 rows and CSV uploads to 2 MB by default. Configure the byte limit with `INGESTION_MAX_UPLOAD_BYTES`. Repeating the same key and content returns the original job without creating rows; changing content while reusing the key returns HTTP 409. Use a new key to intentionally submit a new batch, where repeated source identifiers are classified as duplicates or conflicts.

## Try deterministic reconciliation

Seed the isolated synthetic Day 7 account and its transaction/settlement facts. The command is
idempotent and refuses to run in production:

```powershell
docker compose exec api ledgerguard-seed-reconciliation
```

Using the analyst login and `$headers` from above, create a run:

```powershell
$request = @{
    source_system = 'synthetic-reconciliation'
    source_account_id = 'DEMO-RECON-001'
    input_cutoff_at = '2026-10-14T12:00:00Z'
    match_window_hours = 72
} | ConvertTo-Json
$headers['Idempotency-Key'] = 'local-reconciliation-example-001'
$job = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/reconciliation/runs -Headers $headers -ContentType 'application/json' -Body $request
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/v1/jobs/$($job.job_id)" -Headers $headers
```

The queued scenario produces one exact, partial, missing, duplicate-candidate, and unexplained result.
Repeating the same key and request returns the same job. Auditors may read reconciliation jobs and
stored runs but receive HTTP 403 when creating or cancelling one. See the
[reconciliation v1 contract](../api/RECONCILIATION_V1.md) and
[background-processing contract](../architecture/BACKGROUND_PROCESSING.md).

## Use the analyst dashboard

Open `http://localhost:5173`, sign in as `analyst@ledgerguard.invalid`, and use the reconciliation
workspace to review summary values, batch quality, prioritised discrepancies, and canonical evidence.
The default sort puts non-exact results with the greatest unresolved exposure first. All displayed
times are labelled UTC and all money remains decimal strings; the browser uses scaled `BigInt` only
for ordering. Sign in as the synthetic auditor to verify the same evidence is read-only.

The dashboard selects the completed run with the newest effective input cutoff. Creating a
historical run later therefore cannot replace newer operational evidence. The fixed reconciliation
fixture is intentionally dated in the past so a clean-clone “run now” includes it.

Stop services without deleting their named data volumes:

```powershell
docker compose down
```

Deleting volumes is intentionally not part of the normal workflow because it destroys local database state.

## Native development

Install the backend and frontend development dependencies:

```powershell
./scripts/bootstrap.ps1
```

PostgreSQL and Redis must still be reachable using `DATABASE_URL` and `REDIS_URL`. Run all local quality checks:

```powershell
./scripts/check.ps1
```

Individual services can be started from their directories:

```powershell
cd backend
./.venv/Scripts/alembic.exe upgrade head
./.venv/Scripts/uvicorn.exe ledgerguard.main:app --reload

cd ../frontend
npm run dev
```

Start a native worker from `backend/`:

```powershell
./.venv/Scripts/celery.exe -A ledgerguard.worker.celery_app worker --loglevel=INFO
```

Inspect the Compose worker and run the opt-in PostgreSQL/Redis/Celery integration checks:

```powershell
docker compose exec worker celery -A ledgerguard.worker.celery_app inspect ping --timeout 10
docker run --rm --network ledgerguard_default `
  -e LEDGERGUARD_RUN_INTEGRATION=1 `
  -e DATABASE_URL=postgresql+psycopg://ledgerguard:ledgerguard-local-only@postgres:5432/ledgerguard `
  -e REDIS_URL=redis://redis:6379/0 `
  -e CELERY_BROKER_URL=redis://redis:6379/0 `
  -v "${PWD}/backend:/app" -w /app ledgerguard-api `
  pytest -q -p no:cacheprovider tests/test_background_integration.py
```

Use `.env` values instead of the displayed local-only placeholders when you customise Compose.

## Migration and seed commands

Create schema:

```powershell
cd backend
./.venv/Scripts/alembic.exe upgrade head
./.venv/Scripts/ledgerguard-seed.exe
./.venv/Scripts/ledgerguard-seed-reconciliation.exe
```

Render the migration as PostgreSQL SQL without connecting to a database:

```powershell
./.venv/Scripts/alembic.exe upgrade head --sql
```

Schema changes must be represented by a new Alembic revision. Never modify a migration already applied outside an isolated local environment.

## Configuration and data safety

1. Replace local placeholders before any shared or production-like deployment; never reuse production secrets locally.
2. Keep `.env` untracked. The committed `.gitignore` protects `.env` variants while allowing `.env.example`.
3. Production mode rejects the documented development authentication secret.
4. Production mode rejects the documented demonstration password, and the seed command refuses to create demonstration users.
5. Use only generated synthetic data under `sample-data/`.
6. Treat logs, exports, database dumps, and uploaded fixtures as untrusted local artifacts and do not commit them.

## Time and money conventions

- Persist and exchange timestamps in UTC. The interface may display a chosen time zone only with an explicit label.
- Represent money as decimal strings at API/JavaScript boundaries, `Decimal` in Python, and fixed-precision `NUMERIC` in PostgreSQL.
- Never convert monetary amounts to Python `float` or JavaScript `number` for calculation.

## Health semantics

- `/health/live` proves only that the API process is serving requests.
- `/health/ready` probes PostgreSQL and Redis and returns HTTP 503 if either dependency is unavailable.
- Health failures expose only `up`/`down` state; driver messages and credentials are not returned.
- The Celery container health check uses a targeted worker ping.
