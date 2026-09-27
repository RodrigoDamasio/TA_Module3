"""Supported migrations (extension: multiple frameworks). Adding a pair = one entry here,
a guide in app/prompts/guides/, and a sample."""

from collections.abc import Callable
from dataclasses import dataclass

from app.domain.errors import UnsupportedMigration

from . import routes

RouteExtractor = Callable[[dict[str, str]], set[routes.Route]]


@dataclass(frozen=True)
class FrameworkPair:
    id: str
    source: str  # id used in requests
    target: str
    source_name: str
    target_name: str
    source_language: str
    description: str
    source_extensions: frozenset[str]
    source_routes: RouteExtractor
    forbidden_imports: frozenset[str]
    required_import: str | None
    check_py2_idioms: bool = False

    @property
    def is_web(self) -> bool:
        return self.source_routes is not routes.no_routes


PAIRS: dict[str, FrameworkPair] = {
    p.id: p
    for p in [
        FrameworkPair(
            "flask-fastapi",
            "flask",
            "fastapi",
            "Flask",
            "FastAPI",
            "python",
            "Flask app → FastAPI app (routes, request parsing, errors, blueprints).",
            frozenset({".py"}),
            routes.flask_routes,
            frozenset({"flask", "werkzeug"}),
            "fastapi",
        ),
        FrameworkPair(
            "express-fastapi",
            "express",
            "fastapi",
            "Express.js",
            "FastAPI",
            "javascript",
            "Express.js API (JavaScript) → FastAPI (Python): routers, middleware, handlers.",
            frozenset({".js", ".mjs", ".cjs", ".ts"}),
            routes.express_routes,
            frozenset({"express"}),
            "fastapi",
        ),
        FrameworkPair(
            "django-fastapi",
            "django",
            "fastapi",
            "Django",
            "FastAPI",
            "python",
            "Django function views + urls.py → FastAPI routes.",
            frozenset({".py"}),
            routes.django_routes,
            frozenset({"django"}),
            "fastapi",
        ),
        FrameworkPair(
            "python2-python3",
            "python2",
            "python3",
            "Python 2",
            "Python 3",
            "python",
            "Python 2 code → Python 3 (print, exceptions, dict methods, stdlib renames).",
            frozenset({".py"}),
            routes.no_routes,
            frozenset(
                {
                    "urllib2",
                    "ConfigParser",
                    "StringIO",
                    "cStringIO",
                    "cPickle",
                    "Queue",
                    "httplib",
                    "HTMLParser",
                    "urlparse",
                }
            ),
            None,
            check_py2_idioms=True,
        ),
    ]
}


def find_pair(source: str, target: str) -> FrameworkPair:
    pair = PAIRS.get(f"{source}-{target}")
    if pair is None:
        supported = ", ".join(f"{p.source} → {p.target}" for p in PAIRS.values())
        raise UnsupportedMigration(
            f"Unsupported migration {source} → {target}. Supported: {supported}."
        )
    return pair
