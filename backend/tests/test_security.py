import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from ledgerguard.config import Settings
from ledgerguard.main import app
from ledgerguard.security import (
    RateLimitDecision,
    SecurityMiddleware,
    enforce_synthetic_source,
)


class FakeLimiter:
    def __init__(self, decision: RateLimitDecision | Exception) -> None:
        self.decision = decision
        self.calls: list[tuple[str, int, int]] = []

    async def check(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        self.calls.append((key, limit, window_seconds))
        if isinstance(self.decision, Exception):
            raise self.decision
        return self.decision


def _app_with_security(settings: Settings, limiter: FakeLimiter) -> FastAPI:
    test_app = FastAPI()

    @test_app.get("/api/v1/example")
    def example() -> dict[str, str]:
        return {"status": "ok"}

    test_app.add_middleware(SecurityMiddleware, settings=settings, limiter=limiter)
    return test_app


def _production_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "production",
        "auth_secret_key": "production-auth-secret-with-more-than-32-characters",
        "demo_user_password": "unused-production-demo-password",
        "database_url": "postgresql+psycopg://ledgerguard_app:production-db-password@db/ledgerguard",
        "redis_url": "rediss://redis.internal:6379/0",
        "celery_broker_url": "rediss://redis.internal:6379/0",
        "celery_result_backend": "rediss://redis.internal:6379/1",
        "rate_limit_enabled": True,
        "allowed_hosts": ["ledgerguard.example"],
        "cors_origins": ["https://ledgerguard.example"],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_api_emits_secure_response_headers_and_rejects_untrusted_host() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/meta")
        invalid_host = client.get("/api/v1/meta", headers={"Host": "attacker.example"})

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert invalid_host.status_code == 400
    assert invalid_host.headers["x-request-id"]


def test_declared_request_size_is_rejected_before_endpoint_processing() -> None:
    settings = Settings(
        max_request_body_bytes=300_000, ingestion_max_upload_bytes=32_000, _env_file=None
    )
    limiter = FakeLimiter(RateLimitDecision(True, 10, 9, 60))
    test_app = _app_with_security(settings, limiter)

    with TestClient(test_app) as client:
        response = client.request(
            "GET",
            "/api/v1/example",
            headers={"Content-Length": "300001"},
        )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "REQUEST_TOO_LARGE"


def test_streamed_request_size_is_enforced_without_content_length() -> None:
    settings = Settings(
        max_request_body_bytes=300_000, ingestion_max_upload_bytes=32_000, _env_file=None
    )

    async def consume_body(scope: Scope, receive: Receive, send: Send) -> None:
        del scope
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = SecurityMiddleware(
        consume_body,
        settings=settings,
        limiter=FakeLimiter(RateLimitDecision(True, 10, 9, 60)),
    )
    incoming = [
        {"type": "http.request", "body": b"x" * 200_000, "more_body": True},
        {"type": "http.request", "body": b"x" * 100_001, "more_body": False},
    ]
    outgoing: list[Message] = []

    async def receive() -> Message:
        return incoming.pop(0)

    async def send(message: Message) -> None:
        outgoing.append(message)

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/example",
        "raw_path": b"/api/v1/example",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "state": {},
    }
    asyncio.run(middleware(scope, receive, send))

    assert outgoing[0]["status"] == 413


def test_rate_limit_returns_retry_metadata_without_calling_endpoint() -> None:
    settings = Settings(
        rate_limit_enabled=True,
        rate_limit_requests_per_window=2,
        _env_file=None,
    )
    limiter = FakeLimiter(RateLimitDecision(False, 2, 0, 17))
    test_app = _app_with_security(settings, limiter)

    with TestClient(test_app) as client:
        response = client.get("/api/v1/example")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "17"
    assert response.headers["ratelimit-limit"] == "2"
    assert response.headers["ratelimit-remaining"] == "0"
    assert response.json()["detail"]["code"] == "RATE_LIMITED"
    assert len(limiter.calls) == 1
    assert "127.0.0.1" not in limiter.calls[0][0]


def test_production_fails_closed_when_rate_limit_storage_is_unavailable() -> None:
    settings = _production_settings()
    test_app = _app_with_security(settings, FakeLimiter(RuntimeError("redis password leaked")))

    with TestClient(test_app, base_url="https://ledgerguard.example") as client:
        response = client.get("/api/v1/example")

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")
    assert response.json()["detail"]["code"] == "RATE_LIMIT_UNAVAILABLE"


def test_synthetic_source_guard_rejects_unmarked_sources() -> None:
    settings = Settings(synthetic_data_only=True, _env_file=None)

    enforce_synthetic_source("synthetic-clearing-demo", settings)
    with pytest.raises(Exception) as error:
        enforce_synthetic_source("live-clearing-feed", settings)

    assert getattr(error.value, "status_code", None) == 422
