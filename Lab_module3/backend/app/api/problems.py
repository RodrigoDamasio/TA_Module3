"""RFC 9457 Problem Details: the single place where errors become HTTP responses."""

import logging
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.config import get_settings
from app.domain.errors import (
    InputTooLarge,
    InvalidPath,
    InvalidTransition,
    JobNotFound,
    LLMQuotaExceeded,
    QueueFull,
    UnsupportedMigration,
)

from .guards import RateLimited

PROBLEM_JSON = "application/problem+json"
logger = logging.getLogger(__name__)


# ---- model -----------------------------------------------------------------


class FieldError(BaseModel):
    detail: str
    pointer: str  # JSON Pointer (RFC 6901) into the request body, e.g. "#/url"


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    errors: list[FieldError] | None = None  # extension member (RFC 9457 §3.2)


# OpenAPI documentation for error responses
PROBLEM_RESPONSE: dict[str, Any] = {
    "model": Problem,
    "content": {PROBLEM_JSON: {}},
    "description": "RFC 9457 Problem Details",
}


# ---- catalog ---------------------------------------------------------------


@dataclass(frozen=True)
class ProblemType:
    slug: str
    status: int
    title: str
    description: str


VALIDATION_ERROR = ProblemType(
    "validation-error",
    422,
    "Your request is not valid.",
    "One or more fields in the request body are invalid. See `errors` for each field.",
)
MALFORMED_REQUEST = ProblemType(
    "malformed-request",
    400,
    "The request body is not valid JSON.",
    "The request body could not be parsed as JSON.",
)
JOB_NOT_FOUND = ProblemType(
    "job-not-found",
    404,
    "Migration job not found.",
    "No migration job has this id. Jobs are kept in the server's database.",
)
INVALID_TRANSITION = ProblemType(
    "invalid-transition",
    409,
    "This action is not possible in the job's current phase.",
    "Approve/reject need `awaiting_approval`; rollback needs `completed` or `failed`.",
)
INPUT_TOO_LARGE = ProblemType(
    "input-too-large",
    413,
    "The project is too large to migrate.",
    "Too many files or characters. `detail` states the limit.",
)
UNSUPPORTED_MIGRATION = ProblemType(
    "unsupported-migration",
    422,
    "This migration is not supported.",
    "The source → target pair is not supported. See GET /frameworks.",
)
RATE_LIMITED = ProblemType(
    "rate-limited",
    429,
    "Too many migrations.",
    "This client started too many migrations. Retry after the `Retry-After` delay.",
)
LLM_QUOTA_EXHAUSTED = ProblemType(
    "llm-quota-exhausted",
    503,
    "The migration limit has been reached.",
    "The LLM provider's daily quota is used up. Retry after the `Retry-After` delay.",
)
LLM_UNAVAILABLE = ProblemType(
    "llm-unavailable",
    503,
    "The migration service is busy.",
    "Too many migrations are queued. Retry after the `Retry-After` delay.",
)
WAIT_TIMEOUT = ProblemType(
    "wait-timeout",
    504,
    "The migration is still running.",
    "`?wait=true` gave up waiting. The job continues: follow `status_url` or `events_url`.",
)
INTERNAL_ERROR = ProblemType(
    "internal-error",
    500,
    "Internal server error.",
    "An unexpected error occurred. It has been logged.",
)

CATALOG = {
    p.slug: p
    for p in (
        VALIDATION_ERROR,
        MALFORMED_REQUEST,
        JOB_NOT_FOUND,
        INVALID_TRANSITION,
        INPUT_TOO_LARGE,
        UNSUPPORTED_MIGRATION,
        RATE_LIMITED,
        LLM_QUOTA_EXHAUSTED,
        LLM_UNAVAILABLE,
        WAIT_TIMEOUT,
        INTERNAL_ERROR,
    )
}


class WaitTimeout(Exception):
    def __init__(self, job_id: str, seconds: int) -> None:
        super().__init__(f"Job {job_id} did not finish within {seconds}s; it is still running.")
        self.job_id = job_id


# ---- building responses ----------------------------------------------------


