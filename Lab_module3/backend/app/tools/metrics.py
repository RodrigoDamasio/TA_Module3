"""Deterministic code metrics with lizard (Python, JavaScript, TypeScript, Java, Go)."""

from dataclasses import dataclass

import lizard

from app.domain.models import Language

_FILENAMES = {
    Language.PYTHON: "code.py",
    Language.JAVASCRIPT: "code.js",
    Language.TYPESCRIPT: "code.ts",
    Language.JAVA: "Code.java",
    Language.GO: "code.go",
}


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    start: int
    end: int
    complexity: int  # cyclomatic complexity (CCN)


def analyze_functions(code: str, language: Language, line_offset: int = 0) -> list[FunctionInfo]:
    info = lizard.analyze_file.analyze_source_code(_FILENAMES[language], code)
    return [
        FunctionInfo(
            f.name, f.start_line + line_offset, f.end_line + line_offset, f.cyclomatic_complexity
        )
        for f in info.function_list
    ]


def complexity_hint(max_ccn: int) -> str:
    if max_ccn <= 5:
        return "low"
    return "medium" if max_ccn <= 10 else "high"


def code_metrics(code: str, language: Language, line_offset: int = 0) -> dict[str, object]:
    functions = analyze_functions(code, language, line_offset)
    ccns = [f.complexity for f in functions] or [1]
    return {
        "lines_of_code": sum(1 for line in code.splitlines() if line.strip()),
        "functions": len(functions),
        "max_complexity": max(ccns),
        "avg_complexity": round(sum(ccns) / len(ccns), 1),
        "complexity_hint": complexity_hint(max(ccns)),
        "per_function": [
            {"name": f.name, "lines": f"{f.start}-{f.end}", "complexity": f.complexity}
            for f in sorted(functions, key=lambda f: -f.complexity)
        ],
    }
