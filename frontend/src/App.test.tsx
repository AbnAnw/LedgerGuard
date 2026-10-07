import { cleanup, render, screen } from "@testing-library/react";
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
});
