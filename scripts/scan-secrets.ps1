[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$patterns = [ordered]@{
    'private key material' = '-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'
    'AWS access key' = '\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'
    'GitHub token' = '\bgh[pousr]_[A-Za-z0-9]{20,}\b'
    'OpenAI-style API key' = '\bsk-[A-Za-z0-9_-]{20,}\b'
    'Google API key' = '\bAIza[0-9A-Za-z_-]{35}\b'
    'Slack token' = '\bxox[baprs]-[0-9A-Za-z-]{10,}\b'
}
$textExtensions = @(
    '.css', '.csv', '.env', '.html', '.ini', '.json', '.md', '.ps1', '.py', '.sql',
    '.toml', '.ts', '.tsx', '.txt', '.yaml', '.yml'
)

$paths = & git -c "safe.directory=$repoRoot" -C $repoRoot ls-files --cached --others --exclude-standard
if ($LASTEXITCODE -ne 0) { throw 'Unable to enumerate repository files for secret scanning.' }

$findings = [System.Collections.Generic.List[string]]::new()
foreach ($relativePath in $paths) {
    $fullPath = Join-Path $repoRoot $relativePath
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) { continue }
    $extension = [System.IO.Path]::GetExtension($fullPath).ToLowerInvariant()
    $fileName = [System.IO.Path]::GetFileName($fullPath)
    if ($textExtensions -notcontains $extension -and $fileName -ne '.env.example') { continue }

    $content = Get-Content -Raw -LiteralPath $fullPath -ErrorAction Stop
    foreach ($entry in $patterns.GetEnumerator()) {
        if ($content -match $entry.Value) {
            $findings.Add("$relativePath matches $($entry.Key)")
        }
    }
}

if ($findings.Count -gt 0) {
    throw "Potential committed secret material found:`n$($findings -join "`n")"
}

Write-Output "Secret scan passed for $($paths.Count) tracked or unignored files."
