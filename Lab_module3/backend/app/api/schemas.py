"""HTTP request/response models. JobView is the lab's JSON output (BACKEND_PLAN §10.3)."""

from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, Field

from app.domain.job import MigrationJob, plan_to_dict, verification_to_dict


class FileIn(BaseModel):
    path: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1)


class MigrateRequest(BaseModel):
    files: list[FileIn] = Field(min_length=1)
    source_framework: str = Field(min_length=1, max_length=40)
    target_framework: str = Field(min_length=1, max_length=40)
    require_approval: bool = True


class RejectRequest(BaseModel):
    feedback: str | None = Field(default=None, max_length=2000)


class Accepted(BaseModel):
    job_id: str
    phase: str
    status_url: str
    events_url: str


class FrameworkView(BaseModel):
    id: str
    source: str
    target: str
    source_name: str
    target_name: str
    source_language: str
    description: str
    source_extensions: list[str]


class FileOut(BaseModel):
    path: str
    content: str


class MigratedFile(FileOut):
    language: str
    step_id: int
    version: int


class FileVersionOut(MigratedFile):
    hidden: bool


class Tokens(BaseModel):
    input: int
    output: int


class Meta(BaseModel):
    model: str
    prompt_version: str
    llm_calls: int
    cached_calls: int
    replans: int
    tokens: Tokens
    started_at: str
    updated_at: str
    finished_at: str | None
    approval_requested_at: str | None


class JobView(BaseModel):
    job_id: str
    pair: str
    phase: str
    success: bool
    require_approval: bool
    migrated_files: list[MigratedFile]
    source_files: list[FileOut]
    analysis: dict[str, Any] | None
    plan: dict[str, Any] | None
    verification: dict[str, Any] | None
    errors: list[str]
    history: list[FileVersionOut] | None = None  # every version, incl. hidden ones
    meta: Meta


def _language(path: str) -> str:
    return "python" if path.endswith(".py") else "javascript"


def job_view(
    job: MigrationJob, model: str, prompt_version: str, include_history: bool = False
) -> JobView:
    migrated = []
    for path in job.current_files():
        v = job.latest_version(path)
        assert v is not None  # noqa: S101 — current_files only lists visible versions
        migrated.append(
            MigratedFile(
                path=v.path,
                content=v.content,
                language=_language(v.path),
                step_id=v.step_id,
                version=v.version,
            )
        )
    history = None
    if include_history:
        history = [
            FileVersionOut(
                path=v.path,
                content=v.content,
                language=_language(v.path),
                step_id=v.step_id,
                version=v.version,
                hidden=v.hidden,
            )
            for v in job.versions
        ]
    return JobView(
        job_id=job.id,
        pair=job.pair,
        phase=job.phase.value,
        success=job.success,
        require_approval=job.require_approval,
        migrated_files=migrated,
        source_files=[FileOut(path=s.path, content=s.content) for s in job.sources],
        analysis=asdict(job.analysis) if job.analysis else None,
        plan=plan_to_dict(job.plan) if job.plan else None,
        verification=verification_to_dict(job.verification) if job.verification else None,
        errors=job.errors,
        history=history,
        meta=Meta(
            model=model,
            prompt_version=prompt_version,
            llm_calls=job.llm_calls,
            cached_calls=job.cached_calls,
            replans=job.replans,
            tokens=Tokens(input=job.tokens_in, output=job.tokens_out),
            started_at=job.created_at,
            updated_at=job.updated_at,
            finished_at=job.finished_at,
            approval_requested_at=job.approval_requested_at,
        ),
    )
