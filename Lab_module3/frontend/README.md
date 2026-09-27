# Migration Workflow Agent — Frontend

**Live:** https://taller-migration-agent.vercel.app · API: https://backend-production-4d1c3.up.railway.app · deployment: [DEPLOY.md](DEPLOY.md) · design: [../FRONTEND_PLAN.md](../FRONTEND_PLAN.md)

Next.js 16 + TypeScript + Tailwind. How to use it:
1. Add up to 5 source files: type, paste or upload them.
2. Pick the migration (Flask / Express / Django → FastAPI, or Python 2 → 3) and press **Migrate**.
3. Follow the job live: a phase stepper and an activity log fed by Server-Sent Events.
4. Review the plan: steps grouped in waves that can run in parallel, each with a live status.
5. Approve or reject the plan, with feedback for one replan.
6. Inspect the migrated files in a **diff view**: side by side or unified, compared with the source file or an earlier version.
7. Read the verification checks, then **roll back** or download the result JSON.

**Try a sample** replays one of four stored real migrations, costing 0 LLM calls. `/?job=mig_…` resumes a job after a reload.

## Run locally (Node 24)

```bash
cd TA_Module3/Lab_module3/frontend
nvm use 24 && npm install
npm run build && npm run start   # http://localhost:3000 — API http://localhost:8000
# (`npm run dev` works too where the OS file-watch limit allows it)

# Backend without quota, in another terminal:
cd ../backend && LLM_MODE=fake ../../../.venv/bin/uvicorn app.main:app --port 8000
```

## Quality checks

```bash
npm run typecheck && npm run lint
npm test                     # 53 unit + component tests (Vitest); API and EventSource faked
npm run test:coverage        # thresholds 80 % (currently ~95 % lines)
npm run test:e2e             # 11 Playwright tests: real backend with LLM_MODE=fake + production build (0 quota)
BASE_URL=https://taller-migration-agent.vercel.app npm run test:e2e   # production subset, incl. one real migration
```

- **Validation.** Every API response and every SSE event is checked with **Zod**. The schemas in `lib/schemas.ts` mirror the backend's models, and the tests parse the backend's real stored results with them.
- **Errors.** RFC 9457 problems are mapped in `lib/api.ts`. `Retry-After` drives the countdowns.
- **State.** The JobView is the source of truth. Events update the screen at once and trigger a debounced refetch; if the stream is lost, the page polls instead (`hooks/useJob.ts`).
- **E2E browser.** Tests run on the installed Google Chrome (`channel: "chrome"`), because Playwright's Chromium does not support Ubuntu 20.04.

The tests found four real bugs, all fixed:
- **Duplicate field ids after hydration:** ids came from a module counter, which the server and the browser don't share. Now uses `useId`.
- **A "Removefile 2" accessible name:** the button now has an explicit `aria-label`.
- **A countdown measured from page load** instead of from the error.
- **Scrollable regions (diff, code, activity) not reachable by keyboard** (axe).
