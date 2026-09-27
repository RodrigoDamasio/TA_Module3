"""Prompt library (app/prompts) — the Lab 2 loader, extended to four agents."""

import re
from functools import cache
from pathlib import Path

from app.frameworks.registry import FrameworkPair

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
AGENTS = ("analyzer", "planner", "executor", "verifier")

# Every placeholder used by the prompt files; none may survive assembly.
PLACEHOLDERS = frozenset(
    {
        "persona", "source_name", "source_language", "target_name", "guide",
        "max_tool_rounds", "routes", "imports", "metrics", "numbered_files",
        "source_files", "analysis", "pair", "episodes", "feedback", "max_steps",
        "example_pair", "plan_example", "step_id", "step_count", "step_title",
        "step_description", "numbered_sources", "current_targets", "target_files",
        "retry_block", "checks", "plan", "numbered_migrated", "validation_errors",
        "check_errors", "migrated_dependencies",
    }
)  # fmt: skip


def fill(template: str, **values: object) -> str:
    """Replace only the given {placeholders}; other braces (JSON, paths) stay as they are."""
    return _PLACEHOLDER.sub(
        lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template
    )


class PromptLibrary:
    def __init__(self, root: Path = PROMPTS_DIR) -> None:
        self._root = root

    @cache  # noqa: B019 — one library per process; files never change at runtime
    def _read(self, name: str) -> str:
        return (self._root / name).read_text().strip()

    @property
    def version(self) -> str:
        return self._read("VERSION")

    def system(self, agent: str, pair: FrameworkPair) -> str:
        names = {
            "source_name": pair.source_name,
            "source_language": pair.source_language,
            "target_name": pair.target_name,
        }
        persona = fill(self._read(f"agents/{agent}.md"), **names)
        return fill(
            self._read("base.md"),
            persona=persona,
            guide=self._read(f"guides/{pair.id}.md"),
            **names,
        )

    def task(self, agent: str, **values: object) -> str:
        return fill(self._read(f"tasks/{agent}_task.md"), **values)

    def plan_example(self) -> str:
        return self._read("examples/plan_example.md")

    def repair(self, validation_errors: str) -> str:
        return fill(self._read("repair.md"), validation_errors=validation_errors)

    def step_retry(self, check_errors: str) -> str:
        return fill(self._read("step_retry.md"), check_errors=check_errors)
