export interface LivenessResponse {
  status: "alive";
  service: string;
  version: string;
  checked_at: string;
}

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  roles: string[];
  permissions: string[];
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  user: AuthUser;
}

export type ReconciliationClassification =
  | "exact_match"
  | "partial_match"
  | "missing_settlement"
  | "duplicate_candidate"
  | "unexplained_settlement";

export interface ReconciliationItem {
  id: string;
  source_record_id: string;
  source_reference: string;
  amount: string;
  currency: string;
  occurred_at: string | null;
  settled_at: string | null;
  item_role: "matched" | "candidate";
  allocated_amount: string | null;
}

export interface ReconciliationResult {
  id: string;
  classification: ReconciliationClassification;
  reason_code: string;
  currency: string;
  transaction_total: string;
  settlement_total: string;
  difference_amount: string;
  evidence: Record<string, unknown>;
  evidence_sha256: string;
  transactions: ReconciliationItem[];
  settlements: ReconciliationItem[];
}

export interface ReconciliationRun {
  run_id: string;
  account_id: string;
  source_system: string;
  source_account_id: string;
  algorithm_version: string;
  input_cutoff_at: string;
  configuration: Record<string, unknown>;
  replay_key: string;
  status: "pending" | "queued" | "running" | "completed" | "failed" | "cancelled";
  replayed: boolean;
  summary: {
    transaction_count: number;
    settlement_count: number;
    transaction_value: string;
    settlement_value: string;
    result_count: number;
    classification_counts: Record<ReconciliationClassification, number>;
  };
  results: ReconciliationResult[];
}

export interface DashboardOverview {
  account_id: string;
  source_system: string;
  source_account_id: string;
  display_name: string;
  currency: string | null;
  metrics: {
    transaction_count: number;
    settlement_count: number;
    transaction_value: string;
    settlement_value: string;
    exact_matched_value: string;
    unresolved_value: string;
    match_rate_percent: string;
    validation_failure_count: number;
    classification_counts: Record<ReconciliationClassification, number>;
  };
  latest_run: ReconciliationRun | null;
  batches: Array<{
    id: string;
    record_kind: "transaction" | "settlement";
    source_system: string;
    status: string;
    source_count: number;
    accepted_count: number;
    rejected_count: number;
    duplicate_count: number;
    conflict_count: number;
    created_at: string;
    finished_at: string | null;
  }>;
}

