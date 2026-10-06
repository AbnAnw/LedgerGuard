[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$errors = @()

$requiredFiles = @(
    'docs/architecture/DATA_MODEL.md',
    'docs/architecture/ERD.md',
    'docs/decisions/0001-decimal-money.md',
    'docs/decisions/0002-identifiers.md',
    'docs/decisions/0003-append-only-audit-history.md'
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
        $errors += "Missing required Day 2 file: $relativePath"
    }
}

$modelPath = Join-Path $repoRoot 'docs/architecture/DATA_MODEL.md'
if (Test-Path -LiteralPath $modelPath) {
    $model = Get-Content -LiteralPath $modelPath -Raw
    $requiredEntities = @(
        'users', 'roles', 'user_roles', 'accounts', 'transactions', 'settlements',
        'ingestion_batches', 'ingestion_records', 'reconciliation_runs',
        'reconciliation_results', 'reconciliation_result_transactions',
        'reconciliation_result_settlements', 'fraud_rules', 'fraud_rule_versions',
        'alerts', 'cases', 'case_alerts', 'case_comments', 'case_status_history',
        'audit_events'
    )
    foreach ($entity in $requiredEntities) {
        if ($model -notmatch [regex]::Escape($entity)) {
            $errors += "Data model is missing entity: $entity"
        }
    }

    $requiredConcepts = @(
        'NUMERIC(20,6)', 'TIMESTAMPTZ', 'UTC', 'UUIDv4', 'Lifecycle definitions',
        'Index and query plan', 'Retention assumptions', 'optimistic concurrency',
        'idempotency', 'evidence', 'synthetic'
    )
    foreach ($concept in $requiredConcepts) {
        if ($model -notmatch [regex]::Escape($concept)) {
            $errors += "Data model is missing required concept: $concept"
        }
    }
}

$erdPath = Join-Path $repoRoot 'docs/architecture/ERD.md'
if (Test-Path -LiteralPath $erdPath) {
    $erd = Get-Content -LiteralPath $erdPath -Raw
    if ($erd -notmatch '```mermaid\s+erDiagram') {
        $errors += 'ERD.md does not contain a Mermaid erDiagram block'
    }
    foreach ($entity in @('USERS', 'TRANSACTIONS', 'SETTLEMENTS', 'RECONCILIATION_RUNS', 'ALERTS', 'CASES', 'AUDIT_EVENTS')) {
        if ($erd -notmatch "(?m)^\s*$entity\s*\{") {
            $errors += "ERD is missing entity: $entity"
        }
    }
}

foreach ($relativePath in $requiredFiles | Where-Object { $_ -like 'docs/decisions/*' }) {
    $adrPath = Join-Path $repoRoot $relativePath
    if (Test-Path -LiteralPath $adrPath) {
        $adr = Get-Content -LiteralPath $adrPath -Raw
        if ($adr -notmatch '(?m)^- \*\*Status:\*\* Accepted$') {
            $errors += "ADR is not marked Accepted: $relativePath"
        }
        foreach ($heading in @('## Context', '## Decision', '## Consequences', '## Alternatives rejected')) {
            if ($adr -notmatch [regex]::Escape($heading)) {
                $errors += "ADR is missing '$heading': $relativePath"
            }
        }
    }
}

$planPath = Join-Path $repoRoot 'PROJECT_PLAN.md'
if (Test-Path -LiteralPath $planPath) {
    $plan = Get-Content -LiteralPath $planPath -Raw
    if ($plan -notmatch 'Day 2 \| Domain and data model \| \*\*Complete\*\*') {
        $errors += 'PROJECT_PLAN.md does not mark Day 2 Complete in the status table'
    }
    if ($plan -notmatch '### Day 2[^#]+\*\*Status: Complete\*\*') {
        $errors += 'PROJECT_PLAN.md does not mark the Day 2 detail Complete'
    }
}

if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Output 'Day 2 validation passed: 5 required files, 20 entities, required model conventions, ER diagram, 3 accepted ADRs, and roadmap status verified.'
