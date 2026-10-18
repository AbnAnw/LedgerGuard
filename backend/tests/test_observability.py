import json
import logging
from contextlib import AbstractContextManager
from types import TracebackType
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient
from opentelemetry import trace

from ledgerguard.main import app
from ledgerguard.metrics import render_metrics
from ledgerguard.observability import (
    JsonFormatter,
    configure_observability,
    inject_trace_context,
    job_span,
)


class FakeSession(AbstractContextManager["FakeSession"]):
    def __init__(self) -> None:
        self.responses = [
            [("reconciliation", "queued", 2), ("transaction_ingestion", "failed", 1)],
            [("transaction_ingestion", "JOB_INPUT_REJECTED", 1)],
            (8, 2, 1, 1),
            [("exact_match", 4), ("missing_settlement", 2)],
        ]

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def execute(self, statement: object) -> MagicMock:
        del statement
        response = self.responses.pop(0)
        result = MagicMock()
        if isinstance(response, tuple):
            result.one.return_value = response
        else:
            result.all.return_value = response
        return result


def test_json_formatter_emits_utc_json_and_recursively_redacts_secrets() -> None:
    record = logging.LogRecord("ledgerguard.telemetry", logging.INFO, __file__, 1, "safe", (), None)
    record.event_name = "test.event"
    record.structured_fields = {
        "password": "should-not-appear",
        "nested": {"access_token": "should-not-appear", "result": "ok"},
    }

    payload = json.loads(JsonFormatter().format(record))

    assert payload["timestamp"].endswith("+00:00")
    assert payload["event"] == "test.event"
    assert payload["password"] == "[REDACTED]"
    assert payload["nested"] == {"access_token": "[REDACTED]", "result": "ok"}
    assert "should-not-appear" not in json.dumps(payload)


def test_api_echoes_valid_request_id_and_replaces_invalid_input() -> None:
    request_id = str(uuid4())
    with TestClient(app) as client:
        valid = client.get("/api/v1/meta", headers={"X-Request-ID": request_id})
        invalid = client.get("/api/v1/meta", headers={"X-Request-ID": "not-a-uuid"})

    assert valid.status_code == 200
    assert valid.headers["x-request-id"] == request_id
    assert invalid.status_code == 200
    assert invalid.headers["x-request-id"] != "not-a-uuid"
    assert len(invalid.headers["x-request-id"]) == 36


def test_metrics_include_http_and_database_authoritative_signals() -> None:
    fake = FakeSession()
    output = render_metrics(lambda: fake).decode("utf-8")

    assert "ledgerguard_http_requests_total" in output
    assert (
        'ledgerguard_background_jobs_current{kind="reconciliation",status="queued"} 2.0' in output
    )
    assert 'ledgerguard_queue_depth{kind="reconciliation"} 2.0' in output
    assert (
        'ledgerguard_worker_failures_recorded{failure_code="JOB_INPUT_REJECTED",'
        'kind="transaction_ingestion"} 1.0' in output
    )
    assert 'ledgerguard_ingestion_records_processed{outcome="accepted"} 8.0' in output
    assert (
        'ledgerguard_reconciliation_results_processed{classification="exact_match"} 4.0' in output
    )
    assert "ledgerguard_observability_snapshot_up 1.0" in output


def test_worker_span_continues_injected_api_trace() -> None:
    configure_observability("ledgerguard-test")
    tracer = trace.get_tracer("ledgerguard.tests")
    with tracer.start_as_current_span("api.enqueue") as api_span:
        carrier = inject_trace_context()
        api_trace_id = api_span.get_span_context().trace_id

    with job_span(
        job_id=uuid4(),
        correlation_id=uuid4(),
        kind="reconciliation",
        carrier=carrier,
    ) as worker_span:
        worker_trace_id = worker_span.get_span_context().trace_id

    assert carrier["traceparent"].startswith("00-")
    assert worker_trace_id == api_trace_id
