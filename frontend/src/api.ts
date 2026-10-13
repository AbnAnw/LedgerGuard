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
): Promise<ReconciliationRun> {
  const response = await fetch(`${apiBaseUrl}/api/v1/reconciliation/runs`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
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
  return (await response.json()) as ReconciliationRun;
}
