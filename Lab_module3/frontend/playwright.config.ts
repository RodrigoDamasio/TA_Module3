import { defineConfig, devices } from "@playwright/test";

// BASE_URL=https://<vercel-domain> runs the production subset (E8) instead of local servers.
const deployedUrl = process.env.BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000, // a real migration in production takes ~1-2 min with pacing; local fake: < 2 s
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  workers: 1, // one backend runs one job at a time (in-process queue)
  use: {
    baseURL: deployedUrl ?? "http://localhost:3000",
    // Playwright's bundled Chromium is not supported on Ubuntu 20.04: use the installed Chrome.
    channel: "chrome",
    trace: "retain-on-failure",
  },
  projects: [{ name: "desktop", use: { ...devices["Desktop Chrome"], channel: "chrome" } }],
  webServer: deployedUrl
    ? undefined
    : [
        {
          // Real backend with a fake LLM: full integration (SSE, approval, rollback), zero quota.
          command:
            "rm -f e2e.db* && ../../../.venv/bin/uvicorn app.main:app --port 8000",
          cwd: "../backend",
          url: "http://localhost:8000/health",
          env: {
            LLM_MODE: "fake",
            DATABASE_PATH: "e2e.db",
            FRONTEND_ORIGIN: "http://localhost:3000",
            RATE_LIMIT_JOBS_PER_MINUTE: "1000",
            RATE_LIMIT_JOBS_PER_DAY: "10000",
          },
          reuseExistingServer: false,
        },
        {
          // Production build: no file watchers (the dev server hits the OS watch limit here).
          command: "npm run build && npm run start",
          url: "http://localhost:3000",
          env: { NEXT_PUBLIC_API_URL: "http://localhost:8000" },
          timeout: 180_000,
          reuseExistingServer: false,
        },
      ],
});
