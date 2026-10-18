[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$requiredFiles = @(
    '.github/workflows/ci.yml',
    'backend/tests/test_background_integration.py',
    'docs/architecture/TEST_STRATEGY.md',
    'frontend/e2e/roles.spec.ts',
    'frontend/playwright.config.ts'
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
        throw "Required Day 14 file is missing: $relativePath"
    }
}

$strategy = (Get-Content -Raw (Join-Path $repoRoot 'docs/architecture/TEST_STRATEGY.md')).ToLowerInvariant()
$journeys = Get-Content -Raw (Join-Path $repoRoot 'frontend/e2e/roles.spec.ts')
$workflow = Get-Content -Raw (Join-Path $repoRoot '.github/workflows/ci.yml')
$integration = Get-Content -Raw (Join-Path $repoRoot 'backend/tests/test_background_integration.py')
$package = Get-Content -Raw (Join-Path $repoRoot 'frontend/package.json')
$plan = Get-Content -Raw (Join-Path $repoRoot 'PROJECT_PLAN.md')

foreach ($term in @('unit/service', 'integration', 'browser journey', 'money', 'permission matrix', 'retry', 'ci isolation')) {
    if (-not $strategy.Contains($term)) {
        throw "Test strategy is missing required guidance: $term"
    }
}
foreach ($term in @('admin@ledgerguard.invalid', 'analyst@ledgerguard.invalid', 'auditor@ledgerguard.invalid', 'Run reconciliation', 'Evaluate synthetic account')) {
    if (-not $journeys.Contains($term)) {
        throw "Playwright journeys are missing required role evidence: $term"
    }
}
foreach ($term in @('ruff format --check', 'ruff check', 'mypy src', 'pytest --cov', 'npm run lint', 'npm run typecheck', 'npm run test', 'npm run build', 'test:e2e', 'docker compose up')) {
    if (-not $workflow.Contains($term)) {
        throw "CI workflow is missing a required quality gate: $term"
    }
}
foreach ($term in @('test_worker_executes_a_real_broker_round_trip', 'test_retry_state_is_durable_and_payload_is_removed_at_limit')) {
    if (-not $integration.Contains($term)) {
        throw "Integration coverage is missing: $term"
    }
}
if (-not $package.Contains('"@playwright/test"')) {
    throw 'Frontend package does not pin Playwright.'
}
if (-not $plan.Contains('| Day 14 | Comprehensive automated testing | **Complete** |')) {
    throw 'PROJECT_PLAN.md does not mark Day 14 Complete.'
}

Write-Output 'Day 14 risk coverage, live integration, three role journeys, CI gates, and roadmap validation passed.'
