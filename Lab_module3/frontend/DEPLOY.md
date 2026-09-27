# Frontend Deployment — Vercel

The steps run to deploy the Migration Workflow Agent UI. The pattern is the same as in Modules 1–2.

**Result:** https://taller-migration-agent.vercel.app

| Item | Value |
|---|---|
| Vercel scope / project | `rodrigodamasiojulio-9268` / `taller-migration-agent` (Hobby) |
| Backend | https://backend-production-4d1c3.up.railway.app ([../backend/DEPLOY.md](../backend/DEPLOY.md)) |
| Secrets | None. The Gemini key stays on Railway |

## Steps

```bash
cd TA_Module3/Lab_module3/frontend
# The Vercel CLI is installed under Node 18's global bin (nvm); Node 24 runs the build.

# 1. Create and link the project. This also writes .env.local with a
#    VERCEL_OIDC_TOKEN; that file is git-ignored (.env*).
vercel link --yes --project taller-migration-agent

# 2. Set the backend URL before building (NEXT_PUBLIC_* is inlined at build time)
printf 'https://backend-production-4d1c3.up.railway.app' | vercel env add NEXT_PUBLIC_API_URL production

# 3. Deploy
vercel --prod --yes

# 4. Allow the Vercel domain on the backend (CORS; Railway redeploys the API) — from ../backend
railway variables --set "FRONTEND_ORIGIN=http://localhost:3000,https://taller-migration-agent.vercel.app"
```

## Verification

| Check | Result | LLM calls |
|---|---|---|
| Page public | ✅ HTTP 200 | 0 |
| Bundle contains the Railway URL | ✅ in `/_next/static/immutable/chunks/…` (Next 16 path) | 0 |
| CORS from the Vercel origin | ✅ Preflight, a `404` problem, and the **SSE stream** (`text/event-stream`) all carry `access-control-allow-origin: https://taller-migration-agent.vercel.app` | 0 |
| E2E against production (E4 ×4, E6, E7, E8) | ✅ 7/7 in 1.6 min | 4 |

**E8:** one real `flask_todo` migration with approval, through the UI: replay → *Run it for real* → *Awaiting approval* → approve → *Migration verified*. The job took 39 s on the server and made **4 real calls + 2 cached**. The plan predicted 0, because the post-deploy check V5 had already run the same project. The analysis was indeed a cache hit. The planner's prompt, however, now contained the *episode* that V5 recorded (episodic memory), so the plan, the steps and the verification were new requests. The memory changing the prompt is working as designed; it just means a repeated project is not free once episodes exist.

## Redeploy

```bash
npm run typecheck && npm run lint && npm test && npm run build
vercel --prod --yes
BASE_URL=https://taller-migration-agent.vercel.app npm run test:e2e   # spends ~0–6 calls (E8)
```

Changing the backend URL requires a rebuild (`vercel env rm/add`, then `vercel --prod`). A new frontend domain must be added to `FRONTEND_ORIGIN` on Railway.
