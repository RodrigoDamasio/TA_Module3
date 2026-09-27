"""Job runners. ThreadRunner: one background worker + queue (jobs run one at a time — the
free-tier quota is shared) and an approval-timeout sweeper. InlineRunner: synchronous
(tests, evaluation)."""

import logging
import queue
import threading
from datetime import UTC, datetime, timedelta

from app.domain.errors import QueueFull
from app.domain.job import RUNNING, Phase
from app.domain.ports import JobRepository

logger = logging.getLogger("app.runner")


class InlineRunner:
    def __init__(self, orchestrator) -> None:
        self._orchestrator = orchestrator

    def submit(self, job_id: str) -> None:
        self._orchestrator.run(job_id)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class ThreadRunner:
    def __init__(
        self, orchestrator, jobs: JobRepository, max_queued: int, approval_timeout_min: int
    ) -> None:
        self._orchestrator = orchestrator
        self._jobs = jobs
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=max_queued)
        self._timeout = timedelta(minutes=approval_timeout_min)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def submit(self, job_id: str) -> None:
        try:
            self._queue.put_nowait(job_id)
        except queue.Full as err:
            raise QueueFull() from err

    def start(self) -> None:
        self.recover()
        self._threads = [
            threading.Thread(target=self._work, name="job-runner", daemon=True),
            threading.Thread(target=self._sweep, name="approval-sweeper", daemon=True),
        ]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()
        if not self._queue.full():
            self._queue.put_nowait(None)  # wake the worker so it can exit

    def recover(self) -> None:
        """Jobs left running by a restart cannot resume mid-call: mark them failed."""
        for job in self._jobs.jobs_in_phases({p.value for p in RUNNING}):
            job.fail("Interrupted by a server restart — please submit the migration again.")
            self._jobs.save(job)

    def _work(self) -> None:
        while not self._stop.is_set():
            job_id = self._queue.get()
            if job_id is None:
                return
            try:
                self._orchestrator.run(job_id)
            except Exception:  # the orchestrator records failures; never kill the worker
                logger.exception("runner crashed on %s", job_id)

    def _sweep(self) -> None:
        while not self._stop.wait(60):
            self.expire_approvals()

    def expire_approvals(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        expired = 0
        for job in self._jobs.jobs_in_phases({Phase.AWAITING_APPROVAL.value}):
            requested = datetime.fromisoformat(job.approval_requested_at or job.updated_at)
            if now - requested > self._timeout:
                job.cancel("approval timed out")
                self._jobs.save(job)
                expired += 1
        return expired
