"""Structured logs, correlation context, and OpenTelemetry helpers."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from enum import Enum
from threading import Lock
from time import perf_counter
from uuid import UUID, uuid4

from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import SpanKind, Status, StatusCode
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ledgerguard.config import get_settings

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_job_id: ContextVar[str | None] = ContextVar("job_id", default=None)
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_process_service_name = "ledgerguard-api"
_configured = False
_configuration_lock = Lock()
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "credential",
    "database_url",
    "dsn",
    "email",
    "instrument",
    "password",
    "payload",
    "redis_url",
    "secret",
    "source_record",
    "token",
)
_SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}\b"),
    re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/:@]+:[^\s/@]+@"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b"),
)


def _redact_text(value: str) -> str:
    sanitized = value
    for index, pattern in enumerate(_SENSITIVE_TEXT_PATTERNS):
        replacement = r"\1[REDACTED]@" if index == 2 else "[REDACTED]"
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def _json_safe(value: object) -> object:
    if isinstance(value, datetime | UUID | Enum):
        return (
            value.isoformat()
            if isinstance(value, datetime)
            else str(value.value if isinstance(value, Enum) else value)
        )
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def redact(value: object, *, key: str = "") -> object:
    """Recursively redact values whose field names suggest authentication material."""

    if any(part in key.lower() for part in _SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(item_key): redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return _json_safe(value)


class JsonFormatter(logging.Formatter):
    """Render LedgerGuard application records as a single redacted JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        span_context = trace.get_current_span().get_span_context()
        fields = getattr(record, "structured_fields", {})
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "service": getattr(record, "service_name", _process_service_name),
            "event": getattr(record, "event_name", record.name),
            "message": record.getMessage(),
            "request_id": _request_id.get(),
            "trace_id": (f"{span_context.trace_id:032x}" if span_context.is_valid else None),
            "span_id": f"{span_context.span_id:016x}" if span_context.is_valid else None,
            "job_id": _job_id.get(),
            "correlation_id": _correlation_id.get(),
        }
        payload.update(fields)
        return json.dumps(redact(payload), sort_keys=True, separators=(",", ":"))


def configure_logging(service_name: str) -> None:
    global _process_service_name
    logger = logging.getLogger("ledgerguard.telemetry")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, get_settings().log_level))
    logger.propagate = False
    _process_service_name = service_name


def log_event(event: str, message: str, *, level: int = logging.INFO, **fields: object) -> None:
    logging.getLogger("ledgerguard.telemetry").log(
        level,
        message,
        extra={"event_name": event, "structured_fields": fields},
    )


class StructuredLogSpanExporter(SpanExporter):
    """Export local spans as bounded structured events when no collector is configured."""

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            span_context = span.context
            duration_ms = (
                round((span.end_time - span.start_time) / 1_000_000, 3)
                if span.end_time is not None and span.start_time is not None
                else None
            )
            log_event(
                "trace.span.completed",
                "OpenTelemetry span completed.",
                service=str(span.resource.attributes.get("service.name", _process_service_name)),
                trace_id=f"{span_context.trace_id:032x}",
                span_id=f"{span_context.span_id:016x}",
                span_name=span.name,
                span_kind=span.kind.name.lower(),
                span_status=span.status.status_code.name.lower(),
                duration_ms=duration_ms,
                attributes=dict(span.attributes or {}),
            )
        return SpanExportResult.SUCCESS


def configure_observability(service_name: str) -> None:
    """Configure logging and tracing once per API or worker process."""

    global _configured
    configure_logging(service_name)
    with _configuration_lock:
        if _configured:
            return
        settings = get_settings()
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        if settings.otel_exporter_otlp_endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            endpoint = f"{settings.otel_exporter_otlp_endpoint}/v1/traces"
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        elif settings.otel_structured_log_exporter:
            provider.add_span_processor(SimpleSpanProcessor(StructuredLogSpanExporter()))
        trace.set_tracer_provider(provider)
        _configured = True


def current_request_id() -> UUID | None:
    value = _request_id.get()
    try:
        return UUID(value) if value is not None else None
    except ValueError:
        return None


def inject_trace_context() -> dict[str, str]:
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


@contextmanager
def job_span(
    *, job_id: UUID, correlation_id: UUID, kind: str, carrier: Mapping[str, str]
) -> Iterator[trace.Span]:
    """Continue an API trace and bind durable job correlation to worker logs."""

    extracted = propagate.extract(dict(carrier))
    job_token = _job_id.set(str(job_id))
    correlation_token = _correlation_id.set(str(correlation_id))
    tracer = trace.get_tracer("ledgerguard.jobs")
    try:
        with tracer.start_as_current_span(
            "background_job.process", context=extracted, kind=SpanKind.CONSUMER
        ) as span:
            span.set_attribute("ledgerguard.job.id", str(job_id))
            span.set_attribute("ledgerguard.job.correlation_id", str(correlation_id))
            span.set_attribute("ledgerguard.job.kind", kind)
            yield span
    finally:
        _correlation_id.reset(correlation_token)
        _job_id.reset(job_token)


class ObservabilityMiddleware:
    """Add request correlation, tracing, structured completion logs, and HTTP metrics."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from ledgerguard.metrics import observe_http_request

        header_value = next(
            (
                value.decode("latin-1")
                for key, value in scope.get("headers", [])
                if key.lower() == b"x-request-id"
            ),
            None,
        )
        try:
            request_id = str(UUID(header_value)) if header_value else str(uuid4())
        except ValueError:
            request_id = str(uuid4())
        token = _request_id.set(request_id)
        status_code = 500
        started = perf_counter()
        tracer = trace.get_tracer("ledgerguard.http")

        async def send_with_correlation(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            with tracer.start_as_current_span(
                f"HTTP {scope['method']}",
                kind=SpanKind.SERVER,
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                try:
                    await self.app(scope, receive, send_with_correlation)
                except Exception:
                    span.set_status(Status(StatusCode.ERROR, "unhandled server error"))
                    raise
                finally:
                    route = getattr(scope.get("route"), "path", "unmatched")
                    duration = perf_counter() - started
                    span.update_name(f"HTTP {scope['method']} {route}")
                    span.set_attribute("http.request.method", scope["method"])
                    span.set_attribute("http.route", route)
                    span.set_attribute("http.response.status_code", status_code)
                    if status_code >= 500:
                        span.set_status(Status(StatusCode.ERROR, f"HTTP {status_code}"))
                    observe_http_request(scope["method"], route, status_code, duration)
                    log_event(
                        "http.request.completed",
                        "HTTP request completed.",
                        service="ledgerguard-api",
                        method=scope["method"],
                        route=route,
                        status_code=status_code,
                        duration_ms=round(duration * 1000, 3),
                    )
        finally:
            _request_id.reset(token)
