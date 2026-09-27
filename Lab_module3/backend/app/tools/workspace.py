"""Agent tools over the job's virtual workspace (files live in memory/DB, never on disk)."""

import json

from app.domain.ports import ToolCall, ToolResult, ToolSpec
from app.frameworks.imports import file_imports
from app.frameworks.registry import FrameworkPair

from .metrics import code_metrics

MAX_RESULT_CHARS = 2000
MAX_READ_LINES = 40
MAX_FIND_HITS = 20
_TRUNCATED = "\n... [truncated to fit the context budget]"

READ_FILE = ToolSpec(
    "read_file",
    "Re-read a numbered line range of one file (at most 40 lines). Returns an error message "
    "if the file does not exist.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path exactly as listed"},
            "start": {"type": "integer", "description": "First line (default 1)"},
            "end": {"type": "integer", "description": "Last line (default start + 39)"},
        },
        "required": ["path"],
    },
)
FIND_TEXT = ToolSpec(
    "find_text",
    "Find every line containing a plain text (case-insensitive, not a regex) across all "
    "files, e.g. 'jsonify' or 'req.body'. Returns path:line: content.",
    {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
)
LIST_ROUTES = ToolSpec(
    "list_routes",
    "List the HTTP routes (method + normalized path) found in the files.",
    {"type": "object", "properties": {}},
)
LIST_IMPORTS = ToolSpec(
    "list_imports", "List the modules each file imports.", {"type": "object", "properties": {}}
)
CODE_METRICS = ToolSpec(
    "get_code_metrics",
    "Lines of code and cyclomatic complexity per function for one file.",
    {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
)

ANALYZER_TOOLS = [READ_FILE, FIND_TEXT, LIST_ROUTES, LIST_IMPORTS, CODE_METRICS]
EXECUTOR_TOOLS = [READ_FILE, FIND_TEXT]
VERIFIER_TOOLS = [READ_FILE, LIST_ROUTES]


def trim(text: str) -> str:
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[: MAX_RESULT_CHARS - len(_TRUNCATED)] + _TRUNCATED


class WorkspaceTools:
    def __init__(self, files: dict[str, str], route_lister) -> None:
        self._files = files
        self._routes = route_lister  # callable(files) -> set[Route]

    @classmethod
    def for_sources(cls, files: dict[str, str], pair: FrameworkPair) -> "WorkspaceTools":
        return cls(files, pair.source_routes)

    def run(self, call: ToolCall) -> ToolResult:
        try:
            content = self._dispatch(call.name, call.args)
        except (KeyError, TypeError, ValueError) as err:
            content = f"Error: invalid arguments for {call.name}: {err}"
        return ToolResult(call.id, call.name, trim(content))

    def _dispatch(self, name: str, args: dict) -> str:
        if name == "read_file":
            path = str(args["path"])
            if path not in self._files:
                return f"Error: no file {path!r}. Files: {', '.join(sorted(self._files))}"
            lines = self._files[path].splitlines()
            start = max(1, int(args.get("start") or 1))
            end = min(
                len(lines),
                int(args.get("end") or start + MAX_READ_LINES - 1),
                start + MAX_READ_LINES - 1,
            )
            return "\n".join(f"{n:>4}│ {lines[n - 1]}" for n in range(start, end + 1)) or "(empty)"
        if name == "find_text":
            needle = str(args["text"]).strip().lower()
            if not needle or len(needle) > 80:
                return "Search text must be 1-80 characters."
            hits = [
                f"{path}:{n}: {line.strip()}"
                for path, content in sorted(self._files.items())
                for n, line in enumerate(content.splitlines(), 1)
                if needle in line.lower()
            ]
            return "\n".join(hits[:MAX_FIND_HITS]) or f"No occurrences of {args['text']!r}."
        if name == "list_routes":
            routes = sorted(self._routes(self._files), key=lambda r: (r[1], r[0]))
            return "\n".join(f"{m} {p}" for m, p in routes) or "(no routes)"
        if name == "list_imports":
            return json.dumps({p: sorted(file_imports(p, c)) for p, c in self._files.items()})
        if name == "get_code_metrics":
            path = str(args["path"])
            if path not in self._files:
                return f"Error: no file {path!r}."
            return json.dumps(code_metrics(path, self._files[path]))
        return f"Error: unknown tool {name!r}."