def problem_response(
    request: Request,
    problem_type: ProblemType | None,
    *,
    status: int | None = None,
    detail: str | None = None,
    errors: list[FieldError] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    if problem_type is None:  # about:blank — title SHOULD be the HTTP reason phrase
        status = status or 500
        type_, title = "about:blank", HTTPStatus(status).phrase
    else:
        status = problem_type.status
        type_ = f"{get_settings().base_url}/problems/{problem_type.slug}"
        title = problem_type.title

    body = Problem(
        type=type_,
        title=title,
        status=status,
        detail=detail,
        instance=request.url.path,
        errors=errors,
    )
    return JSONResponse(
        body.model_dump(exclude_none=True),
        status_code=status,
        media_type=PROBLEM_JSON,
        headers=headers,
    )


def _json_pointer(loc: tuple[int | str, ...]) -> str:
    """("body", "url") -> "#/url" (RFC 6901, with ~ and / escaped)."""
    parts = [str(p).replace("~", "~0").replace("/", "~1") for p in loc[1:]]
    return "#/" + "/".join(parts) if parts else "#"


def _friendly_message(error: dict[str, Any]) -> str:
    kind = error.get("type", "")
    if kind == "missing":
        return "This field is required."
    if kind == "string_too_short":
        return "Must not be empty."
    if kind == "enum":
        expected = error.get("ctx", {}).get("expected", "")
        return f"Must be one of: {expected}." if expected else "Unsupported value."
    return str(error.get("msg", "Invalid value.")).removeprefix("Value error, ")


# ---- handlers --------------------------------------------------------------


async def _validation_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RequestValidationError)  # noqa: S101 — narrows the type
    errors = exc.errors()
    if any(e.get("type") == "json_invalid" for e in errors):
        return problem_response(request, MALFORMED_REQUEST)
    field_errors = [
        FieldError(detail=_friendly_message(e), pointer=_json_pointer(tuple(e["loc"])))
        for e in errors
    ]
    count = len(field_errors)
    return problem_response(
        request,
        VALIDATION_ERROR,
        detail=f"The request body has {count} invalid field{'s' if count != 1 else ''}.",
        errors=field_errors,
    )


def _retry_after(seconds: float) -> dict[str, str]:
    return {"Retry-After": str(max(1, round(seconds)))}


def _simple(problem_type: ProblemType):
    async def handler(request: Request, exc: Exception) -> Response:
        return problem_response(request, problem_type, detail=str(exc))

    return handler


async def _invalid_path_handler(request: Request, exc: Exception) -> Response:
    return problem_response(
        request,
        VALIDATION_ERROR,
        detail="The request body has 1 invalid field.",
        errors=[FieldError(detail=str(exc), pointer="#/files")],
    )


async def _wait_timeout_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, WaitTimeout)  # noqa: S101 — narrows the type
    return problem_response(
        request,
        WAIT_TIMEOUT,
        detail=str(exc),
        headers={"Location": f"/migrations/{exc.job_id}"},
    )


async def _rate_limited_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RateLimited)  # noqa: S101 — narrows the type
    return problem_response(
        request, RATE_LIMITED, detail=str(exc), headers=_retry_after(exc.retry_after_s)
    )


async def _quota_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, LLMQuotaExceeded)  # noqa: S101 — narrows the type
    when = "tomorrow" if exc.retry_after_s > 3600 else "shortly"
    return problem_response(
        request,
        LLM_QUOTA_EXHAUSTED,
        detail=f"The free-tier LLM quota is used up; try again {when}.",
        headers=_retry_after(exc.retry_after_s or 60),
    )


async def _busy_handler(request: Request, exc: Exception) -> Response:
    return problem_response(request, LLM_UNAVAILABLE, detail=str(exc), headers=_retry_after(60))


async def _http_exception_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101 — narrows the type
    phrase = HTTPStatus(exc.status_code).phrase
    detail = exc.detail if exc.detail and exc.detail != phrase else None
    return problem_response(
        request, None, status=exc.status_code, detail=detail, headers=exc.headers
    )


class UnhandledErrorMiddleware(BaseHTTPMiddleware):
    """Turns unexpected exceptions into an `internal-error` problem.

    Must be registered BEFORE CORSMiddleware so CORS wraps it and 500s keep their
    CORS headers (Starlette makes the last-added middleware the outermost).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            return await call_next(request)
        except Exception:
            logger.exception("Unhandled error on %s %s", request.method, request.url.path)
            return problem_response(
                request, INTERNAL_ERROR, detail="An unexpected error occurred. Please try again."
            )


def register_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(InvalidPath, _invalid_path_handler)
    app.add_exception_handler(JobNotFound, _simple(JOB_NOT_FOUND))
    app.add_exception_handler(InvalidTransition, _simple(INVALID_TRANSITION))
    app.add_exception_handler(InputTooLarge, _simple(INPUT_TOO_LARGE))
    app.add_exception_handler(UnsupportedMigration, _simple(UNSUPPORTED_MIGRATION))
    app.add_exception_handler(RateLimited, _rate_limited_handler)
    app.add_exception_handler(LLMQuotaExceeded, _quota_handler)
    app.add_exception_handler(QueueFull, _busy_handler)
    app.add_exception_handler(WaitTimeout, _wait_timeout_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)


# ---- problem type documentation (types SHOULD be dereferenceable) ---------

router = APIRouter(prefix="/problems", tags=["problems"])


@router.get("/{slug}", responses={404: PROBLEM_RESPONSE})
def describe_problem(slug: str) -> dict[str, str | int]:
    problem_type = CATALOG.get(slug)
    if problem_type is None:
        raise StarletteHTTPException(status_code=404)
    return {
        "type": slug,
        "title": problem_type.title,
        "status": problem_type.status,
        "description": problem_type.description,
    }
