[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$requiredFiles = @(
    'backend/src/ledgerguard/security.py',
    'backend/src/ledgerguard/database_admin.py',
    'backend/tests/test_security.py',
    'backend/tests/test_database_admin.py',
    'docs/security/SECURITY_AND_PRIVACY.md',
    'scripts/scan-secrets.ps1',
    '.github/dependabot.yml'
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
        throw "Required Day 16 file is missing: $relativePath"
    }
}

$review = (Get-Content -Raw (Join-Path $repoRoot 'docs/security/SECURITY_AND_PRIVACY.md')).ToLowerInvariant()
$security = Get-Content -Raw (Join-Path $repoRoot 'backend/src/ledgerguard/security.py')
$databaseAdmin = Get-Content -Raw (Join-Path $repoRoot 'backend/src/ledgerguard/database_admin.py')
$compose = Get-Content -Raw (Join-Path $repoRoot 'docker-compose.yml')
$workflow = Get-Content -Raw (Join-Path $repoRoot '.github/workflows/ci.yml')
$plan = Get-Content -Raw (Join-Path $repoRoot 'PROJECT_PLAN.md')

foreach ($term in @(
    'credential stuffing', 'privilege escalation', 'malicious csv/json upload',
    'excessive resource use', 'secret exposure', 'audit tampering', 'retention',
    'residual risk', 'synthetic data', 'database boundary'
)) {
    if (-not $review.Contains($term)) {
        throw "Security review is missing required guidance: $term"
    }
}
foreach ($term in @(
    'SecurityMiddleware', 'RedisRateLimiter', 'REQUEST_TOO_LARGE', 'RATE_LIMITED',
    'strict-transport-security', 'enforce_synthetic_source'
)) {
    if (-not $security.Contains($term)) {
        throw "Security implementation is missing: $term"
    }
}
foreach ($term in @(
    'NOCREATEDB', 'NOCREATEROLE', 'REVOKE CREATE ON SCHEMA public',
    'REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_events'
)) {
    if (-not $databaseAdmin.Contains($term)) {
        throw "Runtime database provisioning is missing: $term"
    }
}
foreach ($term in @(
    'migrate:', 'service_completed_successfully', 'DATABASE_RUNTIME_USER',
    'RATE_LIMIT_ENABLED', 'SYNTHETIC_DATA_ONLY'
)) {
    if (-not $compose.Contains($term)) {
        throw "Compose security topology is missing: $term"
    }
}
foreach ($term in @('python -m pip_audit', '--skip-editable', 'npm audit --audit-level=high', './scripts/scan-secrets.ps1')) {
    if (-not $workflow.Contains($term)) {
        throw "CI security scan is missing: $term"
    }
}
if (-not $plan.Contains('| Day 16 | Security and privacy review | **Complete** |')) {
    throw 'PROJECT_PLAN.md does not mark Day 16 Complete.'
}

& (Join-Path $PSScriptRoot 'scan-secrets.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Day 16 secret scan failed.' }

Write-Output 'Day 16 threat model, boundary controls, least-privilege database, scans, and roadmap validation passed.'
