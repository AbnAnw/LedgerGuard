import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AuthUser,
  BackgroundJob,
  DashboardOverview,
  ReconciliationClassification,
  ReconciliationResult,
} from "./api";
import { Dashboard } from "./Dashboard";

const analyst: AuthUser = {
  id: "00000000-0000-0000-0000-000000000001",
  email: "analyst@ledgerguard.invalid",
  display_name: "Synthetic Operations Analyst",
  roles: ["operations_analyst"],
  permissions: ["transactions:read", "reconciliation:read", "reconciliation:write"],
};

const auditor: AuthUser = {
  ...analyst,
  email: "auditor@ledgerguard.invalid",
  display_name: "Synthetic Auditor",
  roles: ["auditor"],
  permissions: ["transactions:read", "reconciliation:read"],
};

function reconciliationResult(
  id: string,
  classification: ReconciliationClassification,
  reference: string,
  transactionTotal: string,
  settlementTotal: string,
  difference: string,
): ReconciliationResult {
  const hasTransaction = classification !== "unexplained_settlement";
  const hasSettlement = classification !== "missing_settlement";
  return {
    id,
    classification,
    reason_code: `${classification.toUpperCase()}_REASON`,
    currency: "USD",
    transaction_total: transactionTotal,
    settlement_total: settlementTotal,
    difference_amount: difference,
    evidence: { classification, source: "synthetic" },
    evidence_sha256: id.padEnd(64, "a"),
    transactions: hasTransaction
      ? [
          {
            id: `tx-${id}`,
            source_record_id: `TX-${id}`,
            source_reference: reference,
            amount: transactionTotal,
            currency: "USD",
            occurred_at: "2026-10-14T09:00:00Z",
            settled_at: null,
            item_role: classification === "duplicate_candidate" ? "candidate" : "matched",
            allocated_amount: classification === "exact_match" ? transactionTotal : null,
          },
        ]
      : [],
    settlements: hasSettlement
      ? [
          {
            id: `st-${id}`,
            source_record_id: `ST-${id}`,
            source_reference: reference,
            amount: settlementTotal,
            currency: "USD",
            occurred_at: null,
            settled_at: "2026-10-14T10:00:00Z",
            item_role: classification === "duplicate_candidate" ? "candidate" : "matched",
            allocated_amount: classification === "exact_match" ? settlementTotal : null,
          },
        ]
      : [],
  };
}

function overview(withRun = true): DashboardOverview {
  const results = [
    reconciliationResult("1", "exact_match", "REF-EXACT", "100.000000", "100.000000", "0.000000"),
    reconciliationResult("2", "partial_match", "REF-PARTIAL", "100.000000", "60.000000", "-40.000000"),
    reconciliationResult("3", "missing_settlement", "REF-MISSING", "30.000000", "0", "-30.000000"),
    reconciliationResult("4", "duplicate_candidate", "REF-DUPLICATE", "20.000000", "40.000000", "20.000000"),
    reconciliationResult("5", "unexplained_settlement", "REF-UNEXPLAINED", "0", "15.000000", "15.000000"),
  ];
  return {
    account_id: "00000000-0000-0000-0000-000000000200",
    source_system: "synthetic-reconciliation",
    source_account_id: "DEMO-RECON-001",
    display_name: "Synthetic Reconciliation Demonstration Account",
    currency: "USD",
    metrics: {
      transaction_count: 4,
      settlement_count: 5,
      transaction_value: "250.000000",
      settlement_value: "215.000000",
      exact_matched_value: "100.000000",
      unresolved_value: "185.000000",
      match_rate_percent: "40.00",
      validation_failure_count: 1,
      classification_counts: {
        exact_match: 1,
        partial_match: 1,
        missing_settlement: 1,
        duplicate_candidate: 1,
        unexplained_settlement: 1,
      },
    },
    latest_run: withRun
      ? {
          run_id: "00000000-0000-0000-0000-000000000100",
          account_id: "00000000-0000-0000-0000-000000000200",
          source_system: "synthetic-reconciliation",
          source_account_id: "DEMO-RECON-001",
          algorithm_version: "reconciliation-v1.0.0",
          input_cutoff_at: "2026-10-14T12:00:00Z",
          configuration: { match_window_hours: 72 },
          replay_key: "b".repeat(64),
          status: "completed",
          replayed: false,
          summary: {
            transaction_count: 4,
            settlement_count: 5,
            transaction_value: "250.000000",
            settlement_value: "215.000000",
            result_count: 5,
            classification_counts: {
              exact_match: 1,
              partial_match: 1,
              missing_settlement: 1,
              duplicate_candidate: 1,
              unexplained_settlement: 1,
            },
          },
          results,
        }
      : null,
    batches: [
      {
        id: "00000000-0000-0000-0000-000000000300",
        record_kind: "transaction",
        source_system: "synthetic-reconciliation-v1",
        status: "completed_with_errors",
        source_count: 5,
        accepted_count: 4,
        rejected_count: 1,
        duplicate_count: 0,
        conflict_count: 0,
        created_at: "2026-10-14T09:00:00Z",
        finished_at: "2026-10-14T09:01:00Z",
      },
    ],
  };
}

