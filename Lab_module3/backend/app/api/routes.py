"""Thin HTTP handlers: parse the request, call the use case, shape the response."""

import asyncio
import time
from collections.abc import AsyncIterable

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.sse import EventSourceResponse, ServerSentEvent
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.application.migrations import MigrationService
from app.domain.job import TERMINAL, MigrationJob
from app.frameworks.registry import PAIRS

from .dependencies import Container, get_container, get_service
from .problems import PROBLEM_RESPONSE, WaitTimeout
from .schemas import Accepted, FrameworkView, JobView, MigrateRequest, RejectRequest, job_view

router = APIRouter()
SSE_POLL_S = 0.5
WAIT_POLL_S = 0.25


def _problems(*codes: int) -> dict:
    return {code: PROBLEM_RESPONSE for code in codes}


def _view(c: Container, job: MigrationJob, include_history: bool = False) -> JobView:
    return job_view(job, c.model, c.prompts.version, include_history)


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/health")
def health(c: Container = Depends(get_container)) -> dict[str, str]:
    return {"status": "ok", "model": c.model, "llm_mode": c.settings.llm_mode}


@router.get("/frameworks")
def frameworks() -> list[FrameworkView]:
    return [
        FrameworkView(
            id=p.id,
            source=p.source,
            target=p.target,
            source_name=p.source_name,
            target_name=p.target_name,
            source_language=p.source_language,
            description=p.description,
            source_extensions=sorted(p.source_extensions),
        )
        for p in PAIRS.values()
    ]


@router.post(
    "/migrate",
    status_code=202,
    responses={200: {"model": JobView}} | _problems(400, 413, 422, 429, 503, 504),
)
def migrate(
    body: MigrateRequest,
    request: Request,
    response: Response,
    wait: bool = Query(False, description="Block until the job ends (needs no approval)."),
    c: Container = Depends(get_container),
) -> Accepted | JobView:
    if wait and body.require_approval:
        raise _field_error("#/require_approval", "Must be false when wait=true.")
    files = [(f.path, f.content) for f in body.files]
    c.service.check_input(files, body.source_framework, body.target_framework)  # free checks
    c.limiter.check(_client(request))  # only requests that would start a job count
    job = c.service.submit(
        files, body.source_framework, body.target_framework, body.require_approval
    )
    status_url = f"/migrations/{job.id}"
    response.headers["Location"] = status_url
    if wait:
        job = _wait_until_finished(c, job.id)
        response.status_code = 200
        return _view(c, job)
    return Accepted(
        job_id=job.id,
        phase=job.phase.value,
        status_url=status_url,
        events_url=f"{status_url}/events",
    )


def _field_error(pointer: str, detail: str) -> RequestValidationError:
    return RequestValidationError(
        [{"type": "value_error", "loc": ("body", *pointer[2:].split("/")), "msg": detail}]
    )


def _wait_until_finished(c: Container, job_id: str) -> MigrationJob:
    deadline = time.monotonic() + c.settings.sync_wait_timeout_s
    while True:
        job = c.jobs.get(job_id)
        if job.phase in TERMINAL:
            return job
        if time.monotonic() > deadline:
            raise WaitTimeout(job_id, c.settings.sync_wait_timeout_s)
        time.sleep(WAIT_POLL_S)


@router.get("/migrations/{job_id}", responses=_problems(404))
def get_migration(
    job_id: str,
    include_history: bool = Query(False, description="Add every file version (incl. hidden)."),
    c: Container = Depends(get_container),
) -> JobView:
    return _view(c, c.service.get(job_id), include_history)


def _existing_job(job_id: str, service: MigrationService = Depends(get_service)) -> str:
    """Checked before the stream starts, so an unknown id is a normal 404 problem."""
    return service.get(job_id).id


@router.get(
    "/migrations/{job_id}/events", response_class=EventSourceResponse, responses=_problems(404)
)
async def migration_events(
    request: Request,
    job_id: str = Depends(_existing_job),
    last_event_id: str | None = Header(None),
    c: Container = Depends(get_container),
) -> AsyncIterable[ServerSentEvent]:
    """Replays the job's events after `Last-Event-ID`, then follows new ones; ends after
    `done`. Events are read from the database, so a reconnect loses nothing."""
    after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    while True:
        events = await run_in_threadpool(c.jobs.events_since, job_id, after)
        if not events:
            job = await run_in_threadpool(c.jobs.get, job_id)
            if job.phase in TERMINAL:  # 'done' was already sent (or read just now)
                events = await run_in_threadpool(c.jobs.events_since, job_id, after)
                if not events:
                    return
        for event in events:
            after = event.id or after
            yield ServerSentEvent(data=event.data, event=event.type, id=str(event.id))
            if event.type == "done":
                return
        if await request.is_disconnected():
            return
        await asyncio.sleep(SSE_POLL_S)


@router.post("/migrations/{job_id}/approve", responses=_problems(404, 409, 503))
def approve(job_id: str, c: Container = Depends(get_container)) -> JobView:
    return _view(c, c.service.approve(job_id))


@router.post("/migrations/{job_id}/reject", responses=_problems(404, 409, 422, 503))
def reject(
    job_id: str, body: RejectRequest | None = None, c: Container = Depends(get_container)
) -> JobView:
    feedback = body.feedback.strip() if body and body.feedback else None
    return _view(c, c.service.reject(job_id, feedback or None))


@router.post("/migrations/{job_id}/rollback", responses=_problems(404, 409))
def rollback(job_id: str, c: Container = Depends(get_container)) -> JobView:
    return _view(c, c.service.rollback(job_id), include_history=True)


@router.get("/samples")
def list_samples(c: Container = Depends(get_container)) -> list[dict]:
    return c.samples.catalog()


@router.get("/samples/{sample_id}", responses=_problems(404))
def get_sample(sample_id: str, c: Container = Depends(get_container)) -> dict:
    sample = c.samples.get(sample_id)
    if sample is None:
        raise StarletteHTTPException(status_code=404, detail="Unknown sample.")
    return sample | {
        "files": c.samples.files(sample_id),
        "result": c.samples.stored_result(sample_id),
    }
