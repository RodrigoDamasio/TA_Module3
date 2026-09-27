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
    CodeTooLarge,
    LLMBadResponse,
    LLMQuotaExceeded,
    LLMRequestRejected,
    LLMTimeout,
    LLMUnavailable,
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
CODE_TOO_LARGE = ProblemType(
    "code-too-large",
    413,
    "The code is too large to analyze.",
    "The submitted code exceeds the size limit. `detail` states the limit.",
)
RATE_LIMITED = ProblemType(
    "rate-limited",
    429,
    "Too many analyses.",
    "This client sent too many analyses. Retry after the `Retry-After` delay.",
)
LLM_BAD_RESPONSE = ProblemType(
    "llm-bad-response",
    502,
    "The analysis could not be completed.",
    "The model's answer was not a valid analysis, even after one repair attempt.",
)
LLM_REQUEST_REJECTED = ProblemType(
    "llm-request-rejected",
    502,
    "The LLM provider rejected the request.",
    "The model provider refused the request (configuration or content policy).",
)
LLM_QUOTA_EXHAUSTED = ProblemType(
    "llm-quota-exhausted",
    503,
    "The analysis limit has been reached.",
    "The LLM provider's quota is used up. Retry after the `Retry-After` delay.",
)
LLM_UNAVAILABLE = ProblemType(
    "llm-unavailable",
    503,
    "The analysis service is busy or unavailable.",
    "The LLM provider is unavailable or too many analyses are in progress.",
)
LLM_TIMEOUT = ProblemType(
    "llm-timeout",
    504,
    "The analysis took too long.",
    "The LLM provider did not answer in time.",
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
        CODE_TOO_LARGE,
        RATE_LIMITED,
        LLM_BAD_RESPONSE,
        LLM_REQUEST_REJECTED,
        LLM_QUOTA_EXHAUSTED,
        LLM_UNAVAILABLE,
        LLM_TIMEOUT,
        INTERNAL_ERROR,
    )
}


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


async def _code_too_large_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, CodeTooLarge)  # noqa: S101 — narrows the type
    return problem_response(request, CODE_TOO_LARGE, detail=exc.reason)


async def _rate_limited_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RateLimited)  # noqa: S101 — narrows the type
    return problem_response(
        request, RATE_LIMITED, detail=str(exc), headers=_retry_after(exc.retry_after_s)
    )


async def _llm_handler(request: Request, exc: Exception) -> Response:
    if isinstance(exc, LLMQuotaExceeded):
        when = "tomorrow" if exc.scope == "day" and exc.retry_after_s > 3600 else "shortly"
        return problem_response(
            request,
            LLM_QUOTA_EXHAUSTED,
            detail=f"The free-tier analysis quota is used up; try again {when}.",
            headers=_retry_after(exc.retry_after_s or 60),
        )
    if isinstance(exc, LLMUnavailable):
        return problem_response(
            request, LLM_UNAVAILABLE, detail=str(exc), headers=_retry_after(exc.retry_after_s)
        )
    if isinstance(exc, LLMTimeout):
        return problem_response(request, LLM_TIMEOUT, detail=str(exc))
    if isinstance(exc, LLMRequestRejected):
        logger.warning("LLM request rejected: status=%s", exc.status)
        return problem_response(request, LLM_REQUEST_REJECTED, detail=str(exc))
    assert isinstance(exc, LLMBadResponse)  # noqa: S101 — narrows the type
    logger.warning("LLM bad response: %s", exc)
    return problem_response(request, LLM_BAD_RESPONSE, detail=str(exc))


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
    app.add_exception_handler(CodeTooLarge, _code_too_large_handler)
    app.add_exception_handler(RateLimited, _rate_limited_handler)
    for error in (LLMQuotaExceeded, LLMUnavailable, LLMTimeout, LLMRequestRejected, LLMBadResponse):
        app.add_exception_handler(error, _llm_handler)
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
