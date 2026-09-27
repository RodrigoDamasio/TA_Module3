"""The four specialized agents of the pipeline (course §5.2): Analyzer → Planner →
Executor → Verifier. Each has its own persona, inputs, tools, and output schema."""

from app.config import Settings
from app.domain.errors import InvalidPath, InvalidPlan
from app.domain.files import validate_path
from app.domain.job import MigrationJob
from app.domain.plan import Complexity, Plan, PlanStep
from app.domain.ports import Episode, LLMClient
from app.domain.reports import Analysis, Check, VerificationIssue
from app.domain.schemas import (
    AnalysisLLM,
    AnalysisOut,
    PlanLLM,
    PlanOut,
    StepLLM,
    StepOut,
    VerificationLLM,
    VerificationOut,
)
from app.frameworks import routes as route_tools
from app.frameworks.imports import file_imports
from app.frameworks.registry import FrameworkPair
from app.tools.metrics import code_metrics
from app.tools.workspace import ANALYZER_TOOLS, VERIFIER_TOOLS, WorkspaceTools

from ..context import bullet, format_routes, numbered_files
from ..prompts import PromptLibrary
from .base import AgentCall, StructuredAgent


def analysis_text(analysis: Analysis | None) -> str:
    if analysis is None:
        return "(no analysis)"
    return (
        f"{analysis.summary}\nComponents:\n{bullet(analysis.components)}\n"
        f"Patterns:\n{bullet(analysis.patterns)}\nRisks:\n{bullet(analysis.risks)}"
    )


