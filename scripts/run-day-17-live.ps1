[CmdletBinding()]
param(
    [string]$ApiBaseUrl = 'http://localhost:8000',
    [string]$DemoPassword = 'DemoOnly!ChangeMe123456',
    [int]$LatencySamples = 20,
    [int]$TimeoutSeconds = 600
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot 'backend/.venv/Scripts/python.exe'
$artifactDirectory = Join-Path $repoRoot 'tmp'
$payloadPath = Join-Path $artifactDirectory 'day17-live-ingestion.json'
$resultPath = Join-Path $artifactDirectory 'day17-live-results.json'
$runId = 'D17-' + [DateTimeOffset]::UtcNow.ToString('yyyyMMddHHmmss')
$idempotencyKey = "day17-$runId"
$workerStopped = $false
$postgresStopped = $false

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed: $($Arguments -join ' ')"
    }
}

function Get-ApiResponse {
    param([string]$Uri, [hashtable]$Headers = @{})
    try {
        return Invoke-WebRequest -Method Get -Uri $Uri -Headers $Headers -TimeoutSec 5 -SkipHttpErrorCheck
    }
    catch {
        return $null
    }
}

function Wait-ForJob {
    param([string]$JobId, [hashtable]$Headers)
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $response = Invoke-RestMethod -Method Get -Uri "$ApiBaseUrl/api/v1/jobs/$JobId" -Headers $Headers -TimeoutSec 10
        if ($response.status -in @('succeeded', 'failed', 'cancelled')) {
            return $response
        }
        Start-Sleep -Seconds 1
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw "Job $JobId did not become terminal within $TimeoutSeconds seconds."
}

if ($LatencySamples -lt 2) {
    throw 'LatencySamples must be at least 2.'
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'The backend virtual environment is missing. Run the documented setup first.'
}
New-Item -ItemType Directory -Path $artifactDirectory -Force | Out-Null

