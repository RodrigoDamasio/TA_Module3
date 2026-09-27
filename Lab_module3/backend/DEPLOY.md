# Backend Deployment — Railway

The exact steps used to deploy the Migration Workflow Agent API, in the order they were run.

**Result:** https://backend-production-4d1c3.up.railway.app ([API docs](https://backend-production-4d1c3.up.railway.app/docs))

| Item | Value |
|---|---|
| Railway project | `taller-migration-agent` |
| Service / environment | `backend` / `production` |
| Volume | `backend-volume` mounted at `/data` (jobs, events, episodes, LLM response cache) |
| Builder | Railpack, Python 3.12, pip |
| Model | `gemini-3.5-flash-lite` (Google AI Studio free tier) |
| Replicas | **1**: the job queue is in-process and the store is SQLite. Do not scale horizontally |

## Prerequisites

- Railway CLI logged in (`railway login`, done in Module 1).
- `GOOGLE_API_KEY` in the course's `.env` (`Taller_Academy/.env`, git-ignored).
- All gates green:
  - `pytest -q` (231 tests, 0 LLM calls)
  - `ruff check .`
  - the full evaluation meets its targets ([eval/report_full.md](eval/report_full.md))
- Work committed and pushed (rollback point).
- **Free plan: at most 2 projects.** The first `railway init` failed with *"Free plan resource provision limit exceeded"*. The Module 1 project (`taller-url-shortener`) was deleted to make room: `railway delete --project <id> --yes`. The Module 1 code remains on GitHub.

## Files that configure the deploy

| File | Purpose |
|---|---|
| `requirements.txt` + `.python-version` | Python 3.12 pip project. Ruff is a runtime dependency: it is the verifier's lint check |
| `railpack.json` | Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'`. The proxy headers give the real client IP to the rate limiter. One uvicorn worker (the default) |
| `railway.json` | Health check `GET /health`. Railway deprecates this format after 2026-12-01; migrate with `railway config migrate` |
| `.railwayignore` | Keeps `tests/`, `eval/`, `*.db` and caches out of the image. `samples/` (incl. `samples/results/`) **is** deployed, because `/samples` serves it |

## Steps

```bash
cd TA_Module3/Lab_module3/backend

# 1. Project, service (with the DB path), volume, public domain
railway init --name taller-migration-agent --workspace <workspace-id>
railway add --service backend --variables "DATABASE_PATH=/data/migrations.db"
railway service link backend
railway volume add --mount-path /data
railway domain --json            # → https://backend-production-4d1c3.up.railway.app

# 2. Non-secret settings
railway variables --set "BASE_URL=https://backend-production-4d1c3.up.railway.app" \
  --set "GEMINI_MODEL=gemini-3.5-flash-lite" --set "LLM_MIN_INTERVAL_S=6" \
  --set "RATE_LIMIT_JOBS_PER_MINUTE=2" --set "RATE_LIMIT_JOBS_PER_DAY=10" --skip-deploys

# 3. API key (run by the owner): piped from .env, never on the command line,
#    in history, or in output. Then compare fingerprints, not values.
grep '^GOOGLE_API_KEY=' ../../../.env | cut -d= -f2- | tr -d '\n' \
  | railway variable set GOOGLE_API_KEY --stdin --skip-deploys > /dev/null
a=$(railway variables --kv | grep '^GOOGLE_API_KEY=' | cut -d= -f2- | tr -d '\n' | sha256sum)
b=$(grep '^GOOGLE_API_KEY=' ../../../.env | cut -d= -f2- | tr -d '\n' | sha256sum)
[ "$a" = "$b" ] && echo "key matches"
railway variables --kv | cut -d= -f1          # names only

# 4. Deploy
railway up --ci
```

**After the frontend is on Vercel.** This sets CORS and redeploys automatically:

```bash
railway variables --set "FRONTEND_ORIGIN=http://localhost:3000,https://<vercel-domain>"
```

## Final environment variables

| Variable | Value |
|---|---|
| `GOOGLE_API_KEY` | *(secret, set via stdin)* |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` |
| `DATABASE_PATH` | `/data/migrations.db` |
| `BASE_URL` | `https://backend-production-4d1c3.up.railway.app` |
| `LLM_MIN_INTERVAL_S` | `6` |
| `RATE_LIMIT_JOBS_PER_MINUTE` / `_PER_DAY` | `2` / `10` new jobs per client IP |
| `FRONTEND_ORIGIN` | `http://localhost:3000,https://taller-migration-agent.vercel.app` |

## Post-deploy verification (results)

| # | Check | Result | LLM calls |
|---|---|---|---|
| V1 | `GET /health`, `GET /frameworks` | ✅ `{"status":"ok","model":"gemini-3.5-flash-lite","llm_mode":"gemini"}`; 4 pairs | 0 |
| V2 | `GET /samples`, `GET /samples/flask_todo` | ✅ 4 samples, all with a stored result (`completed`, `success`, `main.py` + `models.py`) | 0 |
| V3 | Missing fields / `cobol → fastapi` / 30,001 chars / unknown job | ✅ `422 validation-error` (pointers) / `422 unsupported-migration` / `413 input-too-large` / `404 job-not-found`, all `application/problem+json` | 0 |
| V4 | SSE through Railway's proxy | ✅ 14 events streamed live, not buffered: `phase`, `analysis`, `plan`, 4 × `step`, `verification`, `done`. 7 `: ping` keep-alives during the approval wait. The stream closed after `done` | 0 |
| V5 | Real migration `flask_todo`, approval on | ✅ Paused at `awaiting_approval` with a 2-step plan (84 s) → approve → `completed` in 49 s. `success`, confidence 10, every check passed (`compiles` ×2, `lint`, `imports_resolve`, `framework_migrated`, `routes_preserved`). 13,403 / 2,353 tokens | 6 |
| V6 | Rollback of that job | ✅ `rolled_back`, no current files, both versions kept as `hidden` | 0 |
| V7 | CORS from `http://localhost:3000` | ✅ Preflight allows `Last-Event-ID`. A `404` problem and the SSE stream carry `access-control-allow-origin`. `Retry-After` and `Location` are exposed | 0 |
| V8 | `railway logs` | ✅ Job logged as `submitted pair=flask-fastapi files=2 chars=2020 approval=True`. Searches for `GOOGLE_API_KEY`, `AIza`, and code identifiers (`TodoStore`, `jsonify`, `def create_todo`) found 0 matches | 0 |

## Problems hit

- **Railway free plan project limit.** Solved by deleting the Module 1 project, as described in the prerequisites.
- **Setting the key from the assistant's session was blocked** by Claude Code's permission check, so the owner ran step 3 in their own terminal. The design already covered this: the key never has to pass through the assistant.

## Quota notes

- The deployed app shares the key's free-tier quota with every caller of the public URL.
- A migration costs about 6 calls. The protections:
  - a per-IP limit on *new jobs*; reads, samples and SSE are free
  - a per-job budget of 16 calls
  - an LLM response cache on the volume, so a repeated identical request costs 0
  - one Gemini call at a time
  - a circuit breaker after the daily limit, which refuses new jobs with `503`
- Billing is **not** enabled on the Google project. The worst case is therefore "limit reached" until midnight Pacific, never a charge.

## Redeploy / rollback

```bash
pytest -q && ruff check . && git commit ...   # gates + rollback point
railway up --ci
```

Rollback: in the Railway dashboard, open `backend` → Deployments → the previous deployment → Redeploy. The volume is not affected. Jobs that were running during a redeploy are marked `failed ("interrupted by a server restart")` at startup.
