# Local Development

## Day 1 environment

Day 1 is documentation-only and requires Git plus PowerShell 7 or Windows PowerShell 5.1. There are no packages to install and no services to start. Run:

```powershell
./scripts/validate-day-01.ps1
```

The validator checks the planned repository layout, required planning documents, roadmap statuses, safe environment template, synthetic-data notice, and Git branch.

## Planned Day 3 environment

Day 3 will pin and document the runtime versions for:

- Docker Engine with Docker Compose v2
- Python and the backend dependency manager
- Node.js and the frontend package manager
- PostgreSQL, Redis, FastAPI, React, Celery, SQLAlchemy, and Alembic

The supported startup path will be Docker Compose from a clean clone. Native commands may be added for faster iteration but will not replace the reproducible container path.

## Configuration safety

1. Copy `.env.example` to `.env` only when runtime services exist.
2. Replace placeholder local credentials; never reuse a production secret.
3. Keep `.env` untracked. The committed `.gitignore` protects `.env` variants while allowing `.env.example`.
4. Use only generated synthetic data under `sample-data/`.
5. Treat logs, exports, database dumps, and uploaded fixtures as untrusted local artifacts and do not commit them.

## Time and money conventions

- Persist and exchange timestamps in UTC. The future interface will display a chosen time zone with an explicit label.
- Represent money as decimal strings at API/JavaScript boundaries, `Decimal` in Python, and fixed-precision `NUMERIC` in PostgreSQL.
- Never convert monetary amounts to Python `float` or JavaScript `number` for calculation.
