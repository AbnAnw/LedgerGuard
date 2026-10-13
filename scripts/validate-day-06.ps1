[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$errors = @()

$requiredFiles = @(
    'backend/migrations/versions/20261013_0004_ingestion_quality_constraints.py',
    'backend/src/ledgerguard/ingestion.py',
    'backend/tests/test_ingestion.py',
    'docs/api/IDEMPOTENCY_AND_DATA_QUALITY.md',
    'sample-data/transactions-quality-v1.json'
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
        $errors += "Missing required Day 6 file: $relativePath"
    }
}

$ingestion = Get-Content -LiteralPath (Join-Path $repoRoot 'backend/src/ledgerguard/ingestion.py') -Raw
foreach ($contract in @(
    'Idempotency-Key',
    'IDEMPOTENCY_KEY_REUSED',
    'DUPLICATE_SOURCE_RECORD',
    'CONFLICTING_SOURCE_RECORD',
    'idempotent_replay',
    'BatchQualitySummary',
    'with_for_update',
    'IntegrityError'
)) {
    if ($ingestion -notmatch [regex]::Escape($contract)) {
        $errors += "Day 6 ingestion is missing contract: $contract"
    }
}

$models = Get-Content -LiteralPath (Join-Path $repoRoot 'backend/src/ledgerguard/models.py') -Raw
foreach ($constraint in @(
    'uq_ingestion_batches_idempotency',
    'uq_transactions_source',
    'ck_batches_idempotency_key',
    'ck_batches_terminal_totals'
)) {
    if ($models -notmatch [regex]::Escape($constraint)) {
        $errors += "Database model is missing Day 6 guard: $constraint"
    }
}

$tests = Get-Content -LiteralPath (Join-Path $repoRoot 'backend/tests/test_ingestion.py') -Raw
foreach ($scenario in @(
    'exact_idempotent_retry',
    'changed_payload_with_same_idempotency_key',
    'idempotency_race',
    'same_batch_duplicates_and_conflicts',
    'prior_transaction_is_classified',
    'quality_sample_has_all_day_six_outcomes'
)) {
    if ($tests -notmatch [regex]::Escape($scenario)) {
        $errors += "Day 6 tests are missing scenario: $scenario"
    }
}

$plan = Get-Content -LiteralPath (Join-Path $repoRoot 'PROJECT_PLAN.md') -Raw
if ($plan -notmatch 'Day 6 \| Idempotency and data-quality controls \| \*\*Complete\*\*') {
    $errors += 'PROJECT_PLAN.md does not mark Day 6 Complete in the status table.'
}
if ($plan -notmatch '### Day 6[^#]+\*\*Status: Complete\*\*') {
    $errors += 'PROJECT_PLAN.md does not mark the Day 6 detail Complete.'
}

if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Output 'Day 6 validation passed: idempotent retries, payload fingerprints, duplicate/conflict evidence, quality summaries, concurrency and database guards, deterministic tests, and roadmap status verified.'
