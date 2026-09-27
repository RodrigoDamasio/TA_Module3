"""Sample projects served by /samples: source files + a stored completed job (0 LLM calls)."""

import json
from functools import cache
from pathlib import Path

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"


class SampleStore:
    def __init__(self, root: Path = SAMPLES_DIR) -> None:
        self._root = root

    @cache  # noqa: B019 — one store per process; files never change at runtime
    def catalog(self) -> list[dict]:
        entries = json.loads((self._root / "catalog.json").read_text())["samples"]
        return [
            {
                k: e[k]
                for k in ("id", "title", "source_framework", "target_framework", "description")
            }
            | {"has_result": (self._root / "results" / f"{e['id']}.json").is_file()}
            for e in entries
        ]

    def get(self, sample_id: str) -> dict | None:
        return next((s for s in self.catalog() if s["id"] == sample_id), None)

    def files(self, sample_id: str) -> list[dict[str, str]]:
        folder = self._root / sample_id
        return [
            {"path": str(p.relative_to(folder)), "content": p.read_text()}
            for p in sorted(folder.rglob("*"))
            if p.is_file()
        ]

    def stored_result(self, sample_id: str) -> dict | None:
        """A JobView exported by the evaluation harness (eval/run.py --export)."""
        path = self._root / "results" / f"{sample_id}.json"
        return json.loads(path.read_text()) if path.is_file() else None
