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
