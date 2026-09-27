"""Evaluation harness: runs each sample through the REAL multi-agent workflow (auto-approve)
and scores the output deterministically — no LLM judge.

Quota-safe by design:
- every LLM answer is stored in eval/llm_cache.db, so re-runs and resumed runs cost 0 calls
  for everything already answered (prompts are deterministic: fresh job DB, no episodes);
- --max-calls caps REAL requests (cache hits are free); the job in flight stops cleanly;
- the daily quota stops the run at once (resume tomorrow, nothing is lost).

    python -m eval.run --set smoke                    # flask_todo only (~10 calls)
    python -m eval.run --set full --max-calls 60      # the 4 samples (~45 calls)
    python -m eval.run --set full --publish           # copy results to samples/results/
    python -m eval.run --set full --fake              # harness self-test, 0 calls
"""

import argparse
import dataclasses
import json
import shutil
import sys
import tempfile
from pathlib import Path

from app.api.schemas import job_view
from app.application.orchestrator import Orchestrator
from app.application.prompts import PromptLibrary
from app.config import Settings, get_settings
from app.domain.errors import BudgetExceeded, LLMQuotaExceeded
from app.domain.files import SourceFile
from app.domain.job import MigrationJob
from app.domain.ports import LLMClient, LLMRequest, LLMResponse
from app.frameworks import checks
from app.frameworks.registry import find_pair
from app.infrastructure.caching_llm import CachingLLMClient
from app.infrastructure.demo_llm import DemoLLMClient
from app.infrastructure.gemini_client import GeminiClient
from app.infrastructure.llm_decorators import (
    CircuitBreakerLLMClient,
    PacedLLMClient,
    RetryingLLMClient,
)
from app.infrastructure.sqlite_store import (
    SqliteEpisodeStore,
    SqliteJobRepository,
    SqliteResponseCache,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
EVAL = Path(__file__).resolve().parent
SETS = {
    "smoke": ["flask_todo"],
    "full": ["flask_todo", "express_users", "django_articles", "py2_report"],
}
MAX_AVG_CALLS = 12


class Meter:
    """Sits between the cache and the provider: counts real calls, enforces --max-calls,
    and remembers a quota stop so the harness can end the run."""

    def __init__(self, inner: LLMClient, max_calls: int) -> None:
        self._inner, self.max_calls = inner, max_calls
        self.calls = 0
        self.stop_reason: str | None = None

    def generate(self, request: LLMRequest) -> LLMResponse:
        if self.calls >= self.max_calls:
            self.stop_reason = self.stop_reason or "max-calls reached"
            raise BudgetExceeded(self.max_calls)
        self.calls += 1
        try:
            return self._inner.generate(request)
        except LLMQuotaExceeded as err:
            if err.scope == "day":
                self.stop_reason = "daily quota"
            raise


# ---- scoring (deterministic) -------------------------------------------------------


def score(job: MigrationJob, sample: dict) -> dict:
    """Re-runs the deterministic checks on the final files (independent of the job's own
    verification, so a lenient Verifier cannot inflate the score)."""
    pair = find_pair(sample["source_framework"], sample["target_framework"])
    migrated = job.current_files()
    results = checks.verify(pair, {s.path: s.content for s in job.sources}, migrated)
    by_name = {c.name: c for c in results}  # 'compiles' appears once per file
    routes = by_name.get("routes_preserved")
    return {
        "completed": job.phase.value == "completed",
        "success": job.success,
        "files": len(migrated),
        "compiles": bool(migrated) and all(c.passed for c in results if c.name == "compiles"),
        "routes_preserved": routes.passed if routes else None,
        "routes_detail": routes.detail if routes else "",
        "framework_migrated": "framework_migrated" in by_name
        and by_name["framework_migrated"].passed,
        "undefined_names": by_name["lint"].detail.count("F821") if "lint" in by_name else 0,
        "confidence": job.verification.confidence if job.verification else None,
        "steps": len(job.plan.steps) if job.plan else 0,
        "replans": job.replans,
        "calls": job.llm_calls,
        "cached_calls": job.cached_calls,
        "tokens_in": job.tokens_in,
        "tokens_out": job.tokens_out,
        "errors": job.errors,
    }


# ---- running -------------------------------------------------------------------------


def build_llm(settings: Settings, fake: bool, max_calls: int) -> tuple[LLMClient, Meter]:
    if fake:
        inner: LLMClient = DemoLLMClient()
    else:
        if not settings.google_api_key:
            sys.exit("GOOGLE_API_KEY is not set (source the .env or use --fake).")
        gemini = GeminiClient(
            settings.google_api_key, settings.gemini_model, settings.llm_timeout_s
        )
        inner = CircuitBreakerLLMClient(
            RetryingLLMClient(PacedLLMClient(gemini, settings.llm_min_interval_s))
        )
    meter = Meter(inner, max_calls)
    cache_path = EVAL / ("llm_cache.fake.db" if fake else "llm_cache.db")
    model = "demo" if fake else settings.gemini_model
    return CachingLLMClient(meter, SqliteResponseCache(str(cache_path)), model), meter


def run_sample(sample: dict, llm: LLMClient, settings: Settings, prompts: PromptLibrary):
    pair = find_pair(sample["source_framework"], sample["target_framework"])
    sources = [
        SourceFile(str(p.relative_to(SAMPLES / sample["id"])), p.read_text())
        for p in sorted((SAMPLES / sample["id"]).rglob("*"))
        if p.is_file()
    ]
    with tempfile.TemporaryDirectory() as tmp:  # fresh job DB: no episodes → stable prompts
        db = f"{tmp}/eval.db"
        jobs = SqliteJobRepository(db)
        job = MigrationJob.create(pair.id, sources, require_approval=False)
        jobs.create(job)
        Orchestrator(jobs, SqliteEpisodeStore(db), llm, prompts, settings).run(job.id)
        return jobs.get(job.id)


def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    settings = dataclasses.replace(
        settings,
        gemini_model=args.model or settings.gemini_model,
        llm_mode="fake" if args.fake else "gemini",
    )
    model = "demo" if args.fake else settings.gemini_model
    prompts = PromptLibrary()
    llm, meter = build_llm(settings, args.fake, args.max_calls)
    catalog = {s["id"]: s for s in json.loads((SAMPLES / "catalog.json").read_text())["samples"]}
    store = EVAL / "results" / model / f"prompt-v{prompts.version}"
    store.mkdir(parents=True, exist_ok=True)

    rows = []
    for sample_id in SETS[args.set]:
        if args.only and sample_id != args.only:
            continue
        sample = catalog[sample_id]
        row: dict = {"case": sample_id, "status": "", "score": None}
        if meter.stop_reason:
            row["status"] = f"skipped ({meter.stop_reason})"
        else:
            job = run_sample(sample, llm, settings, prompts)
            if meter.stop_reason:  # the job was cut short — do not score a partial run
                row["status"] = f"stopped ({meter.stop_reason})"
            else:
                view = job_view(job, model, prompts.version, include_history=True)
                (store / f"{sample_id}.json").write_text(view.model_dump_json(indent=2))
                row["status"] = "ran"
                row["score"] = score(job, sample)
        print_row(row)
        rows.append(row)

    report = write_report(rows, model, prompts.version, meter.calls, args.set)
    print(f"\nreal calls this run: {meter.calls}  →  {report.relative_to(ROOT)}")
    if meter.stop_reason:
        print(f"Run stopped ({meter.stop_reason}); re-run later to resume — answers are cached.")
    if args.publish:
        publish(store, [r["case"] for r in rows if r["score"] and r["score"]["success"]])
    return 0


def print_row(row: dict) -> None:
    s = row["score"]
    if not s:
        print(f"{row['case']:18} {row['status']}", flush=True)
        return
    print(
        f"{row['case']:18} {'OK ' if s['success'] else 'BAD'} compiles={s['compiles']} "
        f"routes={s['routes_preserved']} ({s['routes_detail']}) "
        f"framework={s['framework_migrated']} "
        f"F821={s['undefined_names']} confidence={s['confidence']} steps={s['steps']} "
        f"real calls={s['calls']} cached={s['cached_calls']}"
        + (f" errors={s['errors']}" if s["errors"] else ""),
        flush=True,
    )


def mark(ok: bool) -> str:
    return "✅" if ok else "❌"


def write_report(rows: list[dict], model: str, version: str, calls: int, set_name: str) -> Path:
    scored = [r["score"] for r in rows if r["score"]]
    n = len(scored)
    completed = sum(s["completed"] for s in scored)
    compiles = sum(s["compiles"] for s in scored)
    web = [s for s in scored if s["routes_preserved"] is not None]
    routes = sum(s["routes_preserved"] for s in web)
    framework = sum(s["framework_migrated"] for s in scored)
    undefined = sum(s["undefined_names"] for s in scored)
    avg_calls = sum(s["calls"] + s["cached_calls"] for s in scored) / n if n else 0
    lines = [
        f"# Evaluation report — `{model}`, prompt v{version}, set `{set_name}`",
        "",
        "Deterministic scoring (BACKEND_PLAN §12.3); the generated code is never executed.",
        "",
        f"- Jobs completed: **{completed}/{len(rows)}** {mark(completed == len(rows))}",
        f"- Migrated files parse + compile: **{compiles}/{n}** {mark(n > 0 and compiles == n)}",
        f"- Routes preserved (web pairs): **{routes}/{len(web)}** {mark(routes == len(web))}",
        f"- Source-framework imports / Py2 idioms gone: **{framework}/{n}** "
        f"{mark(n > 0 and framework == n)}",
        f"- Undefined names (F821): **{undefined}** {mark(undefined == 0)}",
        f"- LLM calls per job (avg, incl. cached): **{avg_calls:.1f}** "
        f"(target ≤ {MAX_AVG_CALLS}) {mark(n > 0 and avg_calls <= MAX_AVG_CALLS)}",
        f"- Real LLM calls in the last run: **{calls}** (cache hits cost 0)",
        "",
        "| Case | Status | Success | Compiles | Routes | Framework gone | F821 | Confidence "
        "| Steps | Real calls (cached) | Tokens in / out |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        s = r["score"]
        if s is None:
            lines.append(f"| {r['case']} | {r['status']} |" + " |" * 9)
            continue
        lines.append(
            f"| {r['case']} | {r['status']} | {mark(s['success'])} | {mark(s['compiles'])} "
            f"| {s['routes_detail'] or 'n/a'} | {mark(s['framework_migrated'])} "
            f"| {s['undefined_names']} | {s['confidence']} | {s['steps']} "
            f"| {s['calls']} ({s['cached_calls']}) | {s['tokens_in']} / {s['tokens_out']} |"
        )
    errors = [(r["case"], e) for r in rows if r["score"] for e in r["score"]["errors"]]
    if errors:
        lines += ["", "## Errors", ""] + [f"- `{case}`: {e}" for case, e in errors]
    path = EVAL / f"report_{set_name}{'_fake' if model == 'demo' else ''}.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def publish(store: Path, cases: list[str]) -> None:
    target = SAMPLES / "results"
    target.mkdir(exist_ok=True)
    for case in cases:
        shutil.copy(store / f"{case}.json", target / f"{case}.json")
    print(f"published {len(cases)} result(s) to {target.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--set", choices=sorted(SETS), default="smoke")
    parser.add_argument("--only", help="run a single sample id")
    parser.add_argument("--model", help="Gemini model (default: GEMINI_MODEL)")
    parser.add_argument("--max-calls", type=int, default=20, help="cap on REAL LLM calls")
    parser.add_argument("--fake", action="store_true", help="demo LLM: 0 calls")
    parser.add_argument("--publish", action="store_true", help="copy successes to samples/results")
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
