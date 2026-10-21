"""FastAPI application entry point."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ledgerguard import __version__
from ledgerguard.audit import router as audit_router
from ledgerguard.auth import access_router, auth_router
from ledgerguard.cases import router as cases_router
from ledgerguard.config import get_settings
from ledgerguard.dashboard import router as dashboard_router
from ledgerguard.fraud import router as fraud_router
from ledgerguard.health import ReadinessState, probe_dependencies
from ledgerguard.ingestion import router as ingestion_router
from ledgerguard.jobs import router as jobs_router
from ledgerguard.metrics import render_metrics
from ledgerguard.observability import ObservabilityMiddleware, configure_observability
from ledgerguard.reconciliation import router as reconciliation_router
from ledgerguard.reports import router as reports_router
from ledgerguard.security import SecurityMiddleware

settings = get_settings()
configure_observability("ledgerguard-api")

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Transaction reconciliation and fraud-monitoring API",
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None if settings.app_env == "production" else "/redoc",
    openapi_url=None if settings.app_env == "production" else "/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
)
app.add_middleware(SecurityMiddleware, settings=settings)
app.add_middleware(ObservabilityMiddleware)
app.include_router(auth_router)
app.include_router(access_router)
app.include_router(ingestion_router)
app.include_router(reconciliation_router)
app.include_router(dashboard_router)
app.include_router(jobs_router)
app.include_router(fraud_router)
app.include_router(cases_router)
app.include_router(audit_router)
app.include_router(reports_router)


class LiveResponse(BaseModel):
    status: str
    service: str
    version: str
    checked_at: datetime


@app.get("/health/live", response_model=LiveResponse, tags=["health"])
def liveness() -> LiveResponse:
    """Confirm that the API process can serve requests."""

    return LiveResponse(
        status="alive",
        service=settings.app_name,
        version=__version__,
        checked_at=datetime.now(UTC),
    )


@app.get("/health/ready", response_model=ReadinessState, tags=["health"])
def readiness(
    state: Annotated[ReadinessState, Depends(probe_dependencies)],
) -> ReadinessState:
    """Confirm that PostgreSQL and Redis are reachable."""

    if state["status"] != "ready":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=state)
    return state


@app.get("/api/v1/meta", tags=["platform"])
def metadata() -> dict[str, str]:
    """Expose non-sensitive build metadata to the frontend."""

    return {"name": settings.app_name, "version": __version__, "environment": settings.app_env}


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    """Expose low-cardinality operational metrics for private Prometheus scraping."""

    return Response(render_metrics(), media_type="text/plain; version=0.0.4; charset=utf-8")
