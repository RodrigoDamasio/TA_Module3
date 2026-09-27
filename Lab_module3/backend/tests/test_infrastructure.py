"""SQLite stores, response cache, runner, Gemini adapter, quota decorators (Q1–Q4)."""

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fakes import FakeLLM
from google.genai import errors, types

from app.domain.errors import (
    JobNotFound,
    LLMOverloaded,
    LLMQuotaExceeded,
    LLMUnavailable,
    QueueFull,
)
from app.domain.files import SourceFile
from app.domain.job import MigrationJob, Phase
from app.domain.ports import (
    AssistantMessage,
    Episode,
    LLMRequest,
    ToolCall,
    ToolResult,
    ToolResultsMessage,
    UserMessage,
)
from app.domain.schemas import AnalysisLLM
from app.infrastructure.caching_llm import CachingLLMClient, request_key
from app.infrastructure.gemini_client import quota_error, to_contents, to_response
from app.infrastructure.llm_decorators import (
    CircuitBreakerLLMClient,
    ConcurrencyLimitedLLMClient,
    PacedLLMClient,
    RetryingLLMClient,
)
from app.infrastructure.runner import ThreadRunner
from app.infrastructure.sqlite_store import (
    SqliteEpisodeStore,
    SqliteJobRepository,
    SqliteResponseCache,
)

REQ = LLMRequest("sys", [UserMessage("hi")], response_schema=AnalysisLLM)


def new_job() -> MigrationJob:
    return MigrationJob.create("flask-fastapi", [SourceFile("app.py", "x = 1\n")], True)


# Q4
def test_job_and_events_are_saved_atomically(tmp_path):
    repo = SqliteJobRepository(str(tmp_path / "db" / "m.db"))
    job = new_job()
    repo.create(job)
    job.move_to(Phase.PLANNING)
    repo.save(job)
    loaded = repo.get(job.id)
    assert loaded.phase is Phase.PLANNING
    events = repo.events_since(job.id, 0)
    assert [e.data["phase"] for e in events] == ["analysis", "planning"]
    assert repo.events_since(job.id, events[0].id)[0].data["phase"] == "planning"
    assert [j.id for j in repo.jobs_in_phases({"planning"})] == [job.id]
    with pytest.raises(JobNotFound):
        repo.get("mig_nope")
    with pytest.raises(JobNotFound):
        repo.get("' OR '1'='1")  # bound parameter, not SQL


def test_episodes_most_recent_first(tmp_path):
    store = SqliteEpisodeStore(str(tmp_path / "m.db"))
    for n in range(4):
        store.record(Episode("flask-fastapi", "success", [f"s{n}"], [], f"lesson {n}"))
    store.record(Episode("django-fastapi", "failure", [], ["x"], "other"))
    assert [e.learning for e in store.recent("flask-fastapi", 3)] == [
        "lesson 3",
        "lesson 2",
        "lesson 1",
    ]


# Q1
def test_identical_request_is_served_from_cache(tmp_path):
    llm = FakeLLM()
    cache = CachingLLMClient(llm, SqliteResponseCache(str(tmp_path / "m.db")), "m1")
    first = cache.generate(REQ)
    second = cache.generate(REQ)
    assert len(llm.requests) == 1 and not first.cached and second.cached
    assert second.parsed == first.parsed
    other_model = CachingLLMClient(llm, SqliteResponseCache(str(tmp_path / "m.db")), "m2")
    other_model.generate(REQ)
    assert len(llm.requests) == 2
    assert request_key("m1", REQ) != request_key(
        "m1", LLMRequest("sys", [UserMessage("hey")], response_schema=AnalysisLLM)
    )


def test_tool_call_turns_are_cached_and_replayable(tmp_path):
    llm = FakeLLM(tool_first=True)
    cache = CachingLLMClient(llm, SqliteResponseCache(str(tmp_path / "m.db")), "m1")
    req = LLMRequest("sys", [UserMessage("find routes")], tools=[])
    first = cache.generate(req)
    replay = cache.generate(req)
    assert not first.cached and replay.cached and replay.tool_calls[0].name == "find_text"


