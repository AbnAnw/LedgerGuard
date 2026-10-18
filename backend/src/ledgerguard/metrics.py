"""Prometheus metrics with database-authoritative worker and processing snapshots."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ledgerguard.db import SessionLocal
from ledgerguard.models import (
    BackgroundJob,
    BackgroundJobKind,
    BackgroundJobStatus,
    IngestionBatch,
    ReconciliationResult,
)
from ledgerguard.observability import log_event

HTTP_REGISTRY = CollectorRegistry()
HTTP_REQUESTS = Counter(
    "ledgerguard_http_requests_total",
    "Completed LedgerGuard HTTP requests.",
    ("method", "route", "status_class"),
    registry=HTTP_REGISTRY,
)
HTTP_DURATION = Histogram(
    "ledgerguard_http_request_duration_seconds",
    "LedgerGuard HTTP request duration in seconds.",
    ("method", "route"),
    registry=HTTP_REGISTRY,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
_KNOWN_FAILURE_CODES = {
    "ACCOUNT_NOT_FOUND",
    "JOB_EXECUTION_FAILED",
    "JOB_INPUT_REJECTED",
    "JOB_TIMEOUT",
    "RETRY_LIMIT_EXCEEDED",
}


def observe_http_request(method: str, route: str, status_code: int, duration: float) -> None:
    safe_route = route if route.startswith("/") else "unmatched"
    HTTP_REQUESTS.labels(
        method=method, route=safe_route, status_class=f"{status_code // 100}xx"
    ).inc()
    HTTP_DURATION.labels(method=method, route=safe_route).observe(duration)


def _label(value: object) -> str:
    return str(getattr(value, "value", value))


class DatabaseMetricsCollector:
    """Collect durable cross-process metrics from PostgreSQL at scrape time."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def collect(self) -> Iterator[GaugeMetricFamily]:
        snapshot = GaugeMetricFamily(
            "ledgerguard_observability_snapshot_up",
            "Whether the authoritative PostgreSQL metric snapshot succeeded.",
        )
        try:
            with self.session_factory() as db:
                job_rows = db.execute(
                    select(BackgroundJob.kind, BackgroundJob.status, func.count())
                    .group_by(BackgroundJob.kind, BackgroundJob.status)
                    .order_by(BackgroundJob.kind, BackgroundJob.status)
                ).all()
                failure_rows = db.execute(
                    select(BackgroundJob.kind, BackgroundJob.failure_code, func.count())
                    .where(BackgroundJob.status == BackgroundJobStatus.FAILED)
                    .group_by(BackgroundJob.kind, BackgroundJob.failure_code)
                ).all()
                ingestion_totals = db.execute(
                    select(
                        func.coalesce(func.sum(IngestionBatch.accepted_count), 0),
                        func.coalesce(func.sum(IngestionBatch.rejected_count), 0),
                        func.coalesce(func.sum(IngestionBatch.duplicate_count), 0),
                        func.coalesce(func.sum(IngestionBatch.conflict_count), 0),
                    )
                ).one()
                reconciliation_rows = db.execute(
                    select(ReconciliationResult.classification, func.count())
                    .group_by(ReconciliationResult.classification)
                    .order_by(ReconciliationResult.classification)
                ).all()
        except Exception:
            log_event(
                "observability.snapshot.failed",
                "PostgreSQL metric snapshot failed.",
                level=30,
                service="ledgerguard-api",
            )
            snapshot.add_metric([], 0)
            yield snapshot
            return

        snapshot.add_metric([], 1)
        yield snapshot

        jobs = GaugeMetricFamily(
            "ledgerguard_background_jobs_current",
            "Authoritative background job counts.",
            labels=["kind", "status"],
        )
        queue = GaugeMetricFamily(
            "ledgerguard_queue_depth",
            "Authoritative queued background job count.",
            labels=["kind"],
        )
        queued_by_kind = {kind.value: 0 for kind in BackgroundJobKind}
        for kind, status, count in job_rows:
            kind_label = _label(kind)
            status_label = _label(status)
            jobs.add_metric([kind_label, status_label], int(count))
            if status_label == BackgroundJobStatus.QUEUED.value:
                queued_by_kind[kind_label] = int(count)
        for kind_label, count in sorted(queued_by_kind.items()):
            queue.add_metric([kind_label], count)
        yield jobs
        yield queue

        failures = GaugeMetricFamily(
            "ledgerguard_worker_failures_recorded",
            "Persisted terminal worker failures.",
            labels=["kind", "failure_code"],
        )
        for kind, code, count in failure_rows:
            safe_code = str(code) if code in _KNOWN_FAILURE_CODES else "other"
            failures.add_metric([_label(kind), safe_code], int(count))
        yield failures

        ingestion = GaugeMetricFamily(
            "ledgerguard_ingestion_records_processed",
            "Persisted ingestion outcomes.",
            labels=["outcome"],
        )
        for outcome, count in zip(
            ("accepted", "rejected", "duplicate", "conflict"), ingestion_totals, strict=True
        ):
            ingestion.add_metric([outcome], int(count))
        yield ingestion

        reconciliation = GaugeMetricFamily(
            "ledgerguard_reconciliation_results_processed",
            "Persisted reconciliation outcomes.",
            labels=["classification"],
        )
        for classification, count in reconciliation_rows:
            reconciliation.add_metric([_label(classification)], int(count))
        yield reconciliation


def render_metrics(session_factory: Callable[[], Session] = SessionLocal) -> bytes:
    database_registry = CollectorRegistry()
    database_registry.register(DatabaseMetricsCollector(session_factory))
    return generate_latest(HTTP_REGISTRY) + generate_latest(database_registry)
