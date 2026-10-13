[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$requiredFiles = @(
    'backend/src/ledgerguard/dashboard.py',
    'backend/tests/test_dashboard.py',
    'frontend/src/Dashboard.tsx',
    'frontend/src/Dashboard.test.tsx',
    'frontend/src/money.ts',
    'frontend/src/money.test.ts',
    'docs/ui/ANALYST_DASHBOARD.md'
)

foreach ($relativePath in $requiredFiles) {
    $path = Join-Path $repoRoot $relativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required Day 8 file is missing: $relativePath"
    }
}

$backend = Get-Content -Raw (Join-Path $repoRoot 'backend/src/ledgerguard/dashboard.py')
$frontend = Get-Content -Raw (Join-Path $repoRoot 'frontend/src/Dashboard.tsx')
$money = Get-Content -Raw (Join-Path $repoRoot 'frontend/src/money.ts')
$contract = Get-Content -Raw (Join-Path $repoRoot 'docs/ui/ANALYST_DASHBOARD.md')
$plan = Get-Content -Raw (Join-Path $repoRoot 'PROJECT_PLAN.md')

$requiredBackendTerms = @(
    'Permission.TRANSACTIONS_READ',
    'Permission.RECONCILIATION_READ',
    'ReconciliationRun.input_cutoff_at.desc()',
    'exact_matched_value',
    'unresolved_value',
    'match_rate_percent'
)
foreach ($term in $requiredBackendTerms) {
    if (-not $backend.Contains($term)) {
        throw "Day 8 dashboard API is missing: $term"
    }
}

$requiredInterfaceTerms = @(
    'Run reconciliation',
    'No completed reconciliation run yet.',
    'No results match these filters.',
    'Dashboard access is not assigned.',
    'Dashboard unavailable.',
    'Auditor · read only',
    'Match window must be a whole number from 1 to 168.'
)
foreach ($term in $requiredInterfaceTerms) {
    if (-not $frontend.Contains($term)) {
        throw "Day 8 interface state is missing: $term"
    }
}

if (-not $money.Contains('BigInt')) {
    throw 'Frontend money comparison must remain decimal-safe with BigInt.'
}
if ($money -match 'Number\s*\(') {
    throw 'Frontend money utilities must not convert monetary values to Number.'
}
if (-not $contract.Contains('latest effective UTC input cutoff')) {
    throw 'Dashboard contract must define effective-cutoff ordering.'
}
if (-not $plan.Contains('### Day 8 — Analyst dashboard')) {
    throw 'Day 8 roadmap section is missing.'
}

Write-Output 'Day 8 dashboard structure, role boundaries, states, and money safety validation passed.'
