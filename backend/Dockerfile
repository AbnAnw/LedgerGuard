FROM python:3.12.8-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN python -m venv /opt/venv
RUN pip install --no-cache-dir pip==26.2.2
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN addgroup --system ledgerguard && adduser --system --ingroup ledgerguard ledgerguard
USER ledgerguard

FROM base AS development
USER root
RUN pip install --no-cache-dir ".[dev]"
COPY alembic.ini ./
COPY migrations ./migrations
COPY tests ./tests
USER ledgerguard

FROM base AS production
CMD ["uvicorn", "ledgerguard.main:app", "--host", "0.0.0.0", "--port", "8000"]
