"""Wiring: the only place that chooses concrete implementations. One Container per app
(tests build their own with a temp database and a fake LLM)."""

from dataclasses import dataclass

from fastapi import Depends, Request

from app.application.migrations import MigrationService
from app.application.orchestrator import Orchestrator
from app.application.prompts import PromptLibrary
from app.config import Settings
from app.domain.ports import JobRepository, LLMClient
from app.infrastructure.caching_llm import CachingLLMClient
from app.infrastructure.demo_llm import DemoLLMClient
from app.infrastructure.gemini_client import GeminiClient
from app.infrastructure.llm_decorators import (
    CircuitBreakerLLMClient,
    ConcurrencyLimitedLLMClient,
    PacedLLMClient,
    RetryingLLMClient,
)
from app.infrastructure.runner import InlineRunner, ThreadRunner
from app.infrastructure.samples import SampleStore
from app.infrastructure.sqlite_store import (
    SqliteEpisodeStore,
    SqliteJobRepository,
    SqliteResponseCache,
)

from .guards import RateLimiter


@dataclass
class Container:
    settings: Settings
    jobs: JobRepository
    service: MigrationService
    runner: InlineRunner | ThreadRunner
    prompts: PromptLibrary
    samples: SampleStore
    limiter: RateLimiter

    @property
    def model(self) -> str:
        return self.settings.gemini_model if self.settings.llm_mode == "gemini" else "demo"


def gemini_stack(settings: Settings) -> tuple[LLMClient, CircuitBreakerLLMClient]:
    """Outermost first: Caching → CircuitBreaker → Retrying → ConcurrencyLimited → Paced → Gemini.
    A cache hit costs nothing and is served even while the breaker is open."""
    if not settings.google_api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set (or use LLM_MODE=fake).")
    gemini = GeminiClient(settings.google_api_key, settings.gemini_model, settings.llm_timeout_s)
    gated = ConcurrencyLimitedLLMClient(
        PacedLLMClient(gemini, settings.llm_min_interval_s),
        limit=1,  # parallel steps share one free-tier quota: calls stay serialized
        wait_s=settings.llm_timeout_s * 3,
    )
    breaker = CircuitBreakerLLMClient(RetryingLLMClient(gated))
    cache = SqliteResponseCache(settings.database_path)
    return CachingLLMClient(breaker, cache, settings.gemini_model), breaker


def build_container(settings: Settings, llm: LLMClient | None = None) -> Container:
    ensure_quota = None
    if llm is None:
        if settings.llm_mode == "fake":
            llm = DemoLLMClient()
        else:
            llm, breaker = gemini_stack(settings)
            ensure_quota = breaker.ensure_closed
    jobs = SqliteJobRepository(settings.database_path)
    prompts = PromptLibrary()
    orchestrator = Orchestrator(
        jobs, SqliteEpisodeStore(settings.database_path), llm, prompts, settings
    )
    runner: InlineRunner | ThreadRunner
    if settings.runner_mode == "inline":
        runner = InlineRunner(orchestrator)
    else:
        runner = ThreadRunner(
            orchestrator, jobs, settings.max_queued_jobs, settings.approval_timeout_min
        )
    service = MigrationService(jobs, runner, settings, ensure_quota or (lambda: None))
    return Container(
        settings=settings,
        jobs=jobs,
        service=service,
        runner=runner,
        prompts=prompts,
        samples=SampleStore(),
        limiter=RateLimiter(settings.rate_limit_jobs_per_minute, settings.rate_limit_jobs_per_day),
    )


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_service(container: Container = Depends(get_container)) -> MigrationService:
    return container.service
