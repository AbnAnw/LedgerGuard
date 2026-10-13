[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$errors = @()

$requiredFiles = @(
    'backend/migrations/versions/20261013_0003_ingestion_rejection_details.py',
    'backend/src/ledgerguard/ingestion.py',
    'backend/tests/test_ingestion.py',
    'docs/api/TRANSACTION_INGESTION_V1.md',
    'sample-data/transactions-valid-v1.json',
    'sample-data/transactions-mixed-v1.json',
    'sample-data/transactions-valid-v1.csv',
    'sample-data/transactions-mixed-v1.csv'
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
        $errors += "Missing required Day 5 file: $relativePath"
    }
}

$backendProject = Get-Content -LiteralPath (Join-Path $repoRoot 'backend/pyproject.toml') -Raw
if ($backendProject -notmatch 'python-multipart==') {
    $errors += 'Backend project does not pin multipart upload support.'
}

$ingestion = Get-Content -LiteralPath (Join-Path $repoRoot 'backend/src/ledgerguard/ingestion.py') -Raw
foreach ($contract in @(
    '/api/v1/ingestion/transactions',
    'router.post("/json"',
    'router.post("/csv"',
    'Decimal',
    'INGESTION_WRITE',
    'INVALID_AMOUNT',
    'INVALID_CURRENCY',
    'INVALID_TIMESTAMP',
    'canonical_sha256'
)) {
    if ($ingestion -notmatch [regex]::Escape($contract)) {
        $errors += "Transaction ingestion is missing contract: $contract"
    }
}

$migration = Get-Content -LiteralPath (Join-Path $repoRoot 'backend/migrations/versions/20261013_0003_ingestion_rejection_details.py') -Raw
if ($migration -notmatch 'rejection_details') {
    $errors += 'Day 5 migration does not add structured rejection details.'
}

$tests = Get-Content -LiteralPath (Join-Path $repoRoot 'backend/tests/test_ingestion.py') -Raw
foreach ($scenario in @(
    'mixed_batch',
    'unknown_account',
    'csv_parser',
    'json_endpoint',
    'csv_endpoint',
    'auditor_cannot',
    'published_json_samples',
    'published_csv_samples'
)) {
    if ($tests -notmatch [regex]::Escape($scenario)) {
        $errors += "Transaction ingestion tests are missing scenario: $scenario"
    }
}

$plan = Get-Content -LiteralPath (Join-Path $repoRoot 'PROJECT_PLAN.md') -Raw
if ($plan -notmatch 'Day 5 \| Transaction ingestion \| \*\*Complete\*\*') {
    $errors += 'PROJECT_PLAN.md does not mark Day 5 Complete in the status table.'
}
if ($plan -notmatch '### Day 5[^#]+\*\*Status: Complete\*\*') {
    $errors += 'PROJECT_PLAN.md does not mark the Day 5 detail Complete.'
}

if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Output 'Day 5 validation passed: versioned JSON and CSV ingestion, decimal and UTC validation, permissions, accepted/rejected evidence, migration, deterministic synthetic samples, tests, and roadmap status verified.'
