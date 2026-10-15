import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, InvestigationCase } from "./api";
import { CaseWorkspace } from "./CaseWorkspace";

const auditor: AuthUser = {
  id: "00000000-0000-0000-0000-000000000001",
  email: "auditor@ledgerguard.invalid",
  display_name: "Synthetic Auditor",
  roles: ["auditor"],
  permissions: ["alerts:read", "cases:read"],
};

const analyst: AuthUser = {
  ...auditor,
  id: "00000000-0000-0000-0000-000000000002",
  email: "analyst@ledgerguard.invalid",
  roles: ["operations_analyst"],
  permissions: ["alerts:read", "cases:read", "cases:write"],
};

const investigation: InvestigationCase = {
  id: "00000000-0000-0000-0000-000000000010",
  case_number: 10,
  title: "Synthetic velocity review",
  description: "Only synthetic data is used.",
  status: "in_review",
  priority: "high",
  owner_user_id: null,
  owner_display_name: null,
  alert_count: 1,
  created_at: "2026-10-16T01:00:00Z",
  updated_at: "2026-10-16T01:00:00Z",
  version: 3,
  resolution_code: null,
  resolution_summary: null,
  resolved_at: null,
  alerts: [{
    id: "00000000-0000-0000-0000-000000000020",
    rule_code: "velocity_10m",
    rule_version_number: 1,
    source_record_id: "SYNTHETIC-001",
    severity: "high",
    score: "80.0000",
    status: "in_review",
    reason_code: "VELOCITY_THRESHOLD_MET",
    created_at: "2026-10-16T00:00:00Z",
  }],
  comments: [],
  history: [{
    id: "00000000-0000-0000-0000-000000000030",
    from_status: "open",
    to_status: "in_review",
    reason: "Review started",
    changed_by_user_id: analyst.id,
    changed_by_display_name: "Synthetic Analyst",
    correlation_id: "00000000-0000-0000-0000-000000000040",
    changed_at: "2026-10-16T01:00:00Z",
  }],
};

function response(value: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(value) });
}

describe("CaseWorkspace", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows an empty read-only queue to an auditor", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => response([])));
    render(<CaseWorkspace token="token" user={auditor} />);

    expect(await screen.findByText("No cases match")).toBeVisible();
    expect(screen.getByText("Read only")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Assign to me" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Add investigation note")).not.toBeInTheDocument();
  });

  it("exposes assignment, comments, and valid next transitions to an analyst", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        if (url.includes("/fraud/")) return response([]);
        if (url.endsWith(investigation.id)) return response(investigation);
        return response([investigation]);
      }),
    );
    render(<CaseWorkspace token="token" user={analyst} />);

    expect(await screen.findByRole("heading", { name: "Synthetic velocity review" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Assign to me" })).toBeVisible();
    expect(screen.getByRole("button", { name: "escalated" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Resolve confirmed" })).toBeVisible();
    expect(screen.getByLabelText("Add investigation note")).toBeVisible();
    expect(screen.queryByRole("button", { name: "reopened" })).not.toBeInTheDocument();
  });
});
