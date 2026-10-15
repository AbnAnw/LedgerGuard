import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuthUser } from "./api";
import { FraudMonitor } from "./FraudMonitor";

const auditor: AuthUser = {
  id: "00000000-0000-0000-0000-000000000001",
  email: "auditor@ledgerguard.invalid",
  display_name: "Synthetic Auditor",
  roles: ["auditor"],
  permissions: ["alerts:read"],
};

const analyst: AuthUser = {
  ...auditor,
  email: "analyst@ledgerguard.invalid",
  roles: ["operations_analyst"],
  permissions: ["alerts:read", "alerts:write"],
};

function response(value: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(value) });
}

describe("FraudMonitor", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows auditor evidence without evaluation controls", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url =
          typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        return response(url.includes("/rules") ? [] : []);
      }),
    );
    render(<FraudMonitor token="token" user={auditor} />);

    expect(await screen.findByRole("heading", { name: /every alert carries/i })).toBeVisible();
    expect(screen.getByText("No alerts yet")).toBeVisible();
    expect(screen.getAllByText("Read only")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /evaluate synthetic/i })).not.toBeInTheDocument();
  });

  it("lets an analyst run evaluation and reports idempotent results", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/evaluations") && init?.method === "POST") {
        return response({ created_count: 2, replayed_count: 1, alerts: [] });
      }
      return response([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<FraudMonitor token="token" user={analyst} />);

    fireEvent.click(await screen.findByRole("button", { name: "Evaluate synthetic account" }));
    expect(await screen.findByText("2 new alerts; 1 existing alert.")).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));
  });
});
