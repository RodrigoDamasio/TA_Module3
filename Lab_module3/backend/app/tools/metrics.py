"""Deterministic code metrics with lizard (from Lab 2, keyed by file extension)."""

import posixpath
from dataclasses import dataclass

import lizard


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    start: int
    end: int
    complexity: int  # cyclomatic complexity (CCN)


def analyze_functions(path: str, code: str) -> list[FunctionInfo]:
    name = "code" + (posixpath.splitext(path)[1] or ".py")
    info = lizard.analyze_file.analyze_source_code(name, code)
    return [
        FunctionInfo(f.name, f.start_line, f.end_line, f.cyclomatic_complexity)
        for f in info.function_list
    ]


def code_metrics(path: str, code: str) -> dict[str, object]:
    functions = analyze_functions(path, code)
    ccns = [f.complexity for f in functions] or [1]
    return {
        "file": path,
        "lines_of_code": sum(1 for line in code.splitlines() if line.strip()),
        "functions": len(functions),
        "max_complexity": max(ccns),
        "per_function": [
            {"name": f.name, "lines": f"{f.start}-{f.end}", "complexity": f.complexity}
            for f in sorted(functions, key=lambda f: -f.complexity)[:10]
        ],
    }