export type BackgroundJobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface BackgroundJob {
  job_id: string;
  kind: "transaction_ingestion" | "reconciliation";
  status: BackgroundJobStatus;
  replayed: boolean;
  progress_current: number;
  progress_total: number;
  progress_percent: number;
  attempt_count: number;
  max_attempts: number;
  status_message: string | null;
  failure_code: string | null;
  failure_detail: string | null;
  cancellation_requested: boolean;
  ingestion_batch_id: string | null;
  reconciliation_run_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

const configuredApiBaseUrl: unknown = import.meta.env.VITE_API_BASE_URL;
const apiBaseUrl =
  typeof configuredApiBaseUrl === "string" ? configuredApiBaseUrl : "http://localhost:8000";

export async function fetchLiveness(signal?: AbortSignal): Promise<LivenessResponse> {
  const response = await fetch(`${apiBaseUrl}/health/live`, {
    headers: { Accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Health request failed with status ${response.status}`);
  }

  return (await response.json()) as LivenessResponse;
}

export async function loginUser(email: string, password: string): Promise<LoginResponse> {
  const response = await fetch(`${apiBaseUrl}/api/v1/auth/login`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    throw new ApiError(
      response.status === 401 ? "The email or password is incorrect." : "Sign-in failed.",
      response.status,
    );
  }
  return (await response.json()) as LoginResponse;
}

export async function logoutUser(token: string): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/api/v1/auth/logout`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok && response.status !== 401) {
    throw new ApiError("Sign-out failed.", response.status);
  }
}

const dashboardAccount = {
  sourceSystem: "synthetic-reconciliation",
  sourceAccountId: "DEMO-RECON-001",
} as const;

export async function fetchDashboard(
  token: string,
  signal?: AbortSignal,
): Promise<DashboardOverview> {
  const query = new URLSearchParams({
    source_system: dashboardAccount.sourceSystem,
    source_account_id: dashboardAccount.sourceAccountId,
  });
  const response = await fetch(`${apiBaseUrl}/api/v1/dashboard/overview?${query.toString()}`, {
    headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
    signal,
  });
  if (!response.ok) {
    throw new ApiError(
      response.status === 403
        ? "Your role cannot access this dashboard."
        : "Dashboard data could not be loaded.",
      response.status,
    );
  }
  return (await response.json()) as DashboardOverview;
}

export async function createReconciliationRun(
  token: string,
  matchWindowHours: number,
): Promise<BackgroundJob> {
  const idempotencyKey = `dashboard-${crypto.randomUUID()}`;
  const response = await fetch(`${apiBaseUrl}/api/v1/reconciliation/runs`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify({
      source_system: dashboardAccount.sourceSystem,
      source_account_id: dashboardAccount.sourceAccountId,
      input_cutoff_at: new Date().toISOString(),
      match_window_hours: matchWindowHours,
    }),
  });
  if (!response.ok) {
    throw new ApiError(
      response.status === 403
        ? "Your role cannot start reconciliation."
        : "Reconciliation could not be completed.",
      response.status,
    );
  }
  return (await response.json()) as BackgroundJob;
}

export async function fetchBackgroundJob(token: string, jobId: string): Promise<BackgroundJob> {
  const response = await fetch(`${apiBaseUrl}/api/v1/jobs/${jobId}`, {
    headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new ApiError("Background job status could not be loaded.", response.status);
  }
  return (await response.json()) as BackgroundJob;
}

export interface FraudRuleVersion {
  id: string;
  rule_id: string;
  version_number: number;
  rule_type: "velocity" | "unusual_amount" | "repeated_failure" | "duplicate_instrument" | "suspicious_timing";
  parameters: Record<string, unknown>;
  severity: "low" | "medium" | "high" | "critical";
  status: "draft" | "active" | "retired";
  activated_at: string | null;
}

export interface FraudRule {
  id: string;
  code: string;
  name: string;
  description: string | null;
  versions: FraudRuleVersion[];
}

export interface FraudAlert {
  id: string;
  rule_code: string;
  rule_version_id: string;
  rule_version_number: number;
  transaction_id: string;
  source_record_id: string;
  severity: "low" | "medium" | "high" | "critical";
  score: string;
  status: "open" | "in_review" | "closed" | "dismissed";
  reason_code: string;
  evidence: Record<string, unknown>;
  evidence_sha256: string;
  correlation_id: string;
  created_at: string;
}

export interface FraudEvaluation {
  account_id: string;
  input_cutoff_at: string;
  active_rule_count: number;
  subject_count: number;
  triggered_count: number;
  created_count: number;
  replayed_count: number;
  alerts: FraudAlert[];
}

export async function fetchFraudMonitor(
  token: string,
  signal?: AbortSignal,
): Promise<{ rules: FraudRule[]; alerts: FraudAlert[] }> {
  const headers = { Accept: "application/json", Authorization: `Bearer ${token}` };
  const [rulesResponse, alertsResponse] = await Promise.all([
    fetch(`${apiBaseUrl}/api/v1/fraud/rules`, { headers, signal }),
    fetch(`${apiBaseUrl}/api/v1/fraud/alerts?limit=100`, { headers, signal }),
  ]);
  if (!rulesResponse.ok || !alertsResponse.ok) {
    throw new ApiError("Fraud-monitoring evidence could not be loaded.", Math.max(rulesResponse.status, alertsResponse.status));
  }
  return {
    rules: (await rulesResponse.json()) as FraudRule[],
    alerts: (await alertsResponse.json()) as FraudAlert[],
  };
}

export async function runFraudEvaluation(token: string): Promise<FraudEvaluation> {
  const response = await fetch(`${apiBaseUrl}/api/v1/fraud/evaluations`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      source_system: "synthetic-fraud",
      source_account_id: "DEMO-FRAUD-001",
      input_cutoff_at: new Date().toISOString(),
    }),
  });
  if (!response.ok) {
    throw new ApiError(
      response.status === 403 ? "Your role cannot run fraud evaluation." : "Fraud evaluation failed.",
      response.status,
    );
  }
  return (await response.json()) as FraudEvaluation;
}

export type CaseStatus = "open" | "in_review" | "escalated" | "resolved" | "reopened";
export type CasePriority = "low" | "medium" | "high" | "critical";

