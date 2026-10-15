[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$requiredFiles = @(
    'backend/src/ledgerguard/cases.py',
    'backend/migrations/versions/20261016_0008_case_workflow_invariants.py',
    'backend/tests/test_cases.py',
    'frontend/src/CaseWorkspace.tsx',
    'frontend/src/CaseWorkspace.test.tsx',
    'docs/architecture/CASE_MANAGEMENT.md'
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
        throw "Required Day 11 file is missing: $relativePath"
    }
}

$caseApi = Get-Content -Raw (Join-Path $repoRoot 'backend/src/ledgerguard/cases.py')
$migration = Get-Content -Raw (Join-Path $repoRoot 'backend/migrations/versions/20261016_0008_case_workflow_invariants.py')
$contract = Get-Content -Raw (Join-Path $repoRoot 'docs/architecture/CASE_MANAGEMENT.md')
$plan = Get-Content -Raw (Join-Path $repoRoot 'PROJECT_PLAN.md')

foreach ($term in @('assign_case', 'add_comment', 'link_alerts', 'transition_case', 'CASE_VERSION_CONFLICT')) {
    if (-not $caseApi.Contains($term)) {
        throw "Case API is missing required workflow behaviour: $term"
    }
}
foreach ($term in @('owner_user_id', 'priority', 'case_status', 'rule_code', 'min_age_hours')) {
    if (-not $caseApi.Contains($term)) {
        throw "Case queue is missing required filter: $term"
    }
}
foreach ($term in @('ck_cases_resolution_required', 'ck_case_comments_body_length', 'ck_case_status_history_changed')) {
    if (-not $migration.Contains($term)) {
        throw "Case migration invariant is missing: $term"
    }
}
foreach ($term in @('optimistic concurrency', 'Auditors', '`resolved`', '`reopened`')) {
    if (-not $contract.Contains($term)) {
        throw "Case-management contract is missing: $term"
    }
}
if (-not $plan.Contains('| Day 11 | Case-management workflow | **Complete** |')) {
    throw 'PROJECT_PLAN.md does not mark Day 11 Complete.'
}

Write-Output 'Day 11 case lifecycle, evidence, filters, permissions, interface, and roadmap validation passed.'
