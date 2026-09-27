"""Deterministic route extraction (facts for the agents and the 'routes preserved' check).

A route is (METHOD, normalized path). Paths from every framework are normalized to the
FastAPI style, so they can be compared: <int:id> / :id / {id:int} -> {id}.
"""

import ast
import posixpath
import re

Route = tuple[str, str]
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

_FLASK_PARAM = re.compile(r"<(?:[a-zA-Z_]+:)?([a-zA-Z_]\w*)>")
_EXPRESS_PARAM = re.compile(r"(?<=/):([a-zA-Z_]\w*)|^:([a-zA-Z_]\w*)")
_FASTAPI_PARAM = re.compile(r"\{([a-zA-Z_]\w*)(?::[^}]*)?\}")


def normalize(path: str) -> str:
    path = _FASTAPI_PARAM.sub(r"{\1}", path)  # first: {id:int} contains a ':'
    path = _FLASK_PARAM.sub(r"{\1}", path)
    path = _EXPRESS_PARAM.sub(lambda m: "{" + (m.group(1) or m.group(2)) + "}", path)
    path = "/" + path.strip("/")
    return re.sub(r"/{2,}", "/", path)


def join(prefix: str, path: str) -> str:
    return normalize(f"{prefix}/{path}")


def _parse(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _const_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _kwarg(call: ast.Call, name: str) -> ast.AST | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _stem(path: str) -> str:
    return posixpath.splitext(posixpath.basename(path))[0]


# ---- Flask ----------------------------------------------------------------------


def flask_routes(files: dict[str, str]) -> set[Route]:
    prefixes: dict[str, str] = {}  # blueprint variable -> url_prefix
    trees = {p: t for p, s in files.items() if p.endswith(".py") and (t := _parse(s))}
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                func = node.value.func
                if isinstance(func, ast.Name) and func.id == "Blueprint":
                    prefix = _const_str(_kwarg(node.value, "url_prefix")) or ""
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            prefixes[target.id] = prefix
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "register_blueprint"
                and node.args
                and isinstance(node.args[0], ast.Name)
            ):
                prefix = _const_str(_kwarg(node, "url_prefix"))
                if prefix is not None:
                    prefixes[node.args[0].id] = prefix
    routes: set[Route] = set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for deco in node.decorator_list:
                if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)):
                    continue
                owner = deco.func.value.id if isinstance(deco.func.value, ast.Name) else ""
                path = _const_str(deco.args[0]) if deco.args else None
                if path is None:
                    continue
                if deco.func.attr == "route":
                    methods_node = _kwarg(deco, "methods")
                    methods = ["GET"]
                    if isinstance(methods_node, ast.List | ast.Tuple):
                        methods = [m for e in methods_node.elts if (m := _const_str(e))]
                elif deco.func.attr in HTTP_METHODS:
                    methods = [deco.func.attr]
                else:
                    continue
                for method in methods:
                    routes.add((method.upper(), join(prefixes.get(owner, ""), path)))
    return routes


# ---- FastAPI (target) ---------------------------------------------------------------


