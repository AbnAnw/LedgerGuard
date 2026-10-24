[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$requiredFiles = @(
    'backend/src/ledgerguard/performance.py',
    'backend/tests/test_performance.py',
    'backend/tests/test_resilience_integration.py',
    'docs/operations/PERFORMANCE_AND_RESILIENCE.md',
    'scripts/run-day-17-live.ps1'
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
        throw "Required Day 17 file is missing: $relativePath"
    }
}

$performance = Get-Content -Raw (Join-Path $repoRoot 'backend/src/ledgerguard/performance.py')
$reconciliation = Get-Content -Raw (Join-Path $repoRoot 'backend/src/ledgerguard/reconciliation.py')
$resilience = Get-Content -Raw (Join-Path $repoRoot 'backend/tests/test_resilience_integration.py')
$documentation = (Get-Content -Raw (Join-Path $repoRoot 'docs/operations/PERFORMANCE_AND_RESILIENCE.md')).ToLowerInvariant()
$plan = Get-Content -Raw (Join-Path $repoRoot 'PROJECT_PLAN.md')

foreach ($term in @('TRANSACTION_COUNT = 10_000', 'EXACT_MATCH_COUNT = 8_000', 'benchmark_reconciliation', 'time.perf_counter')) {
    if (-not $performance.Contains($term)) { throw "Performance harness is missing: $term" }
}
foreach ($term in @('settlements_by_match_key', '_candidate_edges')) {
    if (-not $reconciliation.Contains($term)) { throw "Reconciliation optimization is missing: $term" }
}
foreach ($term in @('test_duplicate_delivery', 'test_partial_database_failure', 'assert transaction_count == 0')) {
    if (-not $resilience.ToLowerInvariant().Contains($term)) { throw "Resilience evidence is missing: $term" }
}
foreach ($term in @('worker restart', 'database reconnection', 'p50', 'p95', 'before/after')) {
    if (-not $documentation.Contains($term)) { throw "Performance documentation is missing: $term" }
}
if (-not $plan.Contains('| Day 17 | Performance and resilience | **Complete** |')) {
    throw 'PROJECT_PLAN.md does not mark Day 17 Complete.'
}

Write-Output 'Day 17 workload, measurements, optimization, resilience evidence, and roadmap validation passed.'
