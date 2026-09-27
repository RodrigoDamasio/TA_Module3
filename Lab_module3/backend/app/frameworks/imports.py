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
