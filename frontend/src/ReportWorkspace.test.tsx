import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReportWorkspace } from "./ReportWorkspace";

const daily = {
  report_date: "2026-10-16",
  window_start: "2026-10-16T00:00:00Z",
  window_end: "2026-10-17T00:00:00Z",
  generated_at: "2026-10-16T12:00:00Z",
  account_id: "00000000-0000-0000-0000-000000000001",
  source_system: "synthetic-reconciliation",
  source_account_id: "DEMO-RECON-001",
  totals_verified: true,
  currency_totals: [
    {
      currency: "USD",
      transaction_count: 4,
      transaction_total: "250.000000",
      settlement_count: 5,
      settlement_total: "215.000000",
      difference: "-35.000000",
    },
  ],
  reconciliation_snapshot: {
    run_id: "00000000-0000-0000-0000-000000000002",
    input_cutoff_at: "2026-10-16T11:00:00Z",
    algorithm_version: "reconciliation-v1.0.0",
    result_count: 1,
    classifications: [
      {
        classification: "exact_match",
        result_count: 1,
        transaction_total: "100.000000",
        settlement_total: "100.000000",
        difference_total: "0.000000",
      },
    ],
  },
};

const unresolved = {
  cutoff_at: "2026-10-16T12:00:00Z",
  generated_at: "2026-10-16T12:00:00Z",
  case_count: 1,
  cases: [
    {
      case_id: "00000000-0000-0000-0000-000000000003",
      case_number: 42,
      title: "Synthetic unusual amount review",
      status: "in_review",
      priority: "high",
      owner_user_id: null,
      owner_display_name: null,
      created_at: "2026-10-15T12:00:00Z",
      age_hours: 24,
      alert_count: 2,
      rule_codes: ["unusual_amount"],
    },
  ],
};

function jsonResponse(value: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    headers: new Headers(),
    json: () => Promise.resolve(value),
  });
}

describe("ReportWorkspace", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows independently verified totals, unresolved cases, and downloads safe CSV", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith(".csv") || url.includes(".csv?")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({
            "Content-Disposition": 'attachment; filename="ledgerguard-daily-reconciliation.csv"',
          }),
          blob: () => Promise.resolve(new Blob(["safe,csv"])),
        });
      }
      return url.includes("unresolved-cases") ? jsonResponse(unresolved) : jsonResponse(daily);
    });
    vi.stubGlobal("fetch", fetchMock);
    const createObjectURL = vi.fn(() => "blob:synthetic-report");
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectURL,
    });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    render(<ReportWorkspace token="token" />);

    expect(screen.getByText("Verifying report totals")).toBeVisible();
    expect(await screen.findByText("✓ Independently verified")).toBeVisible();
    expect(screen.getByText("250.000000")).toBeVisible();
    expect(screen.getByText(/Case #42/)).toBeVisible();
    expect(screen.getByText(/Unassigned · unusual_amount/)).toBeVisible();

    fireEvent.click(screen.getAllByRole("button", { name: "Export safe CSV" })[0]);
    await waitFor(() => expect(createObjectURL).toHaveBeenCalledOnce());
    expect(click).toHaveBeenCalledOnce();
  });

  it("shows explicit empty states when both verified reports contain no rows", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        return url.includes("unresolved-cases")
          ? jsonResponse({ ...unresolved, case_count: 0, cases: [] })
          : jsonResponse({ ...daily, currency_totals: [], reconciliation_snapshot: null });
      }),
    );

    render(<ReportWorkspace token="token" />);

    expect(await screen.findByText("No eligible facts for this UTC date")).toBeVisible();
    expect(screen.getByText("No unresolved cases")).toBeVisible();
    expect(screen.getByText(/No completed reconciliation snapshot/)).toBeVisible();
  });

  it("withholds a failed report and offers a retry", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        return url.includes("daily-reconciliation")
          ? jsonResponse({ detail: { code: "REPORT_TOTAL_MISMATCH" } }, false, 503)
          : jsonResponse(unresolved);
      }),
    );

    render(<ReportWorkspace token="token" />);

    expect(await screen.findByText("The report was not released")).toBeVisible();
    expect(screen.getByText(/Independent totals did not match/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Retry verification" })).toBeVisible();
  });
});
