[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$errors = [System.Collections.Generic.List[string]]::new()

$requiredPaths = @(
    'AGENTS.md',
    'README.md',
    'PROJECT_PLAN.md',
    'PROGRESS.md',
    '.gitignore',
    '.env.example',
    'backend',
    'frontend',
    'worker',
    'tests',
    'docs/PRODUCT_SPEC.md',
    'docs/architecture/OVERVIEW.md',
    'docs/decisions',
    'docs/security',
    'docs/operations/LOCAL_DEVELOPMENT.md',
    'sample-data',
    'scripts',
    'infra',
    '.github/workflows'
)

foreach ($relativePath in $requiredPaths) {
    $fullPath = Join-Path $repoRoot $relativePath
    if (-not (Test-Path -LiteralPath $fullPath)) {
        $errors.Add("Missing required path: $relativePath")
    }
}

$planPath = Join-Path $repoRoot 'PROJECT_PLAN.md'
if (Test-Path -LiteralPath $planPath) {
    $plan = Get-Content -LiteralPath $planPath -Raw
    foreach ($day in 1..21) {
        $dayLabel = 'Day {0}' -f $day
        if ($plan -notmatch [regex]::Escape($dayLabel)) {
            $errors.Add("PROJECT_PLAN.md does not contain $dayLabel")
        }
    }
    if ($plan -notmatch 'Day 1.*Complete') {
        $errors.Add('PROJECT_PLAN.md does not mark Day 1 Complete')
    }
}

$productSpecPath = Join-Path $repoRoot 'docs/PRODUCT_SPEC.md'
if (Test-Path -LiteralPath $productSpecPath) {
    $productSpec = Get-Content -LiteralPath $productSpecPath -Raw
    foreach ($topic in @('Administrator', 'Operations analyst', 'Auditor', 'Ingestion', 'Reconciliation', 'Alerts', 'Investigations', 'Reports', 'Scope', 'Success metrics', 'Risks')) {
        if ($productSpec -notmatch [regex]::Escape($topic)) {
            $errors.Add("Product specification is missing topic: $topic")
        }
    }
}

$environmentPath = Join-Path $repoRoot '.env.example'
if (Test-Path -LiteralPath $environmentPath) {
    $environment = Get-Content -LiteralPath $environmentPath -Raw
    if ($environment -notmatch 'replace-with-') {
        $errors.Add('.env.example does not clearly use placeholder secrets')
    }
}

$readmePath = Join-Path $repoRoot 'README.md'
if (Test-Path -LiteralPath $readmePath) {
    $readme = Get-Content -LiteralPath $readmePath -Raw
    if ($readme -notmatch 'synthetic') {
        $errors.Add('README.md does not state the synthetic-data constraint')
    }
}

$branch = git -C $repoRoot branch --show-current
if ($LASTEXITCODE -ne 0 -or $branch.Trim() -ne 'main') {
    $errors.Add("Expected Git branch 'main', found '$branch'")
}

if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Output "Day 1 validation passed: $($requiredPaths.Count) required paths, 21 roadmap days, product topics, safe environment placeholders, synthetic-data notice, and main branch verified."
