"""Named failures. Mapped to RFC 9457 problems only in app.api."""

from typing import Literal


class DomainError(Exception):
    """Base class for every expected failure."""


# ---- input / workflow ----------------------------------------------------------


class InvalidPath(DomainError):
    pass


class InputTooLarge(DomainError):
    pass


class UnsupportedMigration(DomainError):
    pass


class JobNotFound(DomainError):
    def __init__(self, job_id: str) -> None:
        super().__init__(f"No migration job with id '{job_id}'.")
        self.job_id = job_id


class InvalidTransition(DomainError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"Cannot go from '{current}' to '{target}'.")
        self.current = current
        self.target = target


class InvalidPlan(DomainError):
    pass


class BudgetExceeded(DomainError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"The job reached its limit of {limit} LLM calls.")
        self.limit = limit


class QueueFull(DomainError):
    def __init__(self) -> None:
        super().__init__("Too many migrations are waiting; try again in a minute.")


# ---- LLM provider (from Lab 2) ---------------------------------------------------


class LLMError(DomainError):
    """Base class for failures talking to the LLM provider."""


class LLMQuotaExceeded(LLMError):
    def __init__(self, scope: Literal["minute", "day"], retry_after_s: float) -> None:
        super().__init__(f"LLM quota exceeded ({scope}); retry after {retry_after_s:.0f}s.")
        self.scope = scope
        self.retry_after_s = retry_after_s


class LLMUnavailable(LLMError):
    def __init__(self, reason: str, retry_after_s: float = 10) -> None:
        super().__init__(reason)
        self.retry_after_s = retry_after_s


class LLMOverloaded(LLMUnavailable):
    """The provider is temporarily overloaded (HTTP 5xx) — worth a short retry."""


class LLMTimeout(LLMError):
    pass


class LLMRequestRejected(LLMError):
    """The provider refused the request (bad key, invalid request, blocked content)."""

    def __init__(self, status: int | None, reason: str) -> None:
        super().__init__(reason)
        self.status = status


class LLMBadResponse(LLMError):
    """The model's answer could not be turned into a valid result."""
