"""MigrationJob aggregate: the agent's working memory and its state machine.

Every mutation goes through a method that validates it and emits a JobEvent; the
orchestrator persists the job and its new events together, so the SSE stream and the
stored state can never disagree.
"""

import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .errors import InvalidTransition
from .files import FileVersion, SourceFile
from .plan import Complexity, Plan, PlanStep, StepStatus
from .reports import Analysis, Check, VerificationIssue, VerificationReport


class Phase(StrEnum):
    ANALYSIS = "analysis"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTION = "execution"
    VERIFICATION = "verification"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ROLLED_BACK = "rolled_back"


TERMINAL = frozenset({Phase.COMPLETED, Phase.FAILED, Phase.CANCELLED, Phase.ROLLED_BACK})
RUNNING = frozenset({Phase.ANALYSIS, Phase.PLANNING, Phase.EXECUTION, Phase.VERIFICATION})

_TRANSITIONS: dict[Phase, set[Phase]] = {
    Phase.ANALYSIS: {Phase.PLANNING, Phase.FAILED},
    Phase.PLANNING: {Phase.AWAITING_APPROVAL, Phase.EXECUTION, Phase.FAILED},
    Phase.AWAITING_APPROVAL: {Phase.EXECUTION, Phase.PLANNING, Phase.CANCELLED, Phase.FAILED},
    Phase.EXECUTION: {Phase.VERIFICATION, Phase.FAILED},
    Phase.VERIFICATION: {Phase.EXECUTION, Phase.COMPLETED, Phase.FAILED},
    Phase.COMPLETED: {Phase.ROLLED_BACK},
    Phase.FAILED: {Phase.ROLLED_BACK},
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class JobEvent:
    type: str  # phase | analysis | plan | step | verification | error | done
    data: dict[str, Any]
    id: int | None = None  # assigned by the repository (SSE event id)


@dataclass
class MigrationJob:
    id: str
    pair: str
    sources: list[SourceFile]
    require_approval: bool
    phase: Phase = Phase.ANALYSIS
    analysis: Analysis | None = None
    plan: Plan | None = None
    versions: list[FileVersion] = field(default_factory=list)
    verification: VerificationReport | None = None
    errors: list[str] = field(default_factory=list)
    llm_calls: int = 0
    cached_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    replans: int = 0
    rejection_feedback: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    finished_at: str | None = None
    approval_requested_at: str | None = None
    pending_events: list[JobEvent] = field(default_factory=list)

    @classmethod
    def create(cls, pair: str, sources: list[SourceFile], require_approval: bool) -> "MigrationJob":
        job = cls(f"mig_{secrets.token_hex(6)}", pair, sources, require_approval)
        job._emit("phase", phase=job.phase.value)
        return job

    # ---- events ---------------------------------------------------------------

    def _emit(self, type_: str, **data: Any) -> None:
        self.updated_at = _now()
        self.pending_events.append(JobEvent(type_, data))

    def pop_events(self) -> list[JobEvent]:
        events, self.pending_events = self.pending_events, []
        return events

    # ---- phases -----------------------------------------------------------------

    def move_to(self, phase: Phase, **detail: Any) -> None:
        if phase not in _TRANSITIONS.get(self.phase, set()):
            raise InvalidTransition(self.phase.value, phase.value)
        self.phase = phase
        if phase is Phase.AWAITING_APPROVAL:
            self.approval_requested_at = _now()
        if phase in TERMINAL:
            self.finished_at = _now()
        self._emit("phase", phase=phase.value, **detail)

    def set_analysis(self, analysis: Analysis) -> None:
        self.analysis = analysis
        self._emit("analysis", **asdict(analysis))

    def set_plan(self, plan: Plan, max_steps: int) -> None:
        plan.validate(max_steps)
        if self.plan is not None:
            plan.revision = self.plan.revision + 1
        self.plan = plan
        self._emit("plan", **plan_to_dict(plan))

    def approve(self) -> None:
        if self.phase is not Phase.AWAITING_APPROVAL:
            raise InvalidTransition(self.phase.value, "approve")
        self.move_to(Phase.EXECUTION, approved=True)

    def reject(self, feedback: str | None, max_replans: int = 1) -> None:
        if self.phase is not Phase.AWAITING_APPROVAL:
            raise InvalidTransition(self.phase.value, "reject")
        if feedback and self.replans < max_replans:
            self.replans += 1
            self.rejection_feedback = feedback
            self.move_to(Phase.PLANNING, replan=True)
        else:
            self.move_to(Phase.CANCELLED, reason="plan rejected")
            self._emit("done", success=False, phase=self.phase.value)

    def cancel(self, reason: str) -> None:
        self.move_to(Phase.CANCELLED, reason=reason)
        self._emit("done", success=False, phase=self.phase.value)

    # ---- steps ------------------------------------------------------------------

    def start_step(self, step_id: int) -> PlanStep:
        step = self._plan().step(step_id)
        step.status = StepStatus.IN_PROGRESS
        step.attempts += 1
        step.error = None
        self._emit("step", **step_to_dict(step))
        return step

    def complete_step(self, step_id: int, files: dict[str, str], notes: str = "") -> None:
        step = self._plan().step(step_id)
        for path, content in files.items():
            version = 1 + sum(1 for v in self.versions if v.path == path)
            self.versions.append(FileVersion(path, content, version, step_id))
        step.status = StepStatus.COMPLETED
        step.notes = notes or None
        self._emit("step", **step_to_dict(step), files=sorted(files))

    def fail_step(self, step_id: int, error: str) -> None:
        plan = self._plan()
        step = plan.step(step_id)
        self._hide_versions(step_id)
        step.status = StepStatus.FAILED
        step.error = error
        self._emit("step", **step_to_dict(step))
        for dependent in plan.dependents(step_id):
            if dependent.status is StepStatus.PENDING:
                dependent.status = StepStatus.SKIPPED
                self._emit("step", **step_to_dict(dependent))

    def reopen_step(self, step_id: int) -> None:
        """Verification retry: discard the step's output so it can run again."""
        step = self._plan().step(step_id)
        self._hide_versions(step_id)
        step.status = StepStatus.PENDING
        self._emit("step", **step_to_dict(step))

    def _hide_versions(self, step_id: int) -> None:
        for v in self.versions:
            if v.step_id == step_id:
                v.hidden = True

    # ---- verification and end states -----------------------------------------------

    def set_verification(self, report: VerificationReport) -> None:
        self.verification = report
        self._emit("verification", **verification_to_dict(report))

    def complete(self) -> None:
        self.move_to(Phase.COMPLETED)
        self._emit("done", success=self.success, phase=self.phase.value)

    def fail(self, error: str) -> None:
        self.errors.append(error)
        self._emit("error", message=error)
        if self.phase not in TERMINAL:
            self.move_to(Phase.FAILED)
            self._emit("done", success=False, phase=self.phase.value)

    def rollback(self) -> None:
        if self.phase not in (Phase.COMPLETED, Phase.FAILED):
            raise InvalidTransition(self.phase.value, "rollback")
        for v in self.versions:
            v.hidden = True
        for step in self._plan().steps if self.plan else []:
            if step.status in (StepStatus.COMPLETED, StepStatus.FAILED):
                step.status = StepStatus.ROLLED_BACK
        self.move_to(Phase.ROLLED_BACK)
        self._emit("done", success=False, phase=self.phase.value)

    # ---- queries ---------------------------------------------------------------------

    @property
    def success(self) -> bool:
        return (
            self.phase is Phase.COMPLETED
            and self.verification is not None
            and self.verification.passed
        )

    def current_files(self) -> dict[str, str]:
        latest: dict[str, FileVersion] = {}
        for v in self.versions:
            if not v.hidden and (v.path not in latest or v.version > latest[v.path].version):
                latest[v.path] = v
        return {path: v.content for path, v in sorted(latest.items())}

    def latest_version(self, path: str) -> FileVersion | None:
        visible = [v for v in self.versions if v.path == path and not v.hidden]
        return max(visible, key=lambda v: v.version) if visible else None

    def _plan(self) -> Plan:
        if self.plan is None:
            raise InvalidTransition(self.phase.value, "step without a plan")
        return self.plan


# ---- serialization (stdlib only; used by the repository and the API) ---------------


def step_to_dict(step: PlanStep) -> dict[str, Any]:
    return {k: (v.value if isinstance(v, StrEnum) else v) for k, v in asdict(step).items()}


def plan_to_dict(plan: Plan) -> dict[str, Any]:
    return {"revision": plan.revision, "steps": [step_to_dict(s) for s in plan.steps]}


def verification_to_dict(report: VerificationReport) -> dict[str, Any]:
    return {
        "passed": report.passed,
        "checks_passed": report.checks_passed,
        "confidence": report.confidence,
        "verdict": report.verdict,
        "checks": [asdict(c) for c in report.checks],
        "issues": [asdict(i) for i in report.issues],
    }


def job_to_dict(job: MigrationJob) -> dict[str, Any]:
    data = {
        k: v
        for k, v in asdict(job).items()
        if k not in ("pending_events", "plan", "verification", "phase")
    }
    data["phase"] = job.phase.value
    data["plan"] = plan_to_dict(job.plan) if job.plan else None
    data["verification"] = verification_to_dict(job.verification) if job.verification else None
    return data


def job_from_dict(data: dict[str, Any]) -> MigrationJob:
    plan = None
    if data.get("plan"):
        plan = Plan(
            steps=[
                PlanStep(
                    **{
                        **s,
                        "status": StepStatus(s["status"]),
                        "complexity": Complexity(s["complexity"]),
                    }
                )
                for s in data["plan"]["steps"]
            ],
            revision=data["plan"]["revision"],
        )
    verification = None
    if data.get("verification"):
        v = data["verification"]
        verification = VerificationReport(
            checks=[Check(**c) for c in v["checks"]],
            issues=[VerificationIssue(**i) for i in v["issues"]],
            confidence=v["confidence"],
            verdict=v["verdict"],
        )
    fields = {k: v for k, v in data.items() if k not in ("plan", "verification")}
    return MigrationJob(
        **{
            **fields,
            "phase": Phase(data["phase"]),
            "sources": [SourceFile(**s) for s in data["sources"]],
            "analysis": Analysis(**data["analysis"]) if data.get("analysis") else None,
            "versions": [FileVersion(**v) for v in data["versions"]],
            "plan": plan,
            "verification": verification,
        }
    )
