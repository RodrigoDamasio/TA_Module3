"""LLM_MODE=fake: deterministic answers for every agent — no key, no quota.

Good enough for a full job to pass the real deterministic checks: the Executor's answer is
generated from the routes listed in its prompt. Used for UI work, local E2E, and as the
base of the test fake."""

import json
import re

from app.domain.ports import LLMRequest, LLMResponse, TokenUsage, UserMessage

_ROUTE = re.compile(r"^- (GET|POST|PUT|PATCH|DELETE|ANY) (/\S*)$", re.M)
_TARGETS = re.compile(r"Write ONLY these files: (.+?)\. Return each")
_PARAM = re.compile(r"\{(\w+)\}")


def _section(text: str, header: str) -> str:
    match = re.search(rf"# {re.escape(header)}[^\n]*\n(.*?)(?:\n# |\Z)", text, re.S)
    return match.group(1) if match else ""


def fastapi_module(routes: list[tuple[str, str]]) -> str:
    lines = ["from fastapi import FastAPI", "", "app = FastAPI()"]
    for n, (method, path) in enumerate(routes, 1):
        verb = "get" if method == "ANY" else method.lower()
        params = _PARAM.findall(path)
        args = ", ".join(f"{p}: str" for p in params)
        lines += [
            "",
            "",
            f'@app.{verb}("{path}")',
            f"def handler_{n}({args}) -> dict:",
            '    return {"demo": True}',
        ]
    return "\n".join(lines) + "\n"


class DemoLLMClient:
    target_is_python3_marker = "→ Python 3 (Python 3.12)"

    def generate(self, request: LLMRequest) -> LLMResponse:
        if request.response_schema is None:  # tool-enabled investigation turn
            text = "Demo mode: no investigation needed."
            return LLMResponse(text, [], None, TokenUsage(), "stop")
        prompt = "\n".join(m.text for m in request.messages if isinstance(m, UserMessage))
        name = request.response_schema.__name__
        data = getattr(self, f"_{name}")(request, prompt)
        return LLMResponse(json.dumps(data), [], data, TokenUsage(), "stop")

    def _is_py3(self, request: LLMRequest) -> bool:
        return self.target_is_python3_marker in request.system

    def _AnalysisLLM(self, request: LLMRequest, prompt: str) -> dict:  # noqa: N802
        files = prompt.count("<file path=")
        return {
            "summary": f"Demo mode (LLM_MODE=fake): {files} file(s) analyzed without "
            "calling Gemini.",
            "components": ["demo component"],
            "dependencies": ["demo dependency"],
            "patterns": ["demo pattern"],
            "risks": [],
        }

    def _PlanLLM(self, request: LLMRequest, prompt: str) -> dict:  # noqa: N802
        sources = re.findall(r"^- (\S+)$", _section(prompt, "Source files"), re.M)
        if self._is_py3(request):
            steps = [
                {
                    "id": n,
                    "title": f"Port {path} to Python 3",
                    "description": f"Rewrite {path} with Python 3 syntax and stdlib names.",
                    "depends_on": [],
                    "complexity": "low",
                    "source_files": [path],
                    "target_files": [path],
                }
                for n, path in enumerate(sources, 1)
            ]
        else:
            steps = [
                {
                    "id": 1,
                    "title": "Create the FastAPI app",
                    "description": "Migrate every route into main.py (demo mode).",
                    "depends_on": [],
                    "complexity": "medium",
                    "source_files": sources,
                    "target_files": ["main.py"],
                }
            ]
        return {"steps": steps}

    def _StepLLM(self, request: LLMRequest, prompt: str) -> dict:  # noqa: N802
        match = _TARGETS.search(prompt)
        targets = [t.strip() for t in match.group(1).split(",")] if match else ["main.py"]
        if self._is_py3(request):
            files = [
                {
                    "path": t,
                    "content": f'"""{t} — demo migration (LLM_MODE=fake)."""\n\n\n'
                    "def main() -> None:\n    return None\n",
                }
                for t in targets
            ]
        else:
            routes = _ROUTE.findall(_section(prompt, "Routes of the whole project"))
            files = [{"path": targets[0], "content": fastapi_module(routes)}]
            files += [{"path": t, "content": '"""Demo module."""\n'} for t in targets[1:]]
        return {"files": files, "notes": "Demo mode: generated without calling Gemini."}

    def _VerificationLLM(self, request: LLMRequest, prompt: str) -> dict:  # noqa: N802
        return {"issues": [], "confidence": 8, "verdict": "pass"}
