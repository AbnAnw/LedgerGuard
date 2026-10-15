[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$requiredFiles = @(
    'backend/src/ledgerguard/fraud.py',
    'backend/migrations/versions/20261016_0007_fraud_rule_invariants.py',
    'backend/tests/test_fraud.py',
    'frontend/src/FraudMonitor.tsx',
    'docs/architecture/FRAUD_RULE_ENGINE.md',
    'sample-data/fraud-rules-v1.json'
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
        throw "Required Day 10 file is missing: $relativePath"
    }
}

$engine = Get-Content -Raw (Join-Path $repoRoot 'backend/src/ledgerguard/fraud.py')
$migration = Get-Content -Raw (Join-Path $repoRoot 'backend/migrations/versions/20261016_0007_fraud_rule_invariants.py')
$contract = Get-Content -Raw (Join-Path $repoRoot 'docs/architecture/FRAUD_RULE_ENGINE.md')
$plan = Get-Content -Raw (Join-Path $repoRoot 'PROJECT_PLAN.md')

foreach ($term in @('VELOCITY', 'UNUSUAL_AMOUNT', 'REPEATED_FAILURE', 'DUPLICATE_INSTRUMENT', 'SUSPICIOUS_TIMING')) {
    if (-not $engine.Contains($term)) {
        throw "Fraud engine is missing required rule family: $term"
    }
}
foreach ($term in @('evidence_sha256', 'deduplication_key', 'version_number', 'input_cutoff_at')) {
    if (-not $engine.Contains($term)) {
        throw "Fraud evidence contract is missing: $term"
    }
}
foreach ($term in @('prevent_rule_version_configuration_update', 'ck_rule_versions_lifecycle', 'ck_alerts_evidence_object')) {
    if (-not $migration.Contains($term)) {
        throw "Fraud migration invariant is missing: $term"
    }
}
foreach ($term in @('Only `posted` transactions', 'decimal string', 'Administrators', 'Auditors', 'replay')) {
    if (-not $contract.Contains($term)) {
        throw "Fraud rule contract is missing: $term"
    }
}
if (-not $plan.Contains('| Day 10 | Fraud rule engine | **Complete** |')) {
    throw 'PROJECT_PLAN.md does not mark Day 10 Complete.'
}

Write-Output 'Day 10 deterministic fraud rules, evidence, permissions, interface, and roadmap validation passed.'