function response(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  });
}

function reconciliationJob(status: BackgroundJob["status"]): BackgroundJob {
  const terminal = status === "succeeded" || status === "failed" || status === "cancelled";
  return {
    job_id: "00000000-0000-0000-0000-000000000900",
    kind: "reconciliation",
    status,
    replayed: false,
    progress_current: status === "succeeded" ? 3 : 1,
    progress_total: 3,
    progress_percent: status === "succeeded" ? 100 : 33,
    attempt_count: 1,
    max_attempts: 3,
    status_message:
      status === "succeeded" ? "Processing completed successfully." : "Loading facts.",
    failure_code: null,
    failure_detail: null,
    cancellation_requested: false,
    ingestion_batch_id: null,
    reconciliation_run_id:
      status === "succeeded" ? "00000000-0000-0000-0000-000000000100" : null,
    created_at: "2026-10-14T12:00:00Z",
    started_at: "2026-10-14T12:00:01Z",
    finished_at: terminal ? "2026-10-14T12:00:02Z" : null,
  };
}

describe("Dashboard", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows metrics and puts the largest unresolved result first", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => response(overview())));

    render(<Dashboard token="token" user={analyst} />);

    expect(await screen.findByText("USD 250.000000")).toBeVisible();
    expect(screen.getByText("USD 185.000000")).toBeVisible();
    expect(screen.getByText("40.00%")).toBeVisible();
    const table = screen.getByRole("heading", { name: "Reconciliation results" }).closest("section");
    expect(table).not.toBeNull();
    const rows = within(table as HTMLElement).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("REF-PARTIAL");
    expect(screen.getByRole("heading", { name: "Partial match" })).toBeVisible();
  });

  it("filters results and exposes a deterministic filtered-empty state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => response(overview())));
    render(<Dashboard token="token" user={analyst} />);
    await screen.findByText("USD 250.000000");

    fireEvent.change(screen.getByLabelText("Classification"), { target: { value: "exact_match" } });
    expect(screen.getAllByText("REF-EXACT")).not.toHaveLength(0);
    expect(screen.queryByText("REF-PARTIAL")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "not-present" } });
    expect(screen.getByText("No results match these filters.")).toBeVisible();
  });

  it("gives auditors evidence without reconciliation controls", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => response(overview())));
    render(<Dashboard token="token" user={auditor} />);

    expect(await screen.findByText("Auditor · read only")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Run reconciliation" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Reconciliation results" })).toBeVisible();
  });

  it("renders loading and empty states", async () => {
    let resolveRequest: ((value: unknown) => void) | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(
        () =>
          new Promise((resolve) => {
            resolveRequest = resolve;
          }),
      ),
    );
    const view = render(<Dashboard token="token" user={analyst} />);
    expect(screen.getByText("Loading reconciliation workspace…")).toBeVisible();
    resolveRequest?.({ ok: true, status: 200, json: () => Promise.resolve(overview(false)) });
    expect(await screen.findByText("No completed reconciliation run yet.")).toBeVisible();
    view.unmount();
  });

  it("distinguishes forbidden access from a recoverable server error", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => response({}, 403))
      .mockImplementationOnce(() => response({}, 500))
      .mockImplementationOnce(() => response(overview()));
    vi.stubGlobal("fetch", fetchMock);

    const first = render(<Dashboard token="token" user={auditor} />);
    expect(await screen.findByText("Dashboard access is not assigned.")).toBeVisible();
    first.unmount();
    render(<Dashboard token="token" user={analyst} />);
    expect(await screen.findByText("Dashboard unavailable.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("USD 250.000000")).toBeVisible();
  });

  it("validates the match window before starting reconciliation", async () => {
    const fetchMock = vi.fn().mockImplementation(() => response(overview()));
    vi.stubGlobal("fetch", fetchMock);
    render(<Dashboard token="token" user={analyst} />);
    await screen.findByText("USD 250.000000");

    fireEvent.change(screen.getByLabelText("Match window"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Run reconciliation" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Match window must be a whole number from 1 to 168.",
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  });

  it("queues reconciliation, displays durable progress, and refreshes completed results", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => "00000000-0000-0000-0000-000000000901" });
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => response(overview()))
      .mockImplementationOnce(() => response(reconciliationJob("running"), 202))
      .mockImplementationOnce(() => response(reconciliationJob("succeeded")))
      .mockImplementationOnce(() => response(overview()));
    vi.stubGlobal("fetch", fetchMock);

    render(<Dashboard token="token" user={analyst} />);
    await screen.findByText("USD 250.000000");

    fireEvent.click(screen.getByRole("button", { name: "Run reconciliation" }));
    expect(await screen.findByText("Loading facts.")).toBeVisible();
    expect(screen.getByText("33% · attempt 1 of 3")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));

    expect(await screen.findByText("Background reconciliation completed.")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(4);
    const reconciliationRequest = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(reconciliationRequest[1].method).toBe("POST");
    expect(new Headers(reconciliationRequest[1].headers).get("Idempotency-Key")).toBe(
      "dashboard-00000000-0000-0000-0000-000000000901",
    );
  });
});
