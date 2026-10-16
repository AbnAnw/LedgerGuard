import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuditEvent, AuthUser } from "./api";
import { AuditTimeline } from "./AuditTimeline";

const auditor: AuthUser = {
  id: "00000000-0000-0000-0000-000000000001",
  email: "auditor@ledgerguard.invalid",
  display_name: "Synthetic Auditor",
  roles: ["auditor"],
  permissions: ["audit:read"],
};

const auditEvent: AuditEvent = {
  sequence_number: 42,
  id: "00000000-0000-0000-0000-000000000042",
  occurred_at: "2026-10-16T04:00:00Z",
  actor_user_id: auditor.id,
  actor_display_name: "Synthetic Auditor",
  actor_type: "user",
  action: "case.transitioned",
  target_type: "case",
  target_id: "00000000-0000-0000-0000-000000000010",
  result: "success",
  correlation_id: "00000000-0000-0000-0000-000000000099",
  request_id: null,
  job_id: null,
  before_state: { status: "escalated" },
  after_state: { status: "resolved" },
  metadata: { schema_version: "audit-v1" },
};

function response(value: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(value) });
}

describe("AuditTimeline", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows sequence-ordered evidence and reconstructs a case trail", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/timeline")) {
        return response({
          case_id: auditEvent.target_id,
          alert_ids: ["00000000-0000-0000-0000-000000000020"],
          transaction_ids: ["00000000-0000-0000-0000-000000000030"],
          events: [auditEvent],
        });
      }
      return response([auditEvent]);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AuditTimeline token="token" user={auditor} />);

    expect(await screen.findByText("case.transitioned")).toBeVisible();
    expect(screen.getByText("#42 · success")).toBeVisible();
    fireEvent.change(screen.getByPlaceholderText("Case UUID"), {
      target: { value: auditEvent.target_id },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reconstruct case" }));
    expect(await screen.findByText(/1 transaction.*1 alert/i)).toBeVisible();
  });
});
