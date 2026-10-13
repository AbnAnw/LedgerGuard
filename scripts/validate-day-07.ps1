[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$requiredFiles = @(
    'backend/src/ledgerguard/reconciliation.py',
    'backend/tests/test_reconciliation.py',
    'backend/migrations/versions/20261014_0005_reconciliation_invariants.py',
    'docs/api/RECONCILIATION_V1.md',
    'sample-data/reconciliation-v1.json'
)

foreach ($relativePath in $requiredFiles) {
    $path = Join-Path $repoRoot $relativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required Day 7 file is missing: $relativePath"
    }
}

$source = Get-Content -Raw (Join-Path $repoRoot 'backend/src/ledgerguard/reconciliation.py')
$requiredSourceTerms = @(
    'ALGORITHM_VERSION = "reconciliation-v1.0.0"',
    'EXACT_REFERENCE_AMOUNT_CURRENCY_TIME',
    'PARTIAL_AMOUNT_MISMATCH',
    'NO_ELIGIBLE_SETTLEMENT',
    'DUPLICATE_EXACT_CANDIDATES',
    'NO_ELIGIBLE_TRANSACTION',
    'Permission.RECONCILIATION_WRITE',
    'Permission.RECONCILIATION_READ',
    'evidence_sha256'
)
foreach ($term in $requiredSourceTerms) {
    if (-not $source.Contains($term)) {
        throw "Day 7 reconciliation implementation is missing: $term"
    }
}

$sample = Get-Content -Raw (Join-Path $repoRoot 'sample-data/reconciliation-v1.json') | ConvertFrom-Json
$expectedNames = @(
    'exact_match',
    'partial_match',
    'missing_settlement',
    'duplicate_candidate',
    'unexplained_settlement'
)
foreach ($name in $expectedNames) {
    if ($sample.expected_classifications.$name -ne 1) {
        throw "Synthetic reconciliation sample must expect one $name result."
    }
}

$plan = Get-Content -Raw (Join-Path $repoRoot 'PROJECT_PLAN.md')
if (-not $plan.Contains('### Day 7 — Reconciliation engine version 1')) {
    throw 'Day 7 roadmap section is missing.'
}

Write-Output 'Day 7 reconciliation structure and synthetic scenario validation passed.'
