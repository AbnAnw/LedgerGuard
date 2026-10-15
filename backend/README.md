# LedgerGuard backend

The FastAPI application, SQLAlchemy model, Alembic migrations, seed command, and Celery application live here. The supported full-stack development path is Docker Compose from the repository root.

For local checks with Python 3.12 available:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m mypy src
./.venv/Scripts/python.exe -m pytest
```

Generate SQL without connecting to PostgreSQL:

```powershell
./.venv/Scripts/alembic.exe upgrade head --sql
```

After the base seed, load the isolated deterministic demonstrations with:

```powershell
ledgerguard-seed-reconciliation
ledgerguard-seed-fraud
```
