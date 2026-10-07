[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$errors = @()

$requiredFiles = @(
    'backend/Dockerfile',
    'backend/alembic.ini',
    'backend/pyproject.toml',
    'backend/migrations/env.py',
    'backend/migrations/versions/20261007_0001_initial_schema.py',
    'backend/src/ledgerguard/cli.py',
    'backend/src/ledgerguard/config.py',
    'backend/src/ledgerguard/main.py',
    'backend/src/ledgerguard/models.py',
    'backend/src/ledgerguard/worker.py',
    'docker-compose.yml',
    'frontend/Dockerfile',
    'frontend/package-lock.json',
    'frontend/package.json',
    'frontend/src/App.tsx',
    'frontend/src/api.ts',
    'scripts/bootstrap.ps1',
    'scripts/check.ps1',
    'worker/README.md'
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
        $errors += "Missing required Day 3 file: $relativePath"
    }
}

$composePath = Join-Path $repoRoot 'docker-compose.yml'
if (Test-Path -LiteralPath $composePath) {
    $compose = Get-Content -LiteralPath $composePath -Raw
    foreach ($service in @('postgres', 'redis', 'api', 'worker', 'frontend')) {
        if ($compose -notmatch "(?m)^  $service`:") {
            $errors += "Docker Compose is missing service: $service"
        }
    }
    foreach ($healthCheck in @('/health/ready', 'celery')) {
        if ($compose -notmatch [regex]::Escape($healthCheck)) {
            $errors += "Docker Compose is missing health-check evidence: $healthCheck"
        }
    }
}

$mainPath = Join-Path $repoRoot 'backend/src/ledgerguard/main.py'
if (Test-Path -LiteralPath $mainPath) {
    $main = Get-Content -LiteralPath $mainPath -Raw
    foreach ($endpoint in @('/health/live', '/health/ready')) {
        if ($main -notmatch [regex]::Escape($endpoint)) {
            $errors += "FastAPI application is missing health endpoint: $endpoint"
        }
    }
}

$migrationPath = Join-Path $repoRoot 'backend/migrations/versions/20261007_0001_initial_schema.py'
if (Test-Path -LiteralPath $migrationPath) {
    $migration = Get-Content -LiteralPath $migrationPath -Raw
    $tableCount = ([regex]::Matches($migration, 'op\.create_table\(')).Count
    if ($tableCount -ne 20) {
        $errors += "Initial migration defines $tableCount domain tables; expected 20"
    }
    foreach ($contract in @('Numeric(precision=20, scale=6)', 'DateTime(timezone=True)', 'audit_events_append_only')) {
        if ($migration -notmatch [regex]::Escape($contract)) {
            $errors += "Initial migration is missing contract: $contract"
        }
    }
}

$backendProjectPath = Join-Path $repoRoot 'backend/pyproject.toml'
if (Test-Path -LiteralPath $backendProjectPath) {
    $backendProject = Get-Content -LiteralPath $backendProjectPath -Raw
    foreach ($dependency in @('fastapi', 'sqlalchemy', 'alembic', 'celery', 'redis', 'psycopg')) {
        if ($backendProject -notmatch "(?m)^\s*`"?$dependency") {
            $errors += "Backend project is missing dependency: $dependency"
        }
    }
    foreach ($tool in @('[tool.ruff]', '[tool.mypy]', '[tool.pytest.ini_options]')) {
        if ($backendProject -notmatch [regex]::Escape($tool)) {
            $errors += "Backend project is missing quality configuration: $tool"
        }
    }
}

$frontendProjectPath = Join-Path $repoRoot 'frontend/package.json'
if (Test-Path -LiteralPath $frontendProjectPath) {
    $frontendProject = Get-Content -LiteralPath $frontendProjectPath -Raw | ConvertFrom-Json
    foreach ($script in @('dev', 'build', 'lint', 'typecheck', 'test')) {
        if (-not $frontendProject.scripts.$script) {
            $errors += "Frontend package is missing script: $script"
        }
    }
}

$envExamplePath = Join-Path $repoRoot '.env.example'
if (Test-Path -LiteralPath $envExamplePath) {
    $envExample = Get-Content -LiteralPath $envExamplePath -Raw
    foreach ($setting in @('DATABASE_URL=', 'REDIS_URL=', 'CORS_ORIGINS=', 'VITE_API_BASE_URL=')) {
        if ($envExample -notmatch [regex]::Escape($setting)) {
            $errors += ".env.example is missing setting: $setting"
        }
    }
}

$planPath = Join-Path $repoRoot 'PROJECT_PLAN.md'
if (Test-Path -LiteralPath $planPath) {
    $plan = Get-Content -LiteralPath $planPath -Raw
    if ($plan -notmatch 'Day 3 \| Local platform foundation \| \*\*Complete\*\*') {
        $errors += 'PROJECT_PLAN.md does not mark Day 3 Complete in the status table'
    }
    if ($plan -notmatch '### Day 3[^#]+\*\*Status: Complete\*\*') {
        $errors += 'PROJECT_PLAN.md does not mark the Day 3 detail Complete'
    }
}

if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_ }
    exit 1
}

Write-Output 'Day 3 validation passed: application foundations, five Compose services, 20-table migration, quality tooling, environment contract, and roadmap status verified.'
