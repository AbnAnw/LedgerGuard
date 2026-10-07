"""Celery worker application and baseline diagnostic task."""

from datetime import UTC, datetime

from celery import Celery  # type: ignore[import-untyped]

from ledgerguard import __version__
from ledgerguard.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ledgerguard",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    enable_utc=True,
    timezone="UTC",
    task_track_started=True,
)


@celery_app.task(name="ledgerguard.worker.ping")  # type: ignore[misc]
def ping() -> dict[str, str]:
    """Return deterministic worker build metadata without external side effects."""

    return {
        "status": "ok",
        "service": "ledgerguard-worker",
        "version": __version__,
        "checked_at": datetime.now(UTC).isoformat(),
    }
