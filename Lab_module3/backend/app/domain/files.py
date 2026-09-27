from dataclasses import dataclass
from pathlib import PurePosixPath

from .errors import InvalidPath

ALLOWED_EXTENSIONS = frozenset({".py", ".js", ".mjs", ".cjs", ".ts"})
MAX_PATH_LENGTH = 120


def validate_path(path: str) -> str:
    """Relative POSIX path inside the job's virtual workspace, or InvalidPath."""
    if not path or len(path) > MAX_PATH_LENGTH or "\\" in path or "\0" in path:
        raise InvalidPath(f"Invalid file path: {path!r}.")
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or pure.parts[0] in (".", ""):
        raise InvalidPath(f"File paths must be relative and stay inside the project: {path!r}.")
    if pure.suffix not in ALLOWED_EXTENSIONS:
        raise InvalidPath(f"Unsupported file type: {path!r}.")
    return str(pure)


@dataclass(frozen=True)
class SourceFile:
    path: str
    content: str


@dataclass
class FileVersion:
    """One write of a migrated file. Versions are never deleted — only hidden."""

    path: str
    content: str
    version: int
    step_id: int
    hidden: bool = False
