[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot 'backend'
$frontendRoot = Join-Path $repoRoot 'frontend'
$python = Join-Path $backendRoot '.venv/Scripts/python.exe'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Backend virtual environment is missing. Run ./scripts/bootstrap.ps1 first.'
}

Push-Location $backendRoot
try {
    & $python -m ruff format --check src tests migrations
    if ($LASTEXITCODE -ne 0) { throw 'Backend format check failed.' }
    & $python -m ruff check src tests migrations
    if ($LASTEXITCODE -ne 0) { throw 'Backend lint failed.' }
    & $python -m mypy src
    if ($LASTEXITCODE -ne 0) { throw 'Backend type check failed.' }
    & $python -m pytest --cov=ledgerguard --cov-report=term
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
    & (Join-Path $backendRoot '.venv/Scripts/alembic.exe') upgrade head --sql | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Alembic offline migration check failed.' }
} finally {
    Pop-Location
}

Push-Location $frontendRoot
try {
    npm run lint
    if ($LASTEXITCODE -ne 0) { throw 'Frontend lint failed.' }
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Frontend type check failed.' }
    npm run test
    if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally {
    Pop-Location
}

Write-Output 'All LedgerGuard checks passed.'