try {
    $previousRunId = $env:LEDGERGUARD_PERFORMANCE_RUN_ID
    $previousPythonPath = $env:PYTHONPATH
    $env:LEDGERGUARD_PERFORMANCE_RUN_ID = $runId
    try {
        Push-Location (Join-Path $repoRoot 'backend')
        $env:PYTHONPATH = 'src'
        & $python -m ledgerguard.performance --samples 1 --warmups 0 --ingestion-payload $payloadPath | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Unable to generate the synthetic workload.' }
    }
    finally {
        Pop-Location
        $env:LEDGERGUARD_PERFORMANCE_RUN_ID = $previousRunId
        $env:PYTHONPATH = $previousPythonPath
    }

    Invoke-Compose -Arguments @(
        'exec', '-T', '-e', "LEDGERGUARD_PERFORMANCE_RUN_ID=$runId",
        'api', 'ledgerguard-seed-performance'
    )

    $loginBody = @{
        email = 'analyst@ledgerguard.invalid'
        password = $DemoPassword
    } | ConvertTo-Json
    $login = Invoke-RestMethod -Method Post -Uri "$ApiBaseUrl/api/v1/auth/login" -ContentType 'application/json' -Body $loginBody
    $authHeaders = @{ Authorization = "Bearer $($login.access_token)" }
    $ingestionHeaders = @{
        Authorization = "Bearer $($login.access_token)"
        'Idempotency-Key' = $idempotencyKey
    }

    Invoke-Compose -Arguments @('stop', 'worker')
    $workerStopped = $true

    $latencyMilliseconds = [System.Collections.Generic.List[double]]::new()
    $jobId = $null
    $apiFailureCount = 0
    for ($index = 0; $index -lt $LatencySamples; $index++) {
        $timer = [System.Diagnostics.Stopwatch]::StartNew()
        try {
            $submission = Invoke-RestMethod -Method Post -Uri "$ApiBaseUrl/api/v1/ingestion/transactions/json" -Headers $ingestionHeaders -ContentType 'application/json' -InFile $payloadPath -TimeoutSec 60
            if ($null -eq $jobId) { $jobId = [string]$submission.job_id }
            if ([string]$submission.job_id -ne $jobId) {
                throw 'An idempotent replay returned a different durable job.'
            }
        }
        catch {
            $apiFailureCount++
            throw
        }
        finally {
            $timer.Stop()
            $latencyMilliseconds.Add($timer.Elapsed.TotalMilliseconds)
        }
    }

    if ([string]::IsNullOrWhiteSpace($jobId)) { throw 'No durable job was returned.' }
    Invoke-Compose -Arguments @('up', '-d', 'worker')
    $workerStopped = $false
    $job = Wait-ForJob -JobId $jobId -Headers $authHeaders
    if ($job.status -ne 'succeeded') {
        throw "The bulk ingestion job ended as $($job.status): $($job.failure_code)"
    }

    $workerSeconds = (
        $job.finished_at.ToUniversalTime() - $job.started_at.ToUniversalTime()
    ).TotalSeconds
    if ($workerSeconds -le 0) { throw 'Worker processing time was not positive.' }

    $orderedLatency = @($latencyMilliseconds | Sort-Object)
    $p50Index = [Math]::Ceiling(0.50 * $orderedLatency.Count) - 1
    $p95Index = [Math]::Ceiling(0.95 * $orderedLatency.Count) - 1

    $readyBefore = Get-ApiResponse -Uri "$ApiBaseUrl/health/ready"
    if ($null -eq $readyBefore -or $readyBefore.StatusCode -ne 200) {
        throw 'API readiness was not healthy before the database reconnection drill.'
    }
    Invoke-Compose -Arguments @('stop', 'postgres')
    $postgresStopped = $true
    $readyWhileStopped = Get-ApiResponse -Uri "$ApiBaseUrl/health/ready"
    $unavailableObserved = $null -eq $readyWhileStopped -or $readyWhileStopped.StatusCode -ne 200
    if (-not $unavailableObserved) {
        throw 'Readiness did not report the stopped database.'
    }
    Invoke-Compose -Arguments @('start', 'postgres')
    $postgresStopped = $false
    $recoveryDeadline = [DateTimeOffset]::UtcNow.AddSeconds(120)
    $readyAfter = $null
    do {
        Start-Sleep -Seconds 1
        $readyAfter = Get-ApiResponse -Uri "$ApiBaseUrl/health/ready"
    } while (($null -eq $readyAfter -or $readyAfter.StatusCode -ne 200) -and [DateTimeOffset]::UtcNow -lt $recoveryDeadline)
    if ($null -eq $readyAfter -or $readyAfter.StatusCode -ne 200) {
        throw 'The existing API process did not recover after PostgreSQL restarted.'
    }
    $jobAfterReconnect = Invoke-RestMethod -Method Get -Uri "$ApiBaseUrl/api/v1/jobs/$jobId" -Headers $authHeaders -TimeoutSec 10
    if ($jobAfterReconnect.status -ne 'succeeded') {
        throw 'The authenticated database query failed after reconnection.'
    }

    $dockerVersion = (& docker version --format '{{.Server.Version}}').Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Unable to record Docker version.' }
    $result = [ordered]@{
        schema_version = 'day-17-live-v1'
        measured_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        environment = [ordered]@{
            operating_system = [System.Environment]::OSVersion.VersionString
            logical_cpu_count = [System.Environment]::ProcessorCount
            docker_server_version = $dockerVersion
            compose_project = 'ledgerguard'
        }
        dataset = [ordered]@{
            version = 'performance-v1'
            run_id = $runId
            transaction_count = 10000
            payload_bytes = (Get-Item -LiteralPath $payloadPath).Length
        }
        api = [ordered]@{
            request_count = $LatencySamples
            failure_count = $apiFailureCount
            failure_rate_percent = [Math]::Round(100 * $apiFailureCount / $LatencySamples, 2)
            p50_latency_milliseconds = [Math]::Round($orderedLatency[$p50Index], 3)
            p95_latency_milliseconds = [Math]::Round($orderedLatency[$p95Index], 3)
        }
        worker = [ordered]@{
            job_id = $jobId
            status = [string]$job.status
            attempt_count = [int]$job.attempt_count
            processing_seconds = [Math]::Round($workerSeconds, 6)
            throughput_transactions_per_second = [Math]::Round(10000 / $workerSeconds, 2)
        }
        resilience = [ordered]@{
            worker_restart_completed_original_job = $true
            duplicate_api_deliveries_shared_job = $true
            database_unavailability_observed = $unavailableObserved
            existing_api_reconnected = $true
        }
    }
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $resultPath -Encoding utf8
    $result | ConvertTo-Json -Depth 8
}
finally {
    if ($postgresStopped) { & docker compose start postgres | Out-Null }
    if ($workerStopped) { & docker compose up -d worker | Out-Null }
}
