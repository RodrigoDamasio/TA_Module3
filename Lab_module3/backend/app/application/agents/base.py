"""Structured agent call (from Lab 2): optional tool loop → schema answer → one repair."""

import json
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.domain.errors import LLMBadResponse
from app.domain.ports import (
    AssistantMessage,
    LLMClient,
    LLMRequest,
    LLMResponse,
    Message,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
)
from app.tools.workspace import WorkspaceTools

from ..prompts import PromptLibrary

T = TypeVar("T", bound=BaseModel)
INVESTIGATE_MAX_OUTPUT = 1500
FINALIZE = (
    "Now return your final answer as JSON matching the provided schema. Output only the JSON."
)


@dataclass
class AgentCall:
    system: str
    user: str
    lenient: type[BaseModel]  # schema sent to the model
    strict: type[BaseModel]  # schema validated locally
    max_output_tokens: int
    tools: list[ToolSpec] = field(default_factory=list)
    workspace: WorkspaceTools | None = None
    max_rounds: int = 0


def _parse(response: LLMResponse) -> dict[str, Any] | None:
    if response.parsed is not None:
        return dict(response.parsed)
    try:
        value = json.loads(response.text or "")
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _errors(err: ValidationError) -> str:
    return "\n".join(
        f"- {'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in err.errors()[:10]
    )


class StructuredAgent:
    def __init__(self, prompts: PromptLibrary, thinking_budget: int) -> None:
        self.prompts = prompts
        self._thinking = thinking_budget

    def ask(self, llm: LLMClient, call: AgentCall, validate=None):
        """Returns the strict model. `validate(model)` may raise ValueError with feedback,
        which is sent back once as a repair (e.g. invalid plan, wrong file set)."""
        messages: list[Message] = [UserMessage(call.user)]
        if call.tools and call.workspace is not None and call.max_rounds > 0:
            messages = self._investigate(llm, call)

        response = self._final(llm, call, messages)
        try:
            return self._check(response, call, validate)
        except (ValidationError, ValueError) as err:
            detail = _errors(err) if isinstance(err, ValidationError) else str(err)
            messages = [
                *messages,
                AssistantMessage(response.text or "", []),
                UserMessage(self.prompts.repair(detail)),
            ]
            response = self._final(llm, call, messages)
            try:
                return self._check(response, call, validate)
            except (ValidationError, ValueError) as err2:
                raise LLMBadResponse(f"The model's answer was invalid twice: {err2}") from err2

    def _check(self, response: LLMResponse, call: AgentCall, validate):
        if response.finish_reason == "max_tokens":
            raise ValueError(
                "Your answer was cut off (too long). Return a shorter but complete answer."
            )
        data = _parse(response)
        if data is None:
            raise ValueError("The answer was not a JSON object.")
        model = call.strict.model_validate(data)
        if validate is not None:
            validate(model)
        return model

    def _final(self, llm: LLMClient, call: AgentCall, messages: list[Message]) -> LLMResponse:
        return llm.generate(
            LLMRequest(
                system=call.system,
                messages=list(messages),
                response_schema=call.lenient,
                max_output_tokens=call.max_output_tokens,
                thinking_budget=0,
            )
        )

    def _investigate(self, llm: LLMClient, call: AgentCall) -> list[Message]:
        """ReAct-style tool loop; returns a compacted conversation for the final answer."""
        messages: list[Message] = [UserMessage(call.user)]
        notes: list[str] = []
        rounds = 0
        while True:
            response = llm.generate(
                LLMRequest(
                    system=call.system,
                    messages=list(messages),
                    tools=call.tools,
                    max_output_tokens=INVESTIGATE_MAX_OUTPUT,
                    thinking_budget=self._thinking,
                )
            )
            messages.append(response.as_message())
            if response.text:
                notes.append(response.text.strip())
            if not response.tool_calls:
                break
            assert call.workspace is not None  # noqa: S101 — narrowed by the caller
            results = [call.workspace.run(c) for c in response.tool_calls]
            messages.append(ToolResultsMessage(results))
            notes += [f"Tool {r.name} returned:\n{r.content}" for r in results]
            rounds += 1
            if rounds >= call.max_rounds:
                break
        # Compacted context: task + notes, no raw tool turns (Lab 2).
        return [
            UserMessage(call.user),
            AssistantMessage("Investigation notes:\n" + ("\n\n".join(notes) or "(none)"), []),
            UserMessage(FINALIZE),
        ]
