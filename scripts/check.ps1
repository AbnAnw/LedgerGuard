[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot 'backend'
$frontendRoot = Join-Path $repoRoot 'frontend'
$python = Join-Path $backendRoot '.venv/Scripts/python.exe'
$frontendTemp = Join-Path $repoRoot 'tmp/frontend-check'
$pipAuditCache = Join-Path $repoRoot 'tmp/pip-audit-cache'

& (Join-Path $PSScriptRoot 'scan-secrets.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Secret scan failed.' }
New-Item -ItemType Directory -Path $pipAuditCache -Force | Out-Null

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
    & $python -m pip_audit --local --skip-editable --cache-dir $pipAuditCache
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency audit failed.' }
    & (Join-Path $backendRoot '.venv/Scripts/alembic.exe') upgrade head --sql | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Alembic offline migration check failed.' }
} finally {
    Pop-Location
}

$previousTemp = $env:TEMP
$previousTmp = $env:TMP
New-Item -ItemType Directory -Path $frontendTemp -Force | Out-Null
$env:TEMP = $frontendTemp
$env:TMP = $frontendTemp
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
    npm audit --audit-level=high
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency audit failed.' }
} finally {
    Pop-Location
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
}

Write-Output 'All LedgerGuard checks passed.'
