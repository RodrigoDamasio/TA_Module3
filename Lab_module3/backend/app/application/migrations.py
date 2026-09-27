"""MigrationService: the use cases behind the HTTP API — submit a job, approve or reject
its plan, roll it back. Validation of limits happens here, before any LLM call."""

import logging
from collections.abc import Callable

from app.config import Settings
from app.domain.errors import InputTooLarge, InvalidPath, QueueFull
from app.domain.files import SourceFile, validate_path
from app.domain.job import MigrationJob, Phase
from app.domain.ports import JobRepository, JobRunner
from app.frameworks.registry import find_pair

logger = logging.getLogger("app.migrations")


class MigrationService:
    def __init__(
        self,
        jobs: JobRepository,
        runner: JobRunner,
        settings: Settings,
        ensure_quota: Callable[[], None] = lambda: None,
    ) -> None:
        self.jobs, self.runner, self.settings = jobs, runner, settings
        self._ensure_quota = ensure_quota  # raises LLMQuotaExceeded when the day is used up

    def check_input(
        self, files: list[tuple[str, str]], source: str, target: str
    ) -> list[SourceFile]:
        """Everything that can reject a request for free: pair, paths, sizes."""
        pair = find_pair(source, target)
        if len(files) > self.settings.max_files:
            raise InputTooLarge(f"At most {self.settings.max_files} files per migration.")
        total = sum(len(content) for _, content in files)
        if total > self.settings.max_total_chars:
            raise InputTooLarge(
                f"The files have {total} characters; the limit is {self.settings.max_total_chars}."
            )
        sources, seen = [], set()
        for path, content in files:
            clean = validate_path(path)
            if not clean.endswith(tuple(pair.source_extensions)):
                allowed = ", ".join(sorted(pair.source_extensions))
                raise InvalidPath(f"{pair.source_name} files must end in {allowed}: {path!r}.")
            if clean in seen:
                raise InvalidPath(f"Duplicate file path: {clean!r}.")
            seen.add(clean)
            sources.append(SourceFile(clean, content))
        return sources

    def submit(
        self, files: list[tuple[str, str]], source: str, target: str, require_approval: bool
    ) -> MigrationJob:
        sources = self.check_input(files, source, target)
        self._ensure_quota()
        if not self.runner.has_capacity():
            raise QueueFull()
        job = MigrationJob.create(find_pair(source, target).id, sources, require_approval)
        self.jobs.create(job)
        self._run(job)
        # Never log code: ids, sizes and counts only.
        logger.info(
            "job %s submitted pair=%s files=%d chars=%d approval=%s",
            job.id,
            job.pair,
            len(sources),
            sum(len(s.content) for s in sources),
            require_approval,
        )
        return self.jobs.get(job.id)

    def get(self, job_id: str) -> MigrationJob:
        return self.jobs.get(job_id)

    def approve(self, job_id: str) -> MigrationJob:
        job = self.jobs.get(job_id)
        if job.phase is Phase.AWAITING_APPROVAL and not self.runner.has_capacity():
            raise QueueFull()
        job.approve()
        self.jobs.save(job)
        self._run(job)
        return self.jobs.get(job_id)

    def reject(self, job_id: str, feedback: str | None) -> MigrationJob:
        job = self.jobs.get(job_id)
        replanning = bool(feedback) and job.replans < 1
        if job.phase is Phase.AWAITING_APPROVAL and replanning and not self.runner.has_capacity():
            raise QueueFull()
        job.reject(feedback)
        self.jobs.save(job)
        if job.phase is Phase.PLANNING:
            self._run(job)
        return self.jobs.get(job_id)

    def rollback(self, job_id: str) -> MigrationJob:
        job = self.jobs.get(job_id)
        job.rollback()
        self.jobs.save(job)
        return job

    def _run(self, job: MigrationJob) -> None:
        try:
            self.runner.submit(job.id)
        except QueueFull:
            # Rare race (the queue filled since the capacity check): never leave the job
            # stuck in a running phase.
            job = self.jobs.get(job.id)
            job.fail("The server was too busy to start this migration; please retry.")
            self.jobs.save(job)
            raise
