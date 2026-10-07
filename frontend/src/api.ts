export interface LivenessResponse {
  status: "alive";
  service: string;
  version: string;
  checked_at: string;
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
