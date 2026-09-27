"""Layering and security guards (S1), as in Labs 1–2."""

import ast
import logging
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
WEB_AND_IO = {"fastapi", "starlette", "google", "sqlite3", "lizard", "httpx", "subprocess"}


def imported_modules(path: Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def offenders(layer: str, forbidden: set[str]) -> set[str]:
    return {
        f"{p.relative_to(APP)} imports {m}"
        for p in (APP / layer).rglob("*.py")
        for m in imported_modules(p)
        if any(m == f or m.startswith(f + ".") for f in forbidden)
    }


def test_domain_imports_only_stdlib_and_pydantic():
    inner = {"app.application", "app.infrastructure", "app.api", "app.frameworks", "app.tools"}
    assert offenders("domain", WEB_AND_IO | inner) == set()


def test_application_and_frameworks_never_touch_web_or_storage():
    outer = {"app.infrastructure", "app.api"}
    assert offenders("application", WEB_AND_IO | outer) == set()
    assert offenders("frameworks", (WEB_AND_IO - {"subprocess"}) | outer) == set()


def test_libraries_stay_in_their_modules():
    where: dict[str, set[str]] = {
        lib: set() for lib in ("google", "sqlite3", "lizard", "subprocess")
    }
    for path in APP.rglob("*.py"):
        for module in imported_modules(path):
            for lib in where:
                if module == lib or module.startswith(lib + "."):
                    where[lib].add(str(path.relative_to(APP)))
    assert where == {
        "google": {"infrastructure/gemini_client.py"},
        "sqlite3": {"infrastructure/database.py"},
        "lizard": {"tools/metrics.py"},
        "subprocess": {"frameworks/checks.py"},
    }


def test_sql_lives_only_in_the_sqlite_adapters():
    sql_words = ("SELECT ", "INSERT ", "UPDATE ", "DELETE FROM")
    files = {
        str(p.relative_to(APP))
        for p in APP.rglob("*.py")
        if any(w in p.read_text() for w in sql_words)
    }
    assert files <= {"infrastructure/database.py", "infrastructure/sqlite_store.py"}


def test_ruff_flags_sql_built_from_strings(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def f(c, x):\n    return c.execute(f\"SELECT * FROM t WHERE a = '{x}'\")\n")
    result = subprocess.run(  # noqa: S603 — fixed argv
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--select", "S608", str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0 and "S608" in result.stdout


def test_logs_never_contain_code_or_key(api, caplog, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-never-used")
    private_code = "TOP_SECRET_ALGORITHM = 42\n"
    a = api()
    body = {
        "files": [{"path": "app.py", "content": "from flask import Flask\n" + private_code}],
        "source_framework": "flask",
        "target_framework": "fastapi",
        "require_approval": False,
    }
    with caplog.at_level(logging.DEBUG):
        a.client.post("/migrate?wait=true", json=body)
    assert "submitted pair=flask-fastapi files=1" in caplog.text
    assert "TOP_SECRET_ALGORITHM" not in caplog.text
    assert "test-key-never-used" not in caplog.text
