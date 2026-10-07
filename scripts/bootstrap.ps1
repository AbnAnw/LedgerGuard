[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot 'backend'
$frontendRoot = Join-Path $repoRoot 'frontend'

$python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $python) {
    $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -eq $pythonLauncher) {
        throw 'Python 3.12 is required. Install it or use Docker Compose.'
    }
    & $pythonLauncher.Source -3.12 -m venv (Join-Path $backendRoot '.venv')
} else {
    & $python.Source -m venv (Join-Path $backendRoot '.venv')
}

$venvPython = Join-Path $backendRoot '.venv/Scripts/python.exe'
& $venvPython -m pip install --disable-pip-version-check -e "$backendRoot[dev]"
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }

Push-Location $frontendRoot
try {
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
} finally {
    Pop-Location
}

Write-Output 'LedgerGuard development dependencies installed.'
