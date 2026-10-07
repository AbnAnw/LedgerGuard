"""Dependency probes used by readiness checks."""

from typing import Literal, TypedDict

from redis import Redis
from sqlalchemy import text

from ledgerguard.config import get_settings
from ledgerguard.db import engine


class DependencyState(TypedDict):
    status: Literal["up", "down"]


class ReadinessState(TypedDict):
    status: Literal["ready", "not_ready"]
    dependencies: dict[str, DependencyState]


def probe_dependencies() -> ReadinessState:
    """Probe authoritative dependencies without returning internal error details."""

    dependencies: dict[str, DependencyState] = {
        "database": {"status": "down"},
        "redis": {"status": "down"},
    }

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        dependencies["database"] = {"status": "up"}
    except Exception:
        pass

    client: Redis | None = None
    try:
        client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=1)
        client.ping()
        dependencies["redis"] = {"status": "up"}
    except Exception:
        pass
    finally:
        if client is not None:
            client.close()  # type: ignore[no-untyped-call]

    ready = all(state["status"] == "up" for state in dependencies.values())
    return {"status": "ready" if ready else "not_ready", "dependencies": dependencies}
