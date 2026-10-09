"""FastAPI application entry point."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ledgerguard import __version__
from ledgerguard.auth import access_router, auth_router
from ledgerguard.config import get_settings
from ledgerguard.health import ReadinessState, probe_dependencies

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Transaction reconciliation and fraud-monitoring API",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
)
app.include_router(auth_router)
app.include_router(access_router)


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