export interface CaseSummary {
  id: string;
  case_number: number;
  title: string;
  status: CaseStatus;
  priority: CasePriority;
  owner_user_id: string | null;
  owner_display_name: string | null;
  alert_count: number;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface InvestigationCase extends CaseSummary {
  description: string | null;
  resolution_code: string | null;
  resolution_summary: string | null;
  resolved_at: string | null;
  alerts: Array<{
    id: string;
    rule_code: string;
    rule_version_number: number;
    source_record_id: string;
    severity: string;
    score: string | null;
    status: FraudAlert["status"];
    reason_code: string;
    created_at: string;
  }>;
  comments: Array<{
    id: string;
    author_user_id: string;
    author_display_name: string;
    body: string;
    created_at: string;
  }>;
  history: Array<{
    id: string;
    from_status: CaseStatus | null;
    to_status: CaseStatus;
    reason: string;
    changed_by_user_id: string;
    changed_by_display_name: string;
    correlation_id: string;
    changed_at: string;
  }>;
}

export interface CaseFilters {
  status?: CaseStatus;
  priority?: CasePriority;
  owner_user_id?: string;
  unassigned?: boolean;
  rule_code?: string;
  min_age_hours?: number;
}

function caseHeaders(token: string) {
  return {
    Accept: "application/json",
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

async function caseResponse(response: Response, message: string): Promise<InvestigationCase> {
  if (!response.ok) throw new ApiError(message, response.status);
  return (await response.json()) as InvestigationCase;
}

export async function fetchCases(
  token: string,
  filters: CaseFilters = {},
  signal?: AbortSignal,
): Promise<CaseSummary[]> {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.priority) params.set("priority", filters.priority);
  if (filters.owner_user_id) params.set("owner_user_id", filters.owner_user_id);
  if (filters.unassigned) params.set("unassigned", "true");
  if (filters.rule_code) params.set("rule_code", filters.rule_code);
  if (filters.min_age_hours !== undefined) params.set("min_age_hours", String(filters.min_age_hours));
  const response = await fetch(`${apiBaseUrl}/api/v1/cases?${params}`, {
    headers: caseHeaders(token),
    signal,
  });
  if (!response.ok) throw new ApiError("Case queue could not be loaded.", response.status);
  return (await response.json()) as CaseSummary[];
}

export async function fetchCase(token: string, caseId: string): Promise<InvestigationCase> {
  return caseResponse(
    await fetch(`${apiBaseUrl}/api/v1/cases/${caseId}`, { headers: caseHeaders(token) }),
    "Case evidence could not be loaded.",
  );
}

export async function createCase(
  token: string,
  alertId: string,
  title: string,
  priority: CasePriority,
): Promise<InvestigationCase> {
  return caseResponse(
    await fetch(`${apiBaseUrl}/api/v1/cases`, {
      method: "POST",
      headers: caseHeaders(token),
      body: JSON.stringify({ title, priority, alert_ids: [alertId] }),
    }),
    "Case could not be created.",
  );
}

export async function assignCase(
  token: string,
  caseId: string,
  expectedVersion: number,
  ownerUserId: string | null,
): Promise<InvestigationCase> {
  return caseResponse(
    await fetch(`${apiBaseUrl}/api/v1/cases/${caseId}/assignment`, {
      method: "PATCH",
      headers: caseHeaders(token),
      body: JSON.stringify({ expected_version: expectedVersion, owner_user_id: ownerUserId }),
    }),
    "Case assignment could not be saved. Refresh and retry.",
  );
}

export async function commentOnCase(
  token: string,
  caseId: string,
  expectedVersion: number,
  body: string,
): Promise<InvestigationCase> {
  return caseResponse(
    await fetch(`${apiBaseUrl}/api/v1/cases/${caseId}/comments`, {
      method: "POST",
      headers: caseHeaders(token),
      body: JSON.stringify({ expected_version: expectedVersion, body }),
    }),
    "Comment could not be saved. Refresh and retry.",
  );
}

export async function transitionCase(
  token: string,
  investigation: InvestigationCase,
  target: CaseStatus,
  reason: string,
  resolution?: { code: string; summary: string },
): Promise<InvestigationCase> {
  return caseResponse(
    await fetch(`${apiBaseUrl}/api/v1/cases/${investigation.id}/transitions`, {
      method: "POST",
      headers: caseHeaders(token),
      body: JSON.stringify({
        expected_version: investigation.version,
        to_status: target,
        reason,
        resolution_code: resolution?.code,
        resolution_summary: resolution?.summary,
      }),
    }),
    "Case transition was rejected. Refresh and verify the lifecycle.",
  );
}
