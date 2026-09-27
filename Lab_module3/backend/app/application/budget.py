"""Per-job LLM budget — the loop guard (course §5.4): a job can never exceed its call cap."""

import threading

from app.domain.errors import BudgetExceeded
from app.domain.job import MigrationJob
from app.domain.ports import LLMClient, LLMRequest, LLMResponse


class BudgetedLLMClient:
    def __init__(self, inner: LLMClient, job: MigrationJob, limit: int) -> None:
        self._inner, self._job, self._limit = inner, job, limit
        self._lock = threading.Lock()

    def generate(self, request: LLMRequest) -> LLMResponse:
        with self._lock:
            if self._job.llm_calls >= self._limit:
                raise BudgetExceeded(self._limit)
        response = self._inner.generate(request)
        with self._lock:
            if response.cached:
                self._job.cached_calls += 1
            else:
                self._job.llm_calls += 1
            self._job.tokens_in += response.usage.input
            self._job.tokens_out += response.usage.output + response.usage.thinking
        return response
