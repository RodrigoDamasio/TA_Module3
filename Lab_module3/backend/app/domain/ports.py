"""Provider-neutral abstractions (LLM types from Lab 2) and storage ports."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from .job import JobEvent, MigrationJob

FinishReason = Literal["stop", "max_tokens", "safety", "other"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass(frozen=True)
class ToolCall:
    id: str | None
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call_id: str | None
    name: str
    content: str


@dataclass(frozen=True)
class TokenUsage:
    input: int = 0
    output: int = 0
    thinking: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            self.input + other.input, self.output + other.output, self.thinking + other.thinking
        )


@dataclass(frozen=True)
class UserMessage:
    text: str


@dataclass(frozen=True)
class AssistantMessage:
    text: str | None
    tool_calls: list[ToolCall]
    raw_turn: Any = None  # provider turn, echoed back unchanged in the next request


@dataclass(frozen=True)
class ToolResultsMessage:
    results: list[ToolResult]


Message = UserMessage | AssistantMessage | ToolResultsMessage


@dataclass(frozen=True)
class LLMRequest:
    system: str
    messages: list[Message]
    tools: list[ToolSpec] = field(default_factory=list)
    response_schema: type[BaseModel] | None = None
    max_output_tokens: int = 2048
    thinking_budget: int | None = None


@dataclass(frozen=True)
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall]
    parsed: dict[str, Any] | None
    usage: TokenUsage
    finish_reason: FinishReason
    raw_turn: Any = None
    cached: bool = False  # served by CachingLLMClient (0 real calls)

    def as_message(self) -> AssistantMessage:
        return AssistantMessage(self.text, self.tool_calls, self.raw_turn)


class LLMClient(Protocol):
    def generate(self, request: LLMRequest) -> LLMResponse: ...


# ---- storage ------------------------------------------------------------------


class JobRepository(Protocol):
    def create(self, job: "MigrationJob") -> None: ...

    def save(self, job: "MigrationJob") -> None:
        """Persist the job state and its pending events atomically."""
        ...

    def get(self, job_id: str) -> "MigrationJob": ...

    def events_since(self, job_id: str, after_id: int) -> list["JobEvent"]: ...

    def jobs_in_phases(self, phases: set[str]) -> list["MigrationJob"]: ...


@dataclass(frozen=True)
class Episode:
    pair: str
    outcome: str  # success | failure
    steps: list[str]
    errors: list[str]
    learning: str


class EpisodeStore(Protocol):
    def record(self, episode: Episode) -> None: ...

    def recent(self, pair: str, limit: int) -> list[Episode]: ...


class MemoryStore(Protocol):
    """Long-term memory hook — Module 4 adds retrieval (RAG) behind this port."""

    def recall(self, query: str, limit: int) -> list[str]: ...


class JobRunner(Protocol):
    """Runs jobs outside the request (a background worker, or inline in tests)."""

    def submit(self, job_id: str) -> None: ...

    def has_capacity(self) -> bool: ...
