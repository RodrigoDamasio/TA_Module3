"""DAG scheduler (extension: parallel execution). Runs every step whose dependencies are
completed, up to `parallel` at a time. Job mutations happen under one lock."""

import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

from app.domain.job import MigrationJob


class StepScheduler:
    def __init__(self, parallel: int) -> None:
        self._parallel = max(1, parallel)

    def run(
        self,
        job: MigrationJob,
        lock: threading.RLock,
        start: Callable[[int], None],
        work: Callable[[int], None],
    ) -> None:
        """`start(step_id)` marks a step in progress (called under the lock);
        `work(step_id)` does the step's work and records its outcome (it takes the lock
        itself when mutating the job). Exceptions from `work` stop the run and propagate."""
        assert job.plan is not None  # noqa: S101 — the orchestrator guarantees a plan
        running: dict[int, Future] = {}
        with ThreadPoolExecutor(self._parallel, thread_name_prefix="step") as pool:
            try:
                while True:
                    with lock:
                        ready = [s for s in job.plan.ready_steps() if s.id not in running]
                        for step in ready[: self._parallel - len(running)]:
                            start(step.id)
                            running[step.id] = pool.submit(work, step.id)
                    if not running:
                        return
                    done, _ = wait(running.values(), return_when=FIRST_COMPLETED)
                    for step_id, future in list(running.items()):
                        if future in done:
                            running.pop(step_id)
                            future.result()  # re-raise quota / budget errors
            finally:
                for future in running.values():
                    future.cancel()
