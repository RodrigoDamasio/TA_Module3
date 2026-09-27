"""Orchestrator: runs a job through analysis → planning → (approval) → execution →
verification, persisting after every transition (working memory survives restarts)."""

import logging
import threading

from app.config import Settings
from app.domain.errors import BudgetExceeded, DomainError, LLMError
from app.domain.job import TERMINAL, MigrationJob, Phase
from app.domain.plan import StepStatus
from app.domain.ports import Episode, EpisodeStore, JobRepository, LLMClient
from app.domain.reports import VerificationReport
from app.frameworks import checks as code_checks
from app.frameworks.registry import PAIRS, FrameworkPair

from .agents.pipeline import Agents, episode_learning
from .budget import BudgetedLLMClient
from .prompts import PromptLibrary
from .scheduler import StepScheduler

logger = logging.getLogger("app.orchestrator")
MAX_STEP_ATTEMPTS = 2  # first try + one retry with check feedback


class Orchestrator:
    def __init__(
        self,
        jobs: JobRepository,
        episodes: EpisodeStore,
        llm: LLMClient,
        prompts: PromptLibrary,
        settings: Settings,
    ) -> None:
        self.jobs, self.episodes, self.llm = jobs, episodes, llm
        self.settings = settings
        self.agents = Agents(prompts, settings)
        self.scheduler = StepScheduler(settings.parallel_steps)

    def run(self, job_id: str) -> None:
        """Advance the job until it pauses (awaiting approval) or finishes."""
        job = self.jobs.get(job_id)
        pair = PAIRS[job.pair]
        lock = threading.RLock()
        llm = BudgetedLLMClient(self.llm, job, self.settings.job_llm_budget)

        def save() -> None:
            with lock:
                self.jobs.save(job)

        try:
            if job.phase is Phase.ANALYSIS:
                job.set_analysis(self.agents.analyze(llm, job, pair))
                job.move_to(Phase.PLANNING)
                save()
            if job.phase is Phase.PLANNING:
                episodes = self.episodes.recent(pair.id, 3)
                job.set_plan(
                    self.agents.plan(llm, job, pair, episodes), self.settings.max_plan_steps
                )
                if job.require_approval:
                    job.move_to(Phase.AWAITING_APPROVAL)
                    save()
                    return
                job.move_to(Phase.EXECUTION, approved=False)
                save()
            if job.phase is Phase.EXECUTION:
                self._execute(job, pair, llm, lock, save, feedback={})
            if job.phase is Phase.VERIFICATION:
                self._verify(job, pair, llm, lock, save)
        except (LLMError, BudgetExceeded, DomainError) as err:
            logger.warning("job %s failed: %s", job.id, err)
            with lock:
                job.fail(str(err))
        except Exception:
            logger.exception("job %s crashed", job.id)
            with lock:
                job.fail("Unexpected internal error.")
        finally:
            save()
            if job.phase in TERMINAL:
                self._record_episode(job)

    # ---- execution -------------------------------------------------------------------

    def _execute(self, job, pair, llm, lock, save, feedback: dict[int, list[str]]) -> None:
        def start(step_id: int) -> None:
            job.start_step(step_id)
            self.jobs.save(job)

        def work(step_id: int) -> None:
            errors = feedback.get(step_id)
            while True:
                step = job.plan.step(step_id)
                files, notes = self.agents.execute_step(llm, job, pair, step, errors)
                problems = code_checks.check_python(files)
                with lock:
                    if not problems:
                        job.complete_step(step_id, files, notes)
                        self.jobs.save(job)
                        return
                    if step.attempts >= MAX_STEP_ATTEMPTS:
                        job.fail_step(step_id, "; ".join(problems[:5]))
                        self.jobs.save(job)
                        return
                    errors = problems
                    job.start_step(step_id)  # retry with the check output as feedback
                    self.jobs.save(job)

        self.scheduler.run(job, lock, start, work)
        failed = [s for s in job.plan.steps if s.status is StepStatus.FAILED]
        with lock:
            if failed:
                job.fail(f"Step {failed[0].id} ({failed[0].title}) failed: {failed[0].error}")
            else:
                job.move_to(Phase.VERIFICATION)
        save()

    # ---- verification ------------------------------------------------------------------

    def _verify(self, job, pair: FrameworkPair, llm, lock, save) -> None:
        sources = {f.path: f.content for f in job.sources}
        checks = code_checks.verify(pair, sources, job.current_files())
        failing = [c for c in checks if not c.passed]
        if failing:
            retry = self._steps_to_retry(job, failing)
            if retry:
                with lock:
                    feedback = {}
                    for step_id in retry:
                        job.reopen_step(step_id)
                        feedback[step_id] = [f"{c.name}: {c.detail}" for c in failing]
                    job.move_to(Phase.EXECUTION, retry_steps=sorted(retry))
                save()
                self._execute(job, pair, llm, lock, save, feedback)
                if job.phase is not Phase.VERIFICATION:
                    return
                checks = code_checks.verify(pair, sources, job.current_files())
                failing = [c for c in checks if not c.passed]

        if failing:  # still broken: no LLM review (saves quota), fail with the evidence
            with lock:
                job.set_verification(VerificationReport(checks))
                job.fail("Verification failed: " + "; ".join(c.detail for c in failing)[:500])
            return

        issues, confidence, verdict = self.agents.verify(llm, job, pair, checks)
        with lock:
            job.set_verification(VerificationReport(checks, issues, confidence, verdict))
            job.complete()

    @staticmethod
    def _steps_to_retry(job: MigrationJob, failing) -> set[int]:
        """The last completed step that wrote each failing file (or the last completed step
        when a check is project-wide, e.g. routes). _verify retries at most once."""
        completed = [s for s in job.plan.steps if s.status is StepStatus.COMPLETED]
        steps: set[int] = set()
        for check in failing:
            writers = [s for s in completed if check.file is None or check.file in s.target_files]
            if writers:
                steps.add(max(writers, key=lambda s: s.id).id)
        return steps

    def _record_episode(self, job: MigrationJob) -> None:
        try:
            self.episodes.record(
                Episode(
                    pair=job.pair,
                    outcome="success" if job.success else "failure",
                    steps=[s.title for s in job.plan.steps] if job.plan else [],
                    errors=job.errors[-3:],
                    learning=episode_learning(job),
                )
            )
        except Exception:  # memory must never break a job
            logger.exception("could not record episode for %s", job.id)
