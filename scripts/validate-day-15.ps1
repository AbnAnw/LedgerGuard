[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$requiredFiles = @(
    'backend/src/ledgerguard/metrics.py',
    'backend/src/ledgerguard/observability.py',
    'backend/tests/test_observability.py',
    'docs/architecture/OBSERVABILITY.md',
    'infra/observability/prometheus.yml',
    'infra/observability/grafana/dashboards/ledgerguard-operations.json',
    'infra/observability/grafana/provisioning/dashboards/ledgerguard.yml',
    'infra/observability/grafana/provisioning/datasources/prometheus.yml'
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
        throw "Required Day 15 file is missing: $relativePath"
    }
}

$contract = (Get-Content -Raw (Join-Path $repoRoot 'docs/architecture/OBSERVABILITY.md')).ToLowerInvariant()
$metrics = Get-Content -Raw (Join-Path $repoRoot 'backend/src/ledgerguard/metrics.py')
$observability = Get-Content -Raw (Join-Path $repoRoot 'backend/src/ledgerguard/observability.py')
$compose = Get-Content -Raw (Join-Path $repoRoot 'docker-compose.yml')
$dashboard = Get-Content -Raw (Join-Path $repoRoot 'infra/observability/grafana/dashboards/ledgerguard-operations.json')
$plan = Get-Content -Raw (Join-Path $repoRoot 'PROJECT_PLAN.md')

foreach ($term in @('request id', 'job id', 'trace id', 'redact', 'low-cardinality', 'failure drill', 'latency_ms')) {
    if (-not $contract.Contains($term)) {
        throw "Observability contract is missing required guidance: $term"
    }
}
foreach ($term in @('ledgerguard_http_request_duration_seconds', 'ledgerguard_queue_depth', 'ledgerguard_worker_failures_recorded', 'ledgerguard_ingestion_records_processed', 'ledgerguard_reconciliation_results_processed')) {
    if (-not $metrics.Contains($term)) {
        throw "Metrics implementation is missing: $term"
    }
}
foreach ($term in @('JsonFormatter', 'ObservabilityMiddleware', 'inject_trace_context', 'job_span')) {
    if (-not $observability.Contains($term)) {
        throw "Observability implementation is missing: $term"
    }
}
foreach ($term in @('prom/prometheus:v3.5.0', 'grafana/grafana:12.1.1', '127.0.0.1:${PROMETHEUS_PORT:-9090}', '127.0.0.1:${GRAFANA_PORT:-3000}')) {
    if (-not $compose.Contains($term)) {
        throw "Compose observability topology is missing: $term"
    }
}
foreach ($term in @('API request rate', 'API error rate', 'API p95 latency', 'Durable queue depth', 'Recorded worker failures', 'Ingestion outcomes', 'Reconciliation outcomes')) {
    if (-not $dashboard.Contains($term)) {
        throw "Grafana dashboard is missing panel: $term"
    }
}
if (-not $plan.Contains('| Day 15 | Observability | **Complete** |')) {
    throw 'PROJECT_PLAN.md does not mark Day 15 Complete.'
}

Write-Output 'Day 15 logs, correlation, metrics, traces, health, dashboard, and roadmap validation passed.'
