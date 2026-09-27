"""Route/import extraction and deterministic verification — 0 LLM calls."""

from pathlib import Path

import pytest

from app.domain.errors import UnsupportedMigration
from app.frameworks import routes
from app.frameworks.checks import check_python, verify
from app.frameworks.imports import js_modules, py2_idioms, python_imports
from app.frameworks.registry import PAIRS, find_pair

ROOT = Path(__file__).resolve().parents[1]


def load(folder: Path) -> dict[str, str]:
    return {str(p.relative_to(folder)): p.read_text() for p in folder.rglob("*") if p.is_file()}


def sample(name):
    return load(ROOT / "samples" / name)


def reference(name):
    return load(ROOT / "tests" / "fixtures" / name)


CASES = [
    ("flask_todo", "flask-fastapi"),
    ("express_users", "express-fastapi"),
    ("django_articles", "django-fastapi"),
    ("py2_report", "python2-python3"),
]


# F1
@pytest.mark.parametrize(
    "name, extractor, expected",
    [
        (
            "flask_todo",
            routes.flask_routes,
            {
                ("GET", "/todos"),
                ("POST", "/todos"),
                ("GET", "/todos/{todo_id}"),
                ("PUT", "/todos/{todo_id}"),
                ("DELETE", "/todos/{todo_id}"),
            },
        ),
        (
            "express_users",
            routes.express_routes,
            {
                ("GET", "/health"),
                ("POST", "/users/register"),
                ("POST", "/users/login"),
                ("GET", "/users/{email}"),
            },
        ),
        (
            "django_articles",
            routes.django_routes,
            {("ANY", "/articles"), ("ANY", "/articles/{pk}"), ("ANY", "/articles/new")},
        ),
    ],
)
def test_source_routes(name, extractor, expected):
    assert extractor(sample(name)) == expected


def test_flask_blueprints_and_method_decorators():
    files = {
        "app.py": (
            "from flask import Blueprint, Flask\n"
            "bp = Blueprint('api', __name__, url_prefix='/api')\n"
            "@bp.get('/items/<item_id>')\ndef item(item_id):\n    return ''\n"
            "app = Flask(__name__)\napp.register_blueprint(bp, url_prefix='/v2')\n"
        )
    }
    assert routes.flask_routes(files) == {("GET", "/v2/items/{item_id}")}


# F2
def test_fastapi_routes_with_router_prefix_and_include():
    assert routes.fastapi_routes(reference("express_users")) == {
        ("GET", "/health"),
        ("POST", "/users/register"),
        ("POST", "/users/login"),
        ("GET", "/users/{email}"),
    }
    files = {
        "main.py": "from fastapi import FastAPI\nfrom api import items as item_routes\n"
        "from api.orders import router as orders_router\napp = FastAPI()\n"
        "app.include_router(item_routes.router, prefix='/v1')\n"
        "app.include_router(orders_router, prefix='/v1')\n",
        "api/items.py": "from fastapi import APIRouter\nrouter = APIRouter(prefix='/items')\n"
        "@router.get('/{item_id:int}')\ndef get(item_id: int):\n    return {}\n",
        "api/orders.py": "from fastapi import APIRouter\nrouter = APIRouter()\n"
        "@router.post('/orders')\ndef create():\n    return {}\n",
    }
    assert routes.fastapi_routes(files) == {("GET", "/v1/items/{item_id}"), ("POST", "/v1/orders")}


def test_path_normalization_and_matching():
    assert routes.normalize("todos/<int:todo_id>/") == "/todos/{todo_id}"
    assert routes.normalize("/users/:email") == "/users/{email}"
    assert routes.normalize("//a//{b:path}/") == "/a/{b}"
    assert routes.missing_routes({("ANY", "/x")}, {("POST", "/x")}) == []
    assert routes.missing_routes({("GET", "/x")}, {("POST", "/x")}) == [("GET", "/x")]


# F3
@pytest.mark.parametrize("name, pair", CASES)
def test_reference_migrations_pass_every_check(name, pair):
    checks = verify(PAIRS[pair], sample(name), reference(name))
    assert all(c.passed for c in checks), [c for c in checks if not c.passed]
    assert {c.name for c in checks} >= {"compiles", "lint", "framework_migrated"}


# F4
def test_broken_migrations_fail_the_right_check():
    good = reference("flask_todo")
    pair = PAIRS["flask-fastapi"]

    def failed(files):
        return {c.name: c for c in verify(pair, sample("flask_todo"), files) if not c.passed}

    syntax = failed(good | {"main.py": good["main.py"] + "\ndef broken(:\n"})
    assert "compiles" in syntax and "main.py:" in syntax["compiles"].detail
    assert syntax["compiles"].file == "main.py"

    undefined = failed(good | {"main.py": good["main.py"] + "\nresult = jsonify({})\n"})
    assert "F821" in undefined["lint"].detail and undefined["lint"].file == "main.py"

    leftover = failed(good | {"main.py": "from flask import Flask\n" + good["main.py"]})
    assert "flask" in leftover["framework_migrated"].detail

    missing = failed(good | {"main.py": good["main.py"].split("@app.delete")[0]})
    assert "DELETE /todos/{todo_id}" in missing["routes_preserved"].detail

    assert "files_generated" in failed({})


def test_python2_idioms_are_detected():
    code = "d = {}\nfor k, v in d.iteritems():\n    x = unicode(k)\n"
    assert len(py2_idioms(code)) == 2
    checks = verify(PAIRS["python2-python3"], {}, {"a.py": code})
    assert not next(c for c in checks if c.name == "framework_migrated").passed


# F5
def test_checks_never_execute_code(tmp_path):
    marker = tmp_path / "pwned"
    evil = f"open({str(marker)!r}, 'w').write('x')\nraise SystemExit(1)\n"
    assert check_python({"evil.py": evil}) == []  # compiles fine…
    verify(PAIRS["flask-fastapi"], {}, {"evil.py": evil})
    assert not marker.exists()  # …and was never run


def test_check_python_reports_lines_for_retry_feedback():
    assert check_python({"m.py": "def f(:\n"})[0].startswith("m.py:1")
    problems = check_python({"m.py": "x = undefined_name\n"})
    assert problems and "F821" in problems[0]


def test_imports():
    assert python_imports("import os\nfrom a.b import c\nfrom . import d\n") == {"os", "a"}
    assert python_imports('print "py2"\nimport urllib2\n') == {"urllib2"}  # regex fallback
    assert js_modules("const x = require('express');\nimport y from './y'\n") == {"express", "./y"}


def test_registry():
    assert find_pair("flask", "fastapi").id == "flask-fastapi"
    assert len(PAIRS) == 4 and not PAIRS["python2-python3"].is_web
    with pytest.raises(UnsupportedMigration, match="Supported"):
        find_pair("rails", "fastapi")
