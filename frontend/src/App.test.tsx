import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

describe("App", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows the platform foundation and live API version", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            status: "alive",
            service: "LedgerGuard",
            version: "0.1.0",
            checked_at: "2026-10-07T00:00:00+00:00",
          }),
      }),
    );

    render(<App />);

    expect(screen.getByRole("heading", { name: /every financial exception/i })).toBeVisible();
    expect(await screen.findByText("API online · v0.1.0")).toBeVisible();
    expect(screen.getByRole("heading", { name: "PostgreSQL" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Redis + Celery" })).toBeVisible();
  });

  it("reports an unavailable API without hiding the application", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    render(<App />);

    expect(await screen.findByText("API unavailable")).toBeVisible();
    expect(screen.getByText(/synthetic demonstration data only/i)).toBeVisible();
  });

  it("shows only the read-only audit workspace to an auditor", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const requestUrl =
          typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        if (requestUrl.endsWith("/health/live")) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                status: "alive",
                service: "LedgerGuard",
                version: "0.1.0",
                checked_at: "2026-10-09T00:00:00+00:00",
              }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              access_token: "opaque-token",
              token_type: "bearer",
              expires_at: "2026-10-09T00:30:00+00:00",
              user: {
                id: "018fca3a-f135-7f42-b159-bb08d31f19f1",
                email: "auditor@ledgerguard.invalid",
                display_name: "Synthetic Auditor",
                roles: ["auditor"],
                permissions: ["audit:read"],
              },
            }),
        });
      }),
    );

    render(<App />);
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "auditor@ledgerguard.invalid" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "DemoOnly!ChangeMe123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Welcome, Synthetic Auditor." })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Audit evidence" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Administration" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Operations" })).not.toBeInTheDocument();
    expect(screen.getByText("Read only")).toBeVisible();
  });

  it("shows a generic message for failed authentication", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const requestUrl =
          typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        return Promise.resolve(
          requestUrl.endsWith("/health/live")
            ? {
                ok: true,
                json: () =>
                  Promise.resolve({
                    status: "alive",
                    service: "LedgerGuard",
                    version: "0.1.0",
                    checked_at: "2026-10-09T00:00:00+00:00",
                  }),
              }
            : { ok: false, status: 401 },
        );
      }),
    );

    render(<App />);
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "unknown@ledgerguard.invalid" },
    });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The email or password is incorrect.",
    );
  });
});
