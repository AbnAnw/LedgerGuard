"""Dependency probes used by readiness checks."""

from time import perf_counter
from typing import Literal, TypedDict

from redis import Redis
from sqlalchemy import text

from ledgerguard.config import get_settings
from ledgerguard.db import engine


class DependencyState(TypedDict):
    status: Literal["up", "down"]
    latency_ms: float


class ReadinessState(TypedDict):
    status: Literal["ready", "not_ready"]
    dependencies: dict[str, DependencyState]


def probe_dependencies() -> ReadinessState:
    """Probe authoritative dependencies without returning internal error details."""

    dependencies: dict[str, DependencyState] = {
        "database": {"status": "down", "latency_ms": 0.0},
        "redis": {"status": "down", "latency_ms": 0.0},
    }

    database_started = perf_counter()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        pass
    else:
        dependencies["database"]["status"] = "up"
    finally:
        dependencies["database"]["latency_ms"] = round(
            (perf_counter() - database_started) * 1000, 3
        )

    client: Redis | None = None
    redis_started = perf_counter()
    try:
        client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=1)
        client.ping()
    except Exception:
        pass
    else:
        dependencies["redis"]["status"] = "up"
    finally:
        dependencies["redis"]["latency_ms"] = round((perf_counter() - redis_started) * 1000, 3)
        if client is not None:
            client.close()  # type: ignore[no-untyped-call]

    ready = all(state["status"] == "up" for state in dependencies.values())
    return {"status": "ready" if ready else "not_ready", "dependencies": dependencies}
