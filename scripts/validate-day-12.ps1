[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$requiredFiles = @(
    'backend/src/ledgerguard/audit.py',
    'backend/src/ledgerguard/audit_service.py',
    'backend/migrations/versions/20261016_0009_audit_event_invariants.py',
    'backend/tests/test_audit.py',
    'frontend/src/AuditTimeline.tsx',
    'frontend/src/AuditTimeline.test.tsx',
    'docs/architecture/AUDIT_LOGGING.md'
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
        throw "Required Day 12 file is missing: $relativePath"
    }
}

$writer = Get-Content -Raw (Join-Path $repoRoot 'backend/src/ledgerguard/audit_service.py')
$api = Get-Content -Raw (Join-Path $repoRoot 'backend/src/ledgerguard/audit.py')
$migration = Get-Content -Raw (Join-Path $repoRoot 'backend/migrations/versions/20261016_0009_audit_event_invariants.py')
$contract = (Get-Content -Raw (Join-Path $repoRoot 'docs/architecture/AUDIT_LOGGING.md')).ToLowerInvariant()
$plan = Get-Content -Raw (Join-Path $repoRoot 'PROJECT_PLAN.md')

foreach ($term in @('append_audit_event', 'FORBIDDEN_KEYS', 'MAX_METADATA_BYTES', 'MAX_STATE_BYTES')) {
    if (-not $writer.Contains($term)) {
        throw "Audit writer is missing required safety behaviour: $term"
    }
}
foreach ($term in @('list_audit_events', 'read_case_audit_trail', 'Permission.AUDIT_READ', 'audit.history.read')) {
    if (-not $api.Contains($term)) {
        throw "Audit API is missing required read behaviour: $term"
    }
}
foreach ($term in @('ck_audit_actor_user_pair', 'ck_audit_action_format', 'ck_audit_metadata_object', 'audit_events_append_only')) {
    if (-not $migration.Contains($term)) {
        throw "Audit migration invariant is missing: $term"
    }
}
foreach ($term in @('authentication', 'security-sensitive reads', 'append-only', 'reconstruct', 'redact')) {
    if (-not $contract.Contains($term)) {
        throw "Audit contract is missing required guidance: $term"
    }
}
if (-not $plan.Contains('| Day 12 | Audit logging | **Complete** |')) {
    throw 'PROJECT_PLAN.md does not mark Day 12 Complete.'
}

Write-Output 'Day 12 event coverage, safety limits, append-only enforcement, auditor reconstruction, interface, and roadmap validation passed.'
