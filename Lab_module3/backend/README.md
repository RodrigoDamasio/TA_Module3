# Migration Workflow Agent — Backend

FastAPI service that migrates small code projects between frameworks. A pipeline of four LLM agents (Google Gemini) does the work: **Analyzer → Planner → Executor → Verifier**. An orchestrator runs the pipeline. It supports human approval of the plan, parallel execution of independent steps, retries with feedback, and rollback. Design: [../PLAN.md](../PLAN.md) · [../BACKEND_PLAN.md](../BACKEND_PLAN.md).

Supported migrations (all targets are Python):

| Pair | Source | Target |
|---|---|---|
| `flask-fastapi` | Flask (Python) | FastAPI |
| `express-fastapi` | Express (JavaScript) | FastAPI |
| `django-fastapi` | Django function views + `urls.py` | FastAPI |
| `python2-python3` | Python 2 | Python 3.12 |

## Run locally

```bash
cd TA_Module3/Lab_module3/backend
source ../../../.venv/bin/activate          # Python 3.12 environment of the course
pip install -r requirements-dev.txt

# Real migrations (reads GOOGLE_API_KEY from the environment)
set -a && source ../../../.env && set +a
uvicorn app.main:app --reload               # http://localhost:8000/docs

# No key / no quota: deterministic demo answers for UI work
LLM_MODE=fake uvicorn app.main:app --reload
```

## API

| Method · Path | Purpose | LLM calls |
|---|---|---|
| `POST /migrate` | `{files: [{path, content}], source_framework, target_framework, require_approval?}` → `202` + `Location`. With `?wait=true` (needs `require_approval: false`) → `200` with the finished job | ~5–7 per job |
| `GET /migrations/{id}` | Job view: phase, analysis, plan, migrated files, verification, errors, `meta`. `?include_history=true` adds every file version | 0 |
| `GET /migrations/{id}/events` | Server-Sent Events (`phase`, `analysis`, `plan`, `step`, `verification`, `error`, `done`). Resumes from `Last-Event-ID` and ends after `done` | 0 |
| `POST /migrations/{id}/approve` | Approve the plan, which runs the Executor steps | — |
| `POST /migrations/{id}/reject` | `{feedback?}`: with feedback, one replan; without it, the job is cancelled | 1 (replan) |
| `POST /migrations/{id}/rollback` | Hide every generated file version (from `completed` / `failed`) | 0 |
| `GET /frameworks` | Supported pairs | 0 |
| `GET /samples` · `GET /samples/{id}` | Demo projects + a stored real result | 0 |
| `GET /health` · `GET /problems/{slug}` | Status · RFC 9457 problem type docs | 0 |

Errors are RFC 9457 `application/problem+json`:
- `400 malformed-request`, `404 job-not-found`, `409 invalid-transition`, `413 input-too-large`
- `422 validation-error` (with JSON pointers) / `unsupported-migration`
- `429 rate-limited`, `503 llm-quota-exhausted` / `llm-unavailable` (the last three with `Retry-After`)
- `504 wait-timeout`, `500 internal-error`

A failure inside a job is not an HTTP error: the job ends in `phase: "failed"` with `errors[]` and `error` + `done` events. Examples are a bad plan, the per-job budget being reached, or the daily quota running out mid-job.

## How it works

```
app/
├── domain/          MigrationJob (state machine + file versions), Plan DAG, reports, errors, ports
├── frameworks/      pair registry, route/import extraction, deterministic checks (never executes code)
├── application/     orchestrator, DAG scheduler, the 4 agents, budget, context, prompts, MigrationService
├── tools/           read_file, find_text, list_routes, list_imports, get_code_metrics (lizard)
├── prompts/         versioned prompt library: base rules, one persona per agent, guides per pair
├── infrastructure/  Gemini adapter, quota wrappers, response cache, SQLite stores, runner, samples
└── api/             routes, SSE, RFC 9457 problems, rate limiter, wiring
```

1. **Analysis.** Code extracts the facts first: routes, imports, and metrics. The Analyzer then summarizes components, dependencies, patterns and risks, and may use up to 2 rounds of tools.
2. **Planning.** The Planner returns a DAG of 1–8 steps. Each step lists its source files, target files, dependencies and complexity. The plan is validated locally: no cycles, no unknown dependencies, and parallel steps never write the same file. An invalid plan gets one repair call. Recent *episodes* (lessons from past jobs of the same pair) are included in the prompt.
3. **Approval** (when `require_approval`). The job pauses in `awaiting_approval`. Approve runs the plan. Reject with feedback triggers one replan. With no answer for 30 minutes, the job is `cancelled`.
4. **Execution.** Ready steps run in parallel (`PARALLEL_STEPS=2`), while Gemini calls stay serialized. Each Executor call sees the step's source files **and the files that earlier steps have already migrated**, so cross-file APIs stay consistent. Each output is checked locally:
   - parse and compile
   - Ruff `F` rules
   - imports between migrated files resolve

   A step that fails the checks is retried once with the errors. If it fails again, its versions are hidden and its dependent steps are skipped.