# Q2
def test_adapter_rebuilds_function_call_parts_without_raw_turn():
    contents = to_contents(
        [
            UserMessage("task"),
            AssistantMessage(None, [ToolCall("c1", "read_file", {"path": "app.py"})]),
            ToolResultsMessage([ToolResult("c1", "read_file", "1│ x")]),
            AssistantMessage("notes", []),
        ]
    )
    assert [c.role for c in contents] == ["user", "model", "user", "model"]
    call = contents[1].parts[0].function_call
    assert (call.name, call.args) == ("read_file", {"path": "app.py"})
    assert contents[3].parts[0].text == "notes"


def test_recorded_real_gemini_responses_still_map():
    cassettes = sorted(Path(__file__).parent.joinpath("cassettes").glob("*.json"))
    first = to_response(
        types.GenerateContentResponse.model_validate(json.loads(cassettes[0].read_text()))
    )
    assert first.tool_calls and first.usage.input > 0


def test_daily_quota_waits_for_the_real_reset():
    body = {
        "error": {
            "code": 429,
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
                    ],
                },
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "12s"},
            ],
        }
    }
    from zoneinfo import ZoneInfo

    noon = datetime(2026, 9, 27, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    err = quota_error(errors.ClientError(429, body), now=noon)
    assert (err.scope, err.retry_after_s) == ("day", 43200)


# Q3 — Lab 2 decorators still behave
class Clock:
    def __init__(self):
        self.now, self.slept = 1000.0, []

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def test_quota_decorators():
    clock = Clock()
    paced = PacedLLMClient(FakeLLM(), 6, clock, clock.sleep)
    paced.generate(REQ)
    paced.generate(REQ)
    assert clock.slept == [6]

    inner = FakeLLM()
    inner.fail = {"AnalysisLLM": LLMOverloaded("503")}
    with pytest.raises(LLMOverloaded):
        RetryingLLMClient(inner, sleep=clock.sleep).generate(REQ)
    assert len(inner.requests) == 3  # 1 try + 2 retries

    breaker_inner = FakeLLM(fail={"any": LLMQuotaExceeded("day", 300)})
    breaker = CircuitBreakerLLMClient(breaker_inner, clock)
    for _ in range(2):
        with pytest.raises(LLMQuotaExceeded):
            breaker.generate(REQ)
    assert len(breaker_inner.requests) == 1


def test_concurrency_gate():
    gate = threading.Event()

    class Slow:
        def generate(self, request):
            gate.wait(2)
            return FakeLLM().generate(request)

    limited = ConcurrencyLimitedLLMClient(Slow(), limit=1, wait_s=0.05)
    worker = threading.Thread(target=limited.generate, args=(REQ,))
    worker.start()
    with pytest.raises(LLMUnavailable):
        limited.generate(REQ)
    gate.set()
    worker.join()


# O9 / O10 — runner
def test_restart_recovery_and_approval_timeout(tmp_path):
    repo = SqliteJobRepository(str(tmp_path / "m.db"))
    running, waiting = new_job(), new_job()
    running.move_to(Phase.PLANNING)
    repo.create(running)
    waiting.move_to(Phase.PLANNING)
    waiting.move_to(Phase.AWAITING_APPROVAL)
    repo.create(waiting)

    runner = ThreadRunner(orchestrator=None, jobs=repo, max_queued=1, approval_timeout_min=30)
    runner.recover()
    assert repo.get(running.id).phase is Phase.FAILED
    assert "restart" in repo.get(running.id).errors[-1]
    assert repo.get(waiting.id).phase is Phase.AWAITING_APPROVAL

    assert runner.expire_approvals(datetime.now(UTC) + timedelta(minutes=10)) == 0
    assert runner.expire_approvals(datetime.now(UTC) + timedelta(minutes=31)) == 1
    assert repo.get(waiting.id).phase is Phase.CANCELLED


def test_queue_full(tmp_path):
    runner = ThreadRunner(None, SqliteJobRepository(str(tmp_path / "m.db")), 1, 30)
    runner.submit("a")
    with pytest.raises(QueueFull):
        runner.submit("b")
