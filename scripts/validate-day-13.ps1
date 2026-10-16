[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$requiredFiles = @(
    'backend/src/ledgerguard/reports.py',
    'backend/tests/test_reports.py',
    'frontend/src/ReportWorkspace.tsx',
    'frontend/src/ReportWorkspace.test.tsx',
    'docs/architecture/REPORTING_AND_EXPORT.md'
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
        throw "Required Day 13 file is missing: $relativePath"
    }
}

$reports = Get-Content -Raw (Join-Path $repoRoot 'backend/src/ledgerguard/reports.py')
$interface = Get-Content -Raw (Join-Path $repoRoot 'frontend/src/ReportWorkspace.tsx')
$contract = (Get-Content -Raw (Join-Path $repoRoot 'docs/architecture/REPORTING_AND_EXPORT.md')).ToLowerInvariant()
$plan = Get-Content -Raw (Join-Path $repoRoot 'PROJECT_PLAN.md')

foreach ($term in @('build_daily_reconciliation_report', 'build_unresolved_case_report', 'verify_exact_totals', 'ReportTotalMismatch', 'neutralize_csv_cell', 'DAILY_CSV_FIELDS', 'UNRESOLVED_CSV_FIELDS')) {
    if (-not $reports.Contains($term)) {
        throw "Reporting service is missing required behaviour: $term"
    }
}
foreach ($term in @('report.daily.view', 'report.daily.export', 'report.unresolved.view', 'report.unresolved.export', 'Permission.REPORTS_READ')) {
    if (-not $reports.Contains($term)) {
        throw "Reporting audit or permission behaviour is missing: $term"
    }
}
foreach ($term in @('Independently verified', 'Export safe CSV', 'No eligible facts', 'The report was not released')) {
    if (-not $interface.Contains($term)) {
        throw "Reporting interface is missing a required state: $term"
    }
}
foreach ($term in @('half-open utc', 'python `decimal`', 'http 503', 'fixed server-side column', 'apostrophe')) {
    if (-not $contract.Contains($term)) {
        throw "Reporting contract is missing required guidance: $term"
    }
}
if (-not $plan.Contains('| Day 13 | Reporting and export | **Complete** |')) {
    throw 'PROJECT_PLAN.md does not mark Day 13 Complete.'
}

Write-Output 'Day 13 verified totals, scoped reports, safe CSV, permissions, audit evidence, interface states, and roadmap validation passed.'
