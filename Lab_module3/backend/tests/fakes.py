"""Test doubles: a configurable fake LLM (built on the demo client) and in-memory stores."""

import copy
import json
import threading
import time
from collections import defaultdict

from app.domain.job import JobEvent, MigrationJob, job_from_dict, job_to_dict
from app.domain.ports import Episode, LLMRequest, LLMResponse, TokenUsage, ToolCall
from app.infrastructure.demo_llm import DemoLLMClient

USAGE = TokenUsage(input=100, output=50)


class FakeLLM(DemoLLMClient):
    """Demo answers by default; every agent's answer can be overridden per test.

    plan:          list of step dicts for the Planner
    plan_sequence: list of plans consumed in order (None = demo plan)
    step_files:    {target_path: content | callable(prompt) -> content} for the Executor
    step_sequence: {target_path: [content, content, ...]} consumed in order (retries)
    invalid_once:  schema names whose FIRST answer is invalid JSON (tests repair)
    fail:          {schema name | "any": exception} raised when that schema is requested
    tool_first:    the first tool-enabled turn returns a tool call
    step_delay:    seconds each Executor call sleeps (parallelism tests)
    confidence:    Verifier confidence
    """

    def __init__(self, **options) -> None:
        self.plan = options.get("plan")
        self.plan_sequence = list(options.get("plan_sequence", []))
        self.step_files = options.get("step_files", {})
        self.step_sequence = {k: list(v) for k, v in options.get("step_sequence", {}).items()}
        self.invalid_once = set(options.get("invalid_once", ()))
        self.fail = dict(options.get("fail", {}))
        self.tool_first = options.get("tool_first", False)
        self.step_delay = options.get("step_delay", 0.0)
        self.confidence = options.get("confidence", 8)
        self.requests: list[LLMRequest] = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def generate(self, request: LLMRequest) -> LLMResponse:
        with self._lock:
            self.requests.append(request)
        name = request.response_schema.__name__ if request.response_schema else "tools"
        error = self.fail.get(name) or self.fail.get("any")
        if error is not None:
            raise error
        if name == "tools" and self.tool_first:
            self.tool_first = False
            return LLMResponse(
                None, [ToolCall("t1", "find_text", {"text": "route"})], None, USAGE, "stop"
            )
        if name in self.invalid_once:
            self.invalid_once.discard(name)
            return LLMResponse("Sure! Here is the answer...", [], None, USAGE, "stop")
        response = super().generate(request)
        return LLMResponse(response.text, [], response.parsed, USAGE, "stop")

    def _PlanLLM(self, request, prompt):  # noqa: N802
        plan = self.plan_sequence.pop(0) if self.plan_sequence else self.plan
        return {"steps": copy.deepcopy(plan)} if plan else super()._PlanLLM(request, prompt)

    def _StepLLM(self, request, prompt):  # noqa: N802
        demo = super()._StepLLM(request, prompt)
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.step_delay)
            files = []
            for f in demo["files"]:
                path = f["path"]
                if self.step_sequence.get(path):
                    content = self.step_sequence[path].pop(0)
                elif path in self.step_files:
                    value = self.step_files[path]
                    content = value(prompt) if callable(value) else value
                else:
                    content = f["content"]
                files.append({"path": path, "content": content})
            return {"files": files, "notes": demo["notes"]}
        finally:
            with self._lock:
                self.active -= 1

    def _VerificationLLM(self, request, prompt):  # noqa: N802
        return {
            "issues": []
            if self.confidence >= 7
            else [{"severity": "medium", "file": "main.py", "line": 1, "message": "Needs review"}],
            "confidence": self.confidence,
            "verdict": "pass" if self.confidence >= 7 else "fail",
        }

    def calls(self, schema: str) -> int:
        return sum(
            1
            for r in self.requests
            if (r.response_schema.__name__ if r.response_schema else "tools") == schema
        )


class MemoryJobs:
    """In-memory JobRepository (stores JSON copies, like SQLite would)."""

    def __init__(self) -> None:
        self.state: dict[str, dict] = {}
        self.events: list[tuple[str, JobEvent]] = []
        self._lock = threading.Lock()

    def create(self, job: MigrationJob) -> None:
        self.save(job)

    def save(self, job: MigrationJob) -> None:
        with self._lock:
            self.state[job.id] = json.loads(json.dumps(job_to_dict(job)))
            for event in job.pop_events():
                event.id = len(self.events) + 1
                self.events.append((job.id, event))

    def get(self, job_id: str) -> MigrationJob:
        from app.domain.errors import JobNotFound

        if job_id not in self.state:
            raise JobNotFound(job_id)
        return job_from_dict(copy.deepcopy(self.state[job_id]))

    def events_since(self, job_id: str, after_id: int) -> list[JobEvent]:
        return [e for j, e in self.events if j == job_id and e.id > after_id]

    def jobs_in_phases(self, phases: set[str]) -> list[MigrationJob]:
        return [self.get(i) for i, s in self.state.items() if s["phase"] in phases]

    def event_types(self, job_id: str) -> list[str]:
        return [e.type for j, e in self.events if j == job_id]

    def phases(self, job_id: str) -> list[str]:
        return [e.data["phase"] for j, e in self.events if j == job_id and e.type == "phase"]


class MemoryEpisodes:
    def __init__(self) -> None:
        self.items: dict[str, list[Episode]] = defaultdict(list)

    def record(self, episode: Episode) -> None:
        self.items[episode.pair].append(episode)

    def recent(self, pair: str, limit: int) -> list[Episode]:
        return list(reversed(self.items[pair]))[:limit]
