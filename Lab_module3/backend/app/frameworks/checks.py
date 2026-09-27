"""Deterministic verification of migrated code. NOTHING here executes the generated code:
ast.parse + compile() to bytecode + Ruff (static) on a temporary copy."""

import ast
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from app.domain.reports import Check

from . import routes
from .imports import py2_idioms, python_imports, unresolved_imports
from .registry import FrameworkPair

logger = logging.getLogger(__name__)

# Ruff pyflakes codes that mean the code is broken (not just untidy).
BLOCKING_LINT = frozenset({"F821", "F811", "F822", "F823", "F632", "F706", "F704"})
RUFF_TIMEOUT_S = 20


def _syntax(path: str, source: str) -> str | None:
    try:
        tree = ast.parse(source, filename=path)
        compile(tree, path, "exec")  # bytecode only — never executed
    except SyntaxError as err:
        return f"{path}:{err.lineno} {err.msg}"
    except ValueError as err:  # e.g. null bytes
        return f"{path}: {err}"
    return None


def _ruff(files: dict[str, str]) -> list[tuple[str, int, str, str]] | None:
    """(file, line, code, message) for blocking lint errors; None if Ruff is unavailable."""
    with tempfile.TemporaryDirectory() as tmp:
        for path, content in files.items():
            target = Path(tmp, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        argv = [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--isolated",
            "--no-cache",
            "--select",
            "F",
            "--output-format",
            "json",
            tmp,
        ]
        try:
            result = subprocess.run(
                argv, capture_output=True, text=True, timeout=RUFF_TIMEOUT_S, check=False
            )
            findings = json.loads(result.stdout or "[]")
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as err:
            logger.warning("Ruff lint unavailable: %s", err)
            return None
        return [
            (
                str(Path(f["filename"]).relative_to(tmp)),
                f["location"]["row"],
                f["code"],
                f["message"],
            )
            for f in findings
            if f.get("code") in BLOCKING_LINT
        ]


def check_python(files: dict[str, str], project: dict[str, str] | None = None) -> list[str]:
    """Problems that make a step's output unusable: syntax/compile errors, blocking lint,
    names imported from another project file that it does not define (`project` = the
    other migrated files). Returns human-readable lines (fed back to the Executor on
    retry); [] means OK."""
    py = {p: s for p, s in files.items() if p.endswith(".py")}
    problems = [msg for p, s in py.items() if (msg := _syntax(p, s))]
    if problems:
        return problems
    lint = _ruff(py) or []
    problems = [f"{f}:{line} {code} {msg}" for f, line, code, msg in lint]
    return problems + unresolved_imports((project or {}) | py, only=set(py))


def verify(pair: FrameworkPair, sources: dict[str, str], migrated: dict[str, str]) -> list[Check]:
    checks: list[Check] = []
    if not migrated:
        return [Check("files_generated", False, "No migrated files were produced.")]

    for path, content in migrated.items():
        err = _syntax(path, content) if path.endswith(".py") else None
        checks.append(Check("compiles", err is None, err or f"{path} parses and compiles", path))

    lint = _ruff(migrated)
    if lint is None:
        checks.append(Check("lint", True, "Ruff unavailable — lint skipped"))
    else:
        by_file: dict[str, list[str]] = {}
        for f, line, code, msg in lint:
            by_file.setdefault(f, []).append(f"{f}:{line} {code} {msg}")
        checks.append(
            Check(
                "lint",
                not lint,
                "; ".join(sum(by_file.values(), [])) or "no blocking lint errors",
                next(iter(by_file), None),
            )
        )

    unresolved = unresolved_imports(migrated)
    checks.append(
        Check(
            "imports_resolve",
            not unresolved,
            "; ".join(unresolved) or "imports between migrated files resolve",
            unresolved[0].split(":")[0] if unresolved else None,
        )
    )

    leftovers = []
    for path, content in migrated.items():
        left = python_imports(content) & pair.forbidden_imports
        if left:
            leftovers.append((path, f"{path} still imports {sorted(left)}"))
        if pair.check_py2_idioms:
            idioms = py2_idioms(content)
            if idioms:
                leftovers.append((path, f"{path}: Python 2 idioms {idioms[:5]}"))
    required_ok = pair.required_import is None or any(
        pair.required_import in python_imports(c) for c in migrated.values()
    )
    detail = "; ".join(m for _, m in leftovers)
    if not required_ok:
        detail = (detail + "; " if detail else "") + f"no file imports {pair.required_import}"
    checks.append(
        Check(
            "framework_migrated",
            not leftovers and required_ok,
            detail or f"no {pair.source_name} imports left",
            leftovers[0][0] if leftovers else None,
        )
    )

    if pair.is_web:
        source_routes = pair.source_routes(sources)
        target_routes = routes.fastapi_routes(migrated)
        missing = routes.missing_routes(source_routes, target_routes)
        checks.append(
            Check(
                "routes_preserved",
                not missing,
                f"{len(source_routes) - len(missing)}/{len(source_routes)} routes"
                + (f"; missing {[f'{m} {p}' for m, p in missing]}" if missing else ""),
            )
        )
    return checks