class Agents:
    def __init__(self, prompts: PromptLibrary, settings: Settings) -> None:
        self.prompts = prompts
        self.settings = settings
        self._core = StructuredAgent(prompts, settings.thinking_budget)

    # ---- Analyzer ------------------------------------------------------------------

    def analyze(self, llm: LLMClient, job: MigrationJob, pair: FrameworkPair) -> Analysis:
        sources = {f.path: f.content for f in job.sources}
        metrics = []
        for path, content in sources.items():
            m = code_metrics(path, content)
            metrics.append(
                f"{path}: {m['lines_of_code']} LOC, {m['functions']} functions, "
                f"max complexity {m['max_complexity']}"
            )
        imports = [
            f"{p}: {', '.join(sorted(file_imports(p, c))) or '(none)'}" for p, c in sources.items()
        ]
        call = AgentCall(
            system=self.prompts.system("analyzer", pair),
            user=self.prompts.task(
                "analyzer",
                max_tool_rounds=self.settings.max_tool_rounds,
                routes=format_routes(pair.source_routes(sources)),
                imports=bullet(imports),
                metrics=bullet(metrics),
                numbered_files=numbered_files(sources),
            ),
            lenient=AnalysisLLM,
            strict=AnalysisOut,
            max_output_tokens=2000,
            tools=ANALYZER_TOOLS,
            workspace=WorkspaceTools.for_sources(sources, pair),
            max_rounds=self.settings.max_tool_rounds,
        )
        out: AnalysisOut = self._core.ask(llm, call)
        return Analysis(out.summary, out.components, out.dependencies, out.patterns, out.risks)

    # ---- Planner -------------------------------------------------------------------

    def plan(
        self, llm: LLMClient, job: MigrationJob, pair: FrameworkPair, episodes: list[Episode]
    ) -> Plan:
        sources = {f.path: f.content for f in job.sources}
        lessons = [
            f"outcome: {e.outcome} · steps: {len(e.steps)} · learning: {e.learning}"
            for e in episodes
        ]
        call = AgentCall(
            system=self.prompts.system("planner", pair),
            user=self.prompts.task(
                "planner",
                source_files=bullet(sorted(sources)),
                routes=format_routes(pair.source_routes(sources)),
                analysis=analysis_text(job.analysis),
                pair=pair.id,
                episodes=bullet(lessons) if lessons else "- none yet",
                feedback=job.rejection_feedback or "(none — first plan)",
                max_steps=self.settings.max_plan_steps,
                example_pair="Flask → FastAPI",
                plan_example=self.prompts.plan_example(),
            ),
            lenient=PlanLLM,
            strict=PlanOut,
            max_output_tokens=3000,
        )

        def to_plan(out: PlanOut) -> Plan:
            steps = []
            for s in out.steps:
                try:
                    targets = [validate_path(t) for t in s.target_files]
                except InvalidPath as err:
                    raise ValueError(f"Step {s.id}: {err}") from err
                if any(not t.endswith(".py") for t in targets):
                    raise ValueError(f"Step {s.id}: target files must be Python (.py) files.")
                steps.append(
                    PlanStep(
                        s.id,
                        s.title,
                        s.description,
                        sorted(set(s.depends_on)),
                        Complexity(s.complexity),
                        [p for p in s.source_files if p in sources],
                        targets,
                    )
                )
            plan = Plan(steps)
            try:
                plan.validate(self.settings.max_plan_steps)
            except InvalidPlan as err:
                raise ValueError(f"The plan is invalid: {err}") from err
            return plan

        out: PlanOut = self._core.ask(llm, call, validate=to_plan)
        return to_plan(out)

    # ---- Executor ------------------------------------------------------------------

    def execute_step(
        self,
        llm: LLMClient,
        job: MigrationJob,
        pair: FrameworkPair,
        step: PlanStep,
        check_errors: list[str] | None = None,
    ) -> tuple[dict[str, str], str]:
        sources = {f.path: f.content for f in job.sources}
        reads = {p: sources[p] for p in step.source_files if p in sources} or sources
        current = job.current_files()
        targets_now = {p: current.get(p, "") for p in step.target_files}
        retry = self.prompts.step_retry(bullet(check_errors)) if check_errors else ""
        call = AgentCall(
            system=self.prompts.system("executor", pair),
            user=self.prompts.task(
                "executor",
                step_id=step.id,
                step_count=len(job.plan.steps) if job.plan else 1,
                step_title=step.title,
                step_description=step.description,
                analysis=analysis_text(job.analysis),
                routes=format_routes(pair.source_routes(sources)),
                numbered_sources=numbered_files(reads),
                current_targets=numbered_files({p: c for p, c in targets_now.items() if c})
                if any(targets_now.values())
                else "(new files)",
                target_files=", ".join(step.target_files),
                retry_block=retry,
            ),
            lenient=StepLLM,
            strict=StepOut,
            max_output_tokens=8192,
        )

        def check_files(out: StepOut) -> None:
            written = {f.path for f in out.files}
            if written != set(step.target_files):
                raise ValueError(
                    f"Return exactly these files: {sorted(step.target_files)} "
                    f"(got {sorted(written)})."
                )

        out: StepOut = self._core.ask(llm, call, validate=check_files)
        return {f.path: f.content for f in out.files}, out.notes

    # ---- Verifier ------------------------------------------------------------------

    def verify(
        self, llm: LLMClient, job: MigrationJob, pair: FrameworkPair, checks: list[Check]
    ) -> tuple[list[VerificationIssue], int, str]:
        sources = {f.path: f.content for f in job.sources}
        migrated = job.current_files()
        plan_lines = (
            [f"{s.id}. {s.title} — {s.status.value}" for s in job.plan.steps] if job.plan else []
        )
        call = AgentCall(
            system=self.prompts.system("verifier", pair),
            user=self.prompts.task(
                "verifier",
                checks=bullet(
                    [f"{c.name}: {'PASS' if c.passed else 'FAIL'} — {c.detail}" for c in checks]
                ),
                plan=bullet(plan_lines),
                numbered_sources=numbered_files(sources),
                numbered_migrated=numbered_files(migrated),
            ),
            lenient=VerificationLLM,
            strict=VerificationOut,
            max_output_tokens=2000,
            tools=VERIFIER_TOOLS,
            workspace=WorkspaceTools(migrated, route_tools.fastapi_routes),
            max_rounds=0,  # evidence is already in the prompt: 1 call keeps quota low
        )
        out: VerificationOut = self._core.ask(llm, call)
        issues = [VerificationIssue(i.severity, i.file, i.line, i.message) for i in out.issues]
        return issues, out.confidence, out.verdict


def episode_learning(job: MigrationJob) -> str:
    if job.errors:
        return f"Failed: {job.errors[-1][:200]}"
    if job.verification and not job.verification.passed:
        return "Checks passed but the reviewer had low confidence — keep steps smaller."
    steps = len(job.plan.steps) if job.plan else 0
    return f"Succeeded with {steps} steps and {job.llm_calls} LLM calls."
