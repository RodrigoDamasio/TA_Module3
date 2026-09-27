"""Context assembly: numbered files, fact formatting, token estimates (Lab 2 approach)."""

import math

from app.frameworks.routes import Route

CHARS_PER_TOKEN = 3  # conservative for code (measured in Module 1)
SEPARATOR = "│"


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def numbered(path: str, content: str) -> str:
    lines = content.splitlines() or [""]
    body = "\n".join(f"{n:>4}{SEPARATOR} {line}" for n, line in enumerate(lines, 1))
    return f'<file path="{path}">\n{body}\n</file>'


def numbered_files(files: dict[str, str]) -> str:
    return "\n\n".join(numbered(p, c) for p, c in sorted(files.items())) or "(none)"


def format_routes(routes: set[Route]) -> str:
    return (
        "\n".join(f"- {m} {p}" for m, p in sorted(routes, key=lambda r: (r[1], r[0]))) or "- (none)"
    )


def bullet(items: list[str] | tuple[str, ...]) -> str:
    return "\n".join(f"- {i}" for i in items) or "- (none)"