def fastapi_routes(files: dict[str, str]) -> set[Route]:
    own_prefix: dict[tuple[str, str], str] = {}  # (module stem, var) -> APIRouter prefix
    include_prefix: dict[tuple[str, str], str] = {}  # (module stem | "", var) -> mount prefix
    decorated: list[tuple[str, str, str, str]] = []  # (stem, var, method, path)
    for path, source in files.items():
        tree = _parse(source) if path.endswith(".py") else None
        if tree is None:
            continue
        stem = _stem(path)
        aliases: dict[str, tuple[str, str]] = {}  # local name -> (module stem, var)
        modules: dict[str, str] = {}  # local module alias -> module stem
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    aliases[alias.asname or alias.name] = (node.module.split(".")[-1], alias.name)
                    modules[alias.asname or alias.name] = alias.name  # `from api import items`
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules[alias.asname or alias.name] = alias.name.split(".")[-1]
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                func = node.value.func
                if isinstance(func, ast.Name) and func.id == "APIRouter":
                    prefix = _const_str(_kwarg(node.value, "prefix")) or ""
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            own_prefix[(stem, target.id)] = prefix
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "include_router"
                and node.args
            ):
                prefix = _const_str(_kwarg(node, "prefix")) or ""
                target = node.args[0]
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                    module = modules.get(target.value.id, target.value.id)
                    include_prefix[(module, target.attr)] = prefix
                elif isinstance(target, ast.Name):
                    include_prefix[aliases.get(target.id, ("", target.id))] = prefix
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for deco in node.decorator_list:
                    if (
                        isinstance(deco, ast.Call)
                        and isinstance(deco.func, ast.Attribute)
                        and deco.func.attr in HTTP_METHODS
                        and isinstance(deco.func.value, ast.Name)
                        and deco.args
                        and (route_path := _const_str(deco.args[0])) is not None
                    ):
                        decorated.append((stem, deco.func.value.id, deco.func.attr, route_path))
    routes: set[Route] = set()
    for stem, var, method, route_path in decorated:
        mount = include_prefix.get((stem, var), include_prefix.get(("", var), ""))
        prefix = join(mount, own_prefix.get((stem, var), ""))
        routes.add((method.upper(), join(prefix, route_path)))
    return routes


# ---- Express ------------------------------------------------------------------------

_EXPRESS_ROUTE = re.compile(r"\b(\w+)\.(get|post|put|patch|delete|all)\(\s*(['\"`])([^'\"`]+)\3")
_REQUIRE = re.compile(
    r"(?:const|let|var)\s+(\w+)\s*=\s*require\(\s*['\"](\.{1,2}/[^'\"]+)['\"]\s*\)"
)
_IMPORT = re.compile(r"import\s+(\w+)\s+from\s+['\"](\.{1,2}/[^'\"]+)['\"]")
_MOUNT = re.compile(r"\b\w+\.use\(\s*(['\"`])([^'\"`]+)\1\s*,\s*(\w+)\s*\)")


def _resolve(from_file: str, spec: str, files: dict[str, str]) -> str | None:
    base = posixpath.normpath(posixpath.join(posixpath.dirname(from_file), spec))
    for candidate in (
        base,
        *(base + ext for ext in (".js", ".ts", ".mjs", ".cjs")),
        f"{base}/index.js",
    ):
        if candidate in files:
            return candidate
    return None


def express_routes(files: dict[str, str]) -> set[Route]:
    mounted: dict[str, str] = {}  # file -> prefix
    for path, source in files.items():
        modules = {
            name: _resolve(path, spec, files)
            for name, spec in _REQUIRE.findall(source) + _IMPORT.findall(source)
        }
        for _, prefix, var in _MOUNT.findall(source):
            if (target := modules.get(var)) is not None:
                mounted[target] = prefix
    routes: set[Route] = set()
    for path, source in files.items():
        for _, method, _, route_path in _EXPRESS_ROUTE.findall(source):
            verb = "ANY" if method == "all" else method.upper()
            routes.add((verb, join(mounted.get(path, ""), route_path)))
    return routes


# ---- Django -------------------------------------------------------------------------


def django_routes(files: dict[str, str]) -> set[Route]:
    routes: set[Route] = set()
    for path, source in files.items():
        tree = _parse(source) if path.endswith(".py") else None
        for node in ast.walk(tree) if tree else []:
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("path", "re_path")
                and node.args
                and (route_path := _const_str(node.args[0])) is not None
            ):
                routes.add(("ANY", normalize(route_path)))  # Django URLs don't fix a method
    return routes


def no_routes(files: dict[str, str]) -> set[Route]:
    return set()


def missing_routes(source: set[Route], target: set[Route]) -> list[Route]:
    """Source routes absent from the target. 'ANY' matches any method on the same path."""
    missing = []
    for method, path in sorted(source):
        if method == "ANY":
            found = any(p == path for _, p in target)
        else:
            found = (method, path) in target or ("ANY", path) in target
        if not found:
            missing.append((method, path))
    return missing