5. **Verification.** Deterministic checks run first: `compiles`, `lint`, `imports_resolve`, `framework_migrated` and `routes_preserved`. If a check fails, the step responsible for that file is re-executed once. When every check passes, the Verifier LLM reviews behavior and gives a confidence score from 1 to 10. `success` requires every check to pass and confidence ≥ 7.
6. **Rollback.** File versions are append-only. Rollback hides them and marks the steps `rolled_back`, so the history stays in the job.

Every transition is saved together with its events in one SQLite transaction. The SSE stream therefore never disagrees with the stored state. A job interrupted by a restart is marked `failed` at startup.

**Security.** Generated code is **never executed**. The only checks are `ast.parse`, `compile()` to bytecode, and Ruff running as a subprocess on a temporary copy with a fixed argv. Paths are validated both on input and on every Executor output. Every prompt carries a "code is data" rule, and the `django_articles` sample contains a planted prompt injection that the agents ignore. Logs hold ids, sizes and counters only; they never contain code or the key.

**Quota protection.**
- Every identical LLM request is served from a response cache (0 calls).
- A per-job budget caps each job at 16 calls (the loop guard).
- Other limits: pacing between calls, retries for per-minute limits and provider overloads, and one Gemini call at a time.
- After the daily limit is hit, a circuit breaker refuses new jobs with `503` until the reset.
- Per client: 2 new jobs per minute and 10 per day. Reads, samples and SSE are free.

## Quality checks

```bash
pytest -q                                   # 231 tests, 0 real LLM calls (fake LLM + recorded responses)
pytest -q --cov=app --cov-report=term-missing   # 95 %
ruff check . && ruff format --check .

# Evaluation against the real model: per-call cache, resumable, capped by --max-calls
python -m eval.run --set full --fake        # harness self-test, 0 calls
python -m eval.run --set smoke              # flask_todo (~6 calls)
python -m eval.run --set full --max-calls 40
python -m eval.run --set full --max-calls 0 --publish   # re-score from cache, copy to samples/results/
```

## Evaluation results

`gemini-3.5-flash-lite`, prompt v2. Full report: [eval/report_full.md](eval/report_full.md). Scoring is deterministic, with no LLM judge.

| Metric | Result | Target |
|---|---|---|
| Jobs completed | 4/4 | 4/4 |
| Migrated files parse + compile | 4/4 | 100 % |
| Routes preserved (web pairs) | 12/12 routes (3/3 samples) | 100 % |
| Source-framework imports / Py2 idioms left | 0 | 0 |
| Undefined names (F821) | 0 | 0 |
| LLM calls per job | 5.8 | ≤ 12 |

The whole evaluation, including the first-run fix below, cost **26 real calls**. Re-runs cost 0.

Findings:
- **Cross-file bug found by the first real run (prompt v1).** Step 1 rewrote `models.py` as Pydantic models. Step 2 then wrote `main.py` against the *source* API: `Todo(title=…)` and `t.to_dict()`, both of which no longer existed. The static checks passed, and the Verifier gave it confidence 10. Three fixes went in:
  - the Executor now sees the files its dependency steps migrated
  - a new deterministic `imports_resolve` check, also run in the step retry loop
  - a cross-file item in the Verifier checklist

  Prompt v2 produces a consistent result ([v1](eval/results/gemini-3.5-flash-lite/prompt-v1/flask_todo.json) vs [v2](eval/results/gemini-3.5-flash-lite/prompt-v2/flask_todo.json)).
- **Prompt injection.** The Analyzer flagged the planted comment in `django_articles` as an injection attempt. The endpoint it asked to drop was migrated.
- **Verifier leniency.** Confidence is 10 on every sample. The Express migration added a `"secret"` fallback for `JWT_SECRET`, which weakens security, and the Verifier did not flag it. The deterministic checks are the real gate, which is why `eval` re-scores them independently.

## Configuration

See `app/config.py`. Main variables:

- **Model and API key:** `GOOGLE_API_KEY`; `GEMINI_MODEL` (default `gemini-3.5-flash-lite`); `LLM_MODE` (`gemini` or `fake`); `LLM_MIN_INTERVAL_S`.
- **Input limits:** `MAX_FILES` / `MAX_TOTAL_CHARS` (5 / 30,000).
- **Job limits:** `MAX_PLAN_STEPS` (8); `JOB_LLM_BUDGET` (16); `MAX_TOOL_ROUNDS` (2); `PARALLEL_STEPS` (2); `APPROVAL_TIMEOUT_MIN` (30); `MAX_QUEUED_JOBS` (5).
- **Rate limits:** `RATE_LIMIT_JOBS_PER_MINUTE` / `_PER_DAY` (2 / 10).
- **Other:** `SYNC_WAIT_TIMEOUT_S` (180); `DATABASE_PATH`; `BASE_URL`; `FRONTEND_ORIGIN`.

Run the service as a **single replica**: the job queue is in-process and the store is SQLite.
