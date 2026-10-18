import { expect, type Page, test } from "@playwright/test";

const password = process.env.E2E_DEMO_PASSWORD ?? "DemoOnly!ChangeMe123456";

async function signIn(page: Page, email: string, displayName: string) {
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("API online");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: `Welcome, ${displayName}.` })).toBeVisible();
}

function workspace(page: Page, name: string) {
  return page.locator(".workspace-card").filter({ hasText: name });
}

test("administrator can oversee every workspace", async ({ page }) => {
  await signIn(page, "admin@ledgerguard.invalid", "Synthetic Administrator");

  await expect(workspace(page, "Administration")).toContainText("Manage");
  await expect(workspace(page, "Operations")).toContainText("Manage");
  await expect(workspace(page, "Audit evidence")).toContainText("Read only");
  await expect(page.getByRole("heading", { name: "Reconciliation workspace" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Every alert carries its evidence." })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Reports and safe exports" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Reconstruct every material decision." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run reconciliation" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Evaluate synthetic account" })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to your assigned workspace." })).toBeVisible();
});

test("operations analyst can investigate but cannot administer or audit", async ({ page }) => {
  await signIn(page, "analyst@ledgerguard.invalid", "Synthetic Operations Analyst");

  await expect(workspace(page, "Operations")).toContainText("Manage");
  await expect(workspace(page, "Administration")).toHaveCount(0);
  await expect(workspace(page, "Audit evidence")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Reconciliation workspace" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Every alert carries its evidence." })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Decisions stay attached to evidence." })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Reports and safe exports" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run reconciliation" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Evaluate synthetic account" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Reconstruct every material decision." })).toHaveCount(0);
});

test("auditor has evidence access without write controls", async ({ page }) => {
  await signIn(page, "auditor@ledgerguard.invalid", "Synthetic Auditor");

  await expect(workspace(page, "Audit evidence")).toContainText("Read only");
  await expect(workspace(page, "Administration")).toHaveCount(0);
  await expect(workspace(page, "Operations")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Reconciliation workspace" })).toBeVisible();
  await expect(page.getByText("Auditor · read only")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Every alert carries its evidence." })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Decisions stay attached to evidence." })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Reports and safe exports" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Reconstruct every material decision." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run reconciliation" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Evaluate synthetic account" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Add comment" })).toHaveCount(0);
});
