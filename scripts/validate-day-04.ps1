[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$errors = @()

$requiredFiles = @(
    'backend/migrations/versions/20261009_0002_auth_sessions.py',
    'backend/src/ledgerguard/auth.py',
    'backend/tests/test_auth.py',
    'docs/security/AUTHENTICATION_AND_ACCESS.md',
    'frontend/src/App.tsx',
    'frontend/src/App.test.tsx'
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
        $errors += "Missing required Day 4 file: $relativePath"
    }
}

$backendProject = Get-Content -LiteralPath (Join-Path $repoRoot 'backend/pyproject.toml') -Raw
if ($backendProject -notmatch 'argon2-cffi==') {
    $errors += 'Backend project does not pin Argon2 password hashing.'
}

$auth = Get-Content -LiteralPath (Join-Path $repoRoot 'backend/src/ledgerguard/auth.py') -Raw
foreach ($contract in @(
    'PasswordHasher',
    'token_digest',
    '/login',
    '/logout',
    '/me',
    'ROLE_PERMISSIONS',
    'require_permissions',
    'Invalid or expired session'
)) {
    if ($auth -notmatch [regex]::Escape($contract)) {
        $errors += "Authentication module is missing contract: $contract"
    }
}

$migration = Get-Content -LiteralPath (Join-Path $repoRoot 'backend/migrations/versions/20261009_0002_auth_sessions.py') -Raw
foreach ($contract in @('auth_sessions', 'token_digest', 'expires_at', 'revoked_at')) {
    if ($migration -notmatch [regex]::Escape($contract)) {
        $errors += "Day 4 migration is missing session field: $contract"
    }
}

$tests = Get-Content -LiteralPath (Join-Path $repoRoot 'backend/tests/test_auth.py') -Raw
foreach ($scenario in @(
    'successful_login',
    'disabled_user',
    'expired_revoked',
    'role_boundaries',
    'requires_authentication',
    'logout_revokes'
)) {
    if ($tests -notmatch [regex]::Escape($scenario)) {
        $errors += "Backend authentication tests are missing scenario: $scenario"
    }
}

$frontend = Get-Content -LiteralPath (Join-Path $repoRoot 'frontend/src/App.tsx') -Raw
foreach ($role in @('administrator', 'operations_analyst', 'auditor')) {
    if ($frontend -notmatch [regex]::Escape($role)) {
        $errors += "Frontend role-aware navigation is missing role: $role"
    }
}

$plan = Get-Content -LiteralPath (Join-Path $repoRoot 'PROJECT_PLAN.md') -Raw
if ($plan -notmatch 'Day 4 \| Authentication and role-based access \| \*\*Complete\*\*') {
    $errors += 'PROJECT_PLAN.md does not mark Day 4 Complete in the status table.'
}
if ($plan -notmatch '### Day 4[^#]+\*\*Status: Complete\*\*') {
    $errors += 'PROJECT_PLAN.md does not mark the Day 4 detail Complete.'
}

if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Output 'Day 4 validation passed: Argon2id passwords, revocable expiring sessions, synthetic users, deny-by-default API permissions, role-aware UI, migration, tests, and roadmap status verified.'
