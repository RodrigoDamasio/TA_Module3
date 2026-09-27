import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    google_api_key: str | None
    gemini_model: str
    llm_mode: str  # gemini | fake
    llm_min_interval_s: float
    llm_timeout_s: int
    thinking_budget: int
    max_files: int
    max_total_chars: int
    max_plan_steps: int
    job_llm_budget: int
    max_tool_rounds: int
    parallel_steps: int
    approval_timeout_min: int
    max_queued_jobs: int
    rate_limit_jobs_per_minute: int
    rate_limit_jobs_per_day: int
    sync_wait_timeout_s: int
    runner_mode: str  # thread | inline (tests)
    database_path: str
    base_url: str
    frontend_origins: list[str]


def get_settings() -> Settings:
    return Settings(
        google_api_key=os.getenv("GOOGLE_API_KEY") or None,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        llm_mode=os.getenv("LLM_MODE", "gemini"),
        llm_min_interval_s=_float("LLM_MIN_INTERVAL_S", 6.0),
        llm_timeout_s=_int("LLM_TIMEOUT_S", 90),
        thinking_budget=_int("THINKING_BUDGET", 1024),
        max_files=_int("MAX_FILES", 5),
        max_total_chars=_int("MAX_TOTAL_CHARS", 30000),
        max_plan_steps=_int("MAX_PLAN_STEPS", 8),
        job_llm_budget=_int("JOB_LLM_BUDGET", 16),
        max_tool_rounds=_int("MAX_TOOL_ROUNDS", 2),
        parallel_steps=_int("PARALLEL_STEPS", 2),
        approval_timeout_min=_int("APPROVAL_TIMEOUT_MIN", 30),
        max_queued_jobs=_int("MAX_QUEUED_JOBS", 5),
        rate_limit_jobs_per_minute=_int("RATE_LIMIT_JOBS_PER_MINUTE", 2),
        rate_limit_jobs_per_day=_int("RATE_LIMIT_JOBS_PER_DAY", 10),
        sync_wait_timeout_s=_int("SYNC_WAIT_TIMEOUT_S", 180),
        runner_mode=os.getenv("RUNNER_MODE", "thread"),
        database_path=os.getenv("DATABASE_PATH", "migrations.db"),
        base_url=os.getenv("BASE_URL", "http://localhost:8000").rstrip("/"),
        frontend_origins=[
            origin.strip().rstrip("/")
            for origin in os.getenv("FRONTEND_ORIGIN", "http://localhost:3000").split(",")
            if origin.strip()
        ],
    )
