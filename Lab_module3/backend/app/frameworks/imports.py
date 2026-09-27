"""Import and idiom detection (facts for the Analyzer, checks for the Verifier)."""

import ast
import re

_PY_IMPORT_LINE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)
_JS_MODULE = re.compile(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)|from\s+['\"]([^'\"]+)['\"]")

PY2_IDIOM_ATTRS = frozenset({"iteritems", "itervalues", "iterkeys", "has_key"})
PY2_IDIOM_NAMES = frozenset({"unicode", "xrange", "raw_input", "basestring", "long"})


def python_imports(source: str) -> set[str]:
    """Top-level module names. Works on Python 2 sources too (falls back to a regex)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {(a or b).split(".")[0] for a, b in _PY_IMPORT_LINE.findall(source)}
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    return modules


def js_modules(source: str) -> set[str]:
    return {a or b for a, b in _JS_MODULE.findall(source)}


def file_imports(path: str, source: str) -> set[str]:
    return python_imports(source) if path.endswith(".py") else js_modules(source)


def py2_idioms(source: str) -> list[str]:
    """Python 2 idioms still present in (Python 3-parsable) code."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in PY2_IDIOM_ATTRS:
            found.append(f"line {node.lineno}: .{node.attr}()")
        elif isinstance(node, ast.Name) and node.id in PY2_IDIOM_NAMES:
            found.append(f"line {node.lineno}: {node.id}")
    return found


# ---- cross-file consistency --------------------------------------------------------------


def _module_name(path: str) -> str:
    parts = path.removesuffix(".py").split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _top_level_names(body: list[ast.stmt]) -> set[str] | None:
    """Names a module defines at top level (incl. inside if/try blocks); None when it cannot
    be known statically (star import, module __getattr__)."""
    names: set[str] = set()
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
        elif isinstance(node, ast.AnnAssign | ast.AugAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            if any(a.name == "*" for a in node.names):
                return None
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.If | ast.Try | ast.With):
            blocks = [node.body, getattr(node, "orelse", []), getattr(node, "finalbody", [])]
            blocks += [h.body for h in getattr(node, "handlers", [])]
            for block in blocks:
                inner = _top_level_names(block)
                if inner is None:
                    return None
                names |= inner
    return None if "__getattr__" in names else names


def unresolved_imports(files: dict[str, str], only: set[str] | None = None) -> list[str]:
    """`from x import a` / `x.a` where x is one of the project's own files but does not
    define `a` — the cross-file mismatch a per-file linter cannot see. Checks the files in
    `only` (default: all) against every file in `files`."""
    trees: dict[str, ast.Module] = {}
    for path, source in files.items():
        if path.endswith(".py"):
            try:
                trees[path] = ast.parse(source)
            except SyntaxError:
                continue
    modules = {_module_name(p): p for p in trees}
    defined = {m: _top_level_names(trees[p].body) for m, p in modules.items()}
    problems = []
    for path, tree in trees.items():
        if only is not None and path not in only:
            continue
        package = _module_name(path).rpartition(".")[0]
        aliases: dict[str, str] = {}  # `import models as m` → {"m": "models"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parent = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
                    base = ".".join(p for p in (parent, base) if p)
                if base not in modules or defined[base] is None:
                    continue
                for alias in node.names:
                    name = alias.name
                    if name not in defined[base] and f"{base}.{name}" not in modules:
                        problems.append(
                            f"{path}:{node.lineno} imports {name!r} from {modules[base]}, "
                            f"which does not define it"
                        )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in modules:
                        aliases[alias.asname or alias.name] = alias.name
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in aliases
            ):
                module = aliases[node.value.id]
                names = defined[module]
                if names is not None and node.attr not in names:
                    problems.append(
                        f"{path}:{node.lineno} uses {node.value.id}.{node.attr}, but "
                        f"{modules[module]} does not define {node.attr!r}"
                    )
    return problems
