"""HTTP security boundary, throttling, and synthetic-data guardrails."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException, status
from redis.asyncio import Redis
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ledgerguard.config import Settings
from ledgerguard.observability import log_event

_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Result of one bounded fixed-window counter evaluation."""

    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class RateLimiter(Protocol):
    async def check(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        """Increment a bucket and return its bounded decision."""


class RedisRateLimiter:
    """Atomic fixed-window rate limiter shared by API replicas."""

    def __init__(self, redis_url: str) -> None:
        self.client = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )

    async def check(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        raw = await self.client.eval(_RATE_LIMIT_SCRIPT, 1, key, window_seconds)
        if not isinstance(raw, list | tuple) or len(raw) != 2:
            raise RuntimeError("rate limiter returned an invalid response")
        current = int(raw[0])
        ttl = max(int(raw[1]), 1)
        return RateLimitDecision(
            allowed=current <= limit,
            limit=limit,
            remaining=max(limit - current, 0),
            retry_after=ttl,
        )


def _header_value(scope: Scope, name: bytes) -> str | None:
    return next(
        (value.decode("latin-1") for key, value in scope.get("headers", []) if key.lower() == name),
        None,
    )


def _host_name(host_header: str | None) -> str:
    if not host_header:
        return ""
    if host_header.startswith("["):
        return host_header.split("]", 1)[0][1:].lower()
    return host_header.rsplit(":", 1)[0].lower()


class RequestBodyTooLarge(Exception):
    """Raised before domain parsing when a streamed body crosses its configured limit."""


class SecurityMiddleware:
    """Enforce host, body, rate, cache, and response-header controls."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: Settings,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.app = app
        self.settings = settings
        self.limiter = limiter or RedisRateLimiter(settings.redis_url)
        self.allowed_hosts = {host.lower() for host in settings.allowed_hosts}

    def _security_headers(self, path: str) -> list[tuple[bytes, bytes]]:
        if path in {"/docs", "/redoc"} or path.startswith("/openapi"):
            content_security_policy = (
                "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data:"
            )
        else:
            content_security_policy = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        headers = [
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"no-referrer"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
            (b"content-security-policy", content_security_policy.encode("ascii")),
        ]
        if path.startswith("/api/"):
            headers.append((b"cache-control", b"no-store"))
        if self.settings.app_env == "production":
            headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
        return headers

    async def _send_json(
        self,
        send: Send,
        path: str,
        status_code: int,
        body: dict[str, object],
        extra_headers: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
        ]
        headers.extend(self._security_headers(path))
        headers.extend(extra_headers or [])
        await send({"type": "http.response.start", "status": status_code, "headers": headers})
        await send({"type": "http.response.body", "body": payload})

    def _bucket(self, scope: Scope) -> tuple[str, int]:
        path = str(scope.get("path", ""))
        policy = "login" if path == "/api/v1/auth/login" else "api"
        limit = (
            self.settings.rate_limit_login_requests_per_window
            if policy == "login"
            else self.settings.rate_limit_requests_per_window
        )
        client = scope.get("client")
        address = str(client[0]) if client else "unknown"
        digest = hmac.digest(
            self.settings.auth_secret_key.get_secret_value().encode(),
            address.encode(),
            hashlib.sha256,
        ).hex()
        return f"ledgerguard:rate:{policy}:{digest}", limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        host = _host_name(_header_value(scope, b"host"))
        if host not in self.allowed_hosts:
            await self._send_json(
                send, path, status.HTTP_400_BAD_REQUEST, {"detail": "Invalid host"}
            )
            return

        content_length = _header_value(scope, b"content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                await self._send_json(
                    send, path, status.HTTP_400_BAD_REQUEST, {"detail": "Invalid Content-Length"}
                )
                return
            if declared_length < 0:
                await self._send_json(
                    send, path, status.HTTP_400_BAD_REQUEST, {"detail": "Invalid Content-Length"}
                )
                return
            if declared_length > self.settings.max_request_body_bytes:
                await self._send_json(
                    send,
                    path,
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    {
                        "detail": {
                            "code": "REQUEST_TOO_LARGE",
                            "message": "Request body exceeds the configured limit.",
                        }
                    },
                )
                return

        rate_headers: list[tuple[bytes, bytes]] = []
        if self.settings.rate_limit_enabled and path.startswith("/api/"):
            key, limit = self._bucket(scope)
            try:
                decision = await self.limiter.check(
                    key, limit, self.settings.rate_limit_window_seconds
                )
            except Exception:
                log_event(
                    "security.rate_limit.unavailable",
                    "Rate-limit storage was unavailable.",
                    policy="closed" if self.settings.app_env == "production" else "open",
                )
                if self.settings.app_env == "production":
                    await self._send_json(
                        send,
                        path,
                        status.HTTP_503_SERVICE_UNAVAILABLE,
                        {
                            "detail": {
                                "code": "RATE_LIMIT_UNAVAILABLE",
                                "message": "Request controls are temporarily unavailable.",
                            }
                        },
                        [(b"retry-after", b"1")],
                    )
                    return
            else:
                rate_headers = [
                    (b"ratelimit-limit", str(decision.limit).encode()),
                    (b"ratelimit-remaining", str(decision.remaining).encode()),
                    (b"ratelimit-reset", str(decision.retry_after).encode()),
                ]
                if not decision.allowed:
                    await self._send_json(
                        send,
                        path,
                        status.HTTP_429_TOO_MANY_REQUESTS,
                        {"detail": {"code": "RATE_LIMITED", "message": "Too many requests."}},
                        [*rate_headers, (b"retry-after", str(decision.retry_after).encode())],
                    )
                    return

        received = 0
        response_started = False

        async def bounded_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.settings.max_request_body_bytes:
                    raise RequestBodyTooLarge
            return message

        async def send_with_security(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                existing_names = {key.lower() for key, _ in message.get("headers", [])}
                additions = [
                    header
                    for header in [*self._security_headers(path), *rate_headers]
                    if header[0] not in existing_names
                ]
                message["headers"] = [*message.get("headers", []), *additions]
            await send(message)

        try:
            await self.app(scope, bounded_receive, send_with_security)
        except RequestBodyTooLarge:
            if response_started:
                raise
            await self._send_json(
                send,
                path,
                status.HTTP_413_CONTENT_TOO_LARGE,
                {
                    "detail": {
                        "code": "REQUEST_TOO_LARGE",
                        "message": "Request body exceeds the configured limit.",
                    }
                },
                rate_headers,
            )


def enforce_synthetic_source(source_system: str, settings: Settings) -> None:
    """Reject sources that are not explicitly marked synthetic in this portfolio build."""

    if settings.synthetic_data_only and not source_system.lower().startswith("synthetic-"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "SYNTHETIC_SOURCE_REQUIRED",
                "message": "This LedgerGuard build accepts synthetic demonstration sources only.",
            },
        )
