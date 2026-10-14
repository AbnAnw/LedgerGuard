[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$requiredFiles = @(
    'backend/src/ledgerguard/jobs.py',
    'backend/src/ledgerguard/worker.py',
    'backend/migrations/versions/20261014_0006_background_jobs.py',
    'backend/tests/test_jobs.py',
    'backend/tests/test_background_integration.py',
    'docs/architecture/BACKGROUND_PROCESSING.md'
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
        throw "Required Day 9 file is missing: $relativePath"
    }
}

$jobs = Get-Content -Raw (Join-Path $repoRoot 'backend/src/ledgerguard/jobs.py')
$worker = Get-Content -Raw (Join-Path $repoRoot 'backend/src/ledgerguard/worker.py')
$compose = Get-Content -Raw (Join-Path $repoRoot 'docker-compose.yml')
$contract = Get-Content -Raw (Join-Path $repoRoot 'docs/architecture/BACKGROUND_PROCESSING.md')
$plan = Get-Content -Raw (Join-Path $repoRoot 'PROJECT_PLAN.md')

$requiredJobTerms = @(
    'BackgroundJobStatus.QUEUED',
    'BackgroundJobStatus.RUNNING',
    'BackgroundJobStatus.SUCCEEDED',
    'BackgroundJobStatus.FAILED',
    'BackgroundJobStatus.CANCELLED',
    'mark_job_for_retry',
    'cancellation_requested_at',
    'with_for_update'
)
foreach ($term in $requiredJobTerms) {
    if (-not $jobs.Contains($term)) {
        throw "Day 9 durable job implementation is missing: $term"
    }
}

foreach ($term in @('task_acks_late=True', 'task_reject_on_worker_lost=True', 'worker_prefetch_multiplier=1')) {
    if (-not ($worker -replace '\s', '').Contains($term)) {
        throw "Day 9 worker safety configuration is missing: $term"
    }
}
if (-not $compose.Contains('celery -A ledgerguard.worker.celery_app inspect ping')) {
    throw 'Compose worker health check does not use a targeted Celery ping.'
}
foreach ($term in @('10,000 synthetic transactions', 'Duplicate broker delivery', 'HTTP 202')) {
    if (-not $contract.Contains($term)) {
        throw "Background-processing contract is missing: $term"
    }
}
if (-not $plan.Contains('| Day 9 | Background processing | **Complete** |')) {
    throw 'PROJECT_PLAN.md does not mark Day 9 Complete.'
}

Write-Output 'Day 9 durable jobs, worker safety, integration contract, and roadmap validation passed.'
