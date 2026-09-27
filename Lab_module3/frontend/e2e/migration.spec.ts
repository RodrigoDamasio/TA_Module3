/** E2E (FRONTEND_PLAN §8). Locally: real backend with LLM_MODE=fake — 0 LLM calls.
 * With BASE_URL set, only the production subset runs (E8). */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const deployed = !!process.env.BASE_URL;
const SAMPLES = join(__dirname, "..", "..", "backend", "samples");
const read = (sample: string, path: string) => readFileSync(join(SAMPLES, sample, path), "utf8");

async function fillProject(page: Page, files: [string, string][]) {
  for (let i = 0; i < files.length; i++) {
    if (i > 0) await page.getByRole("button", { name: "Add file" }).click();
    await page.getByLabel(`File ${i + 1} path`).fill(files[i][0]);
    await page.getByLabel(`File ${i + 1} content`).fill(files[i][1]);
  }
}

const FLASK: [string, string][] = [
  ["app.py", read("flask_todo", "app.py")],
  ["models.py", read("flask_todo", "models.py")],
];

async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((v) =>
    ["serious", "critical"].includes(v.impact ?? ""),
  );
  expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(", ")}`)).toEqual([]);
}

async function replaySample(page: Page, id: string) {
  await page.goto("/");
  await page.getByLabel("Try a sample").selectOption(id);
  await expect(page.getByText("Stored result — replay (0 LLM calls)")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run it for real" })).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByText(/Migration verified/)).toBeVisible();
}

test.describe("local (fake-LLM backend)", () => {
  test.skip(deployed, "local-only: needs the fake-LLM backend");

  test("E1: migrate without approval — live stepper, plan, diff", async ({ page }) => {
    await page.goto("/");
    await fillProject(page, FLASK);
    await page.getByRole("checkbox", { name: /Require my approval/ }).uncheck();
    await page.getByRole("button", { name: "Migrate" }).click();
    await expect(page).toHaveURL(/\?job=mig_[0-9a-f]+/);
    await expect(page.getByText(/Migration verified/)).toBeVisible();
    await expect(page.getByRole("list", { name: "Activity" })).toContainText(
      "Migration completed.",
    );
    await expect(page.getByText("Completed", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("tab", { name: /main\.py/ })).toBeVisible();
    await expect(page.getByLabel("Compare with")).toBeVisible();
    await expect(
      page.locator("td", { hasText: "from fastapi import FastAPI" }).first(),
    ).toBeVisible();
  });

  test("E2: approval — reject with feedback, replan, approve", async ({ page }) => {
    await page.goto("/");
    await fillProject(page, FLASK);
    await page.getByRole("button", { name: "Migrate" }).click();
    await expect(page.getByRole("heading", { name: "Your approval is needed" })).toBeVisible();
    await page.getByLabel(/Feedback for a new plan/).fill("Put the models in their own step.");
    await page.getByRole("button", { name: "Reject and replan" }).click();
    await expect(page.getByText("Plan revision 2")).toBeVisible();
    await expect(page.getByText(/No replans left/)).toBeVisible();
    await page.getByRole("button", { name: "Approve plan" }).click();
    await expect(page.getByText(/Migration verified/)).toBeVisible();
  });

  test("E3: rollback, then reload resumes the same job", async ({ page }) => {
    await page.goto("/");
    await fillProject(page, FLASK);
    await page.getByRole("checkbox", { name: /Require my approval/ }).uncheck();
    await page.getByRole("button", { name: "Migrate" }).click();
    await expect(page.getByText(/Migration verified/)).toBeVisible();
    await page.getByRole("button", { name: "Roll back" }).click();
    await page.getByRole("button", { name: "Confirm rollback" }).click();
    await expect(page.getByText(/every generated file is hidden/)).toBeVisible();
    const url = page.url();
    await page.reload();
    expect(page.url()).toBe(url);
    await expect(page.getByText(/Migration rolled back/)).toBeVisible();
    await expect(page.getByText(/Version history \(1 hidden\)/)).toBeVisible();
  });

  test("E5: client-side checks, network failure, 429 countdown", async ({ page }) => {
    await page.goto("/");
    await fillProject(page, [["app.js", "const x = 1;"]]);
    await expect(page.getByRole("main").getByRole("alert")).toContainText("accepts .py");
    await expect(page.getByRole("button", { name: "Migrate" })).toBeDisabled();

    await page.getByLabel("File 1 path").fill("app.py");
    await page.route("**/migrate", (route) => route.abort());
    await page.getByRole("button", { name: "Migrate" }).click();
    await expect(page.getByRole("main").getByRole("alert")).toContainText(
      "Can't reach the migration service",
    );

    await page.unroute("**/migrate");
    await page.route("**/migrate", (route) =>
      route.fulfill({
        status: 429,
        headers: {
          "Content-Type": "application/problem+json",
          "Retry-After": "30",
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Expose-Headers": "Retry-After",
        },
        body: JSON.stringify({ type: "x/problems/rate-limited", status: 429, title: "t" }),
      }),
    );
    await page.getByRole("button", { name: "Migrate" }).click();
    await expect(page.getByText(/You can try again in (29|30) s/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Migrate" })).toBeDisabled();
  });
});

test.describe("everywhere (0 LLM calls)", () => {
  for (const id of ["flask_todo", "express_users", "django_articles", "py2_report"]) {
    test(`E4: sample ${id} replays its stored real result`, async ({ page }) => {
      await replaySample(page, id);
      await expect(page.getByRole("tab", { name: /\.py/ }).first()).toBeVisible();
    });
  }

  test("E6: mobile 375×667 — no horizontal scroll, controls reachable", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/");
    await expectNoHorizontalScroll(page);
    await replaySample(page, "express_users");
    await expectNoHorizontalScroll(page);
    await page.getByRole("tab", { name: "Diff" }).click();
    await expectNoHorizontalScroll(page);
    await page.getByRole("button", { name: "Run it for real" }).scrollIntoViewIfNeeded();
    await expect(page.getByRole("button", { name: "Download result JSON" })).toBeVisible();
  });

  test("E7: accessibility — input and completed states", async ({ page }) => {
    await page.goto("/");
    await expectAccessible(page);
    await replaySample(page, "flask_todo");
    await expectAccessible(page);
  });
});

test.describe("local accessibility of the approval state", () => {
  test.skip(deployed, "a real approval would spend quota");

  test("E7b: accessibility — awaiting approval", async ({ page }) => {
    await page.goto("/");
    await fillProject(page, FLASK);
    await page.getByRole("button", { name: "Migrate" }).click();
    await expect(page.getByRole("heading", { name: "Your approval is needed" })).toBeVisible();
    await expectAccessible(page);
  });
});

test.describe("production", () => {
  test.skip(!deployed, "production only (BASE_URL)");
  test.setTimeout(300_000);

  test("E8: one real flask_todo migration with approval", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Try a sample").selectOption("flask_todo");
    await page.getByRole("button", { name: "Run it for real" }).click({ timeout: 20_000 });
    await expect(page.getByRole("heading", { name: "Your approval is needed" })).toBeVisible({
      timeout: 180_000,
    });
    await page.getByRole("button", { name: "Approve plan" }).click();
    await expect(page.getByText(/Migration verified/)).toBeVisible({ timeout: 180_000 });
  });
});
