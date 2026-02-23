"""Unified LLM Client error hierarchy."""

from __future__ import annotations

from typing import Any


class SDKError(Exception):
    def __init__(self, message: str, *, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


class ProviderError(SDKError):
    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        error_code: str | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
        raw: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(message, cause=cause)
        self.provider = provider
        self.status_code = status_code
        self.error_code = error_code
        self.retryable = retryable
        self.retry_after = retry_after
        self.raw = raw


class AuthenticationError(ProviderError):
    def __init__(self, **kwargs: Any):
        kwargs.setdefault("retryable", False)
        super().__init__(**kwargs)


class AccessDeniedError(ProviderError):
    def __init__(self, **kwargs: Any):
        kwargs.setdefault("retryable", False)
        super().__init__(**kwargs)


class NotFoundError(ProviderError):
    def __init__(self, **kwargs: Any):
        kwargs.setdefault("retryable", False)
        super().__init__(**kwargs)


class InvalidRequestError(ProviderError):
    def __init__(self, **kwargs: Any):
        kwargs.setdefault("retryable", False)
        super().__init__(**kwargs)


class RateLimitError(ProviderError):
    def __init__(self, **kwargs: Any):
        kwargs.setdefault("retryable", True)
        super().__init__(**kwargs)


class ServerError(ProviderError):
    def __init__(self, **kwargs: Any):
        kwargs.setdefault("retryable", True)
        super().__init__(**kwargs)


class ContentFilterError(ProviderError):
    def __init__(self, **kwargs: Any):
        kwargs.setdefault("retryable", False)
        super().__init__(**kwargs)


class ContextLengthError(ProviderError):
    def __init__(self, **kwargs: Any):
        kwargs.setdefault("retryable", False)
        super().__init__(**kwargs)


class QuotaExceededError(ProviderError):
    def __init__(self, **kwargs: Any):
        kwargs.setdefault("retryable", False)
        super().__init__(**kwargs)


class RequestTimeoutError(SDKError):
    retryable: bool = True


class AbortError(SDKError):
    retryable: bool = False


class NetworkError(SDKError):
    retryable: bool = True


class StreamError(SDKError):
    retryable: bool = True


class InvalidToolCallError(SDKError):
    retryable: bool = False


class NoObjectGeneratedError(SDKError):
    retryable: bool = False


class ConfigurationError(SDKError):
    retryable: bool = False


# Maps HTTP status codes to error classes
STATUS_CODE_MAP: dict[int, type[ProviderError]] = {
    400: InvalidRequestError,
    401: AuthenticationError,
    403: AccessDeniedError,
    404: NotFoundError,
    408: RateLimitError,
    413: ContextLengthError,
    422: InvalidRequestError,
    429: RateLimitError,
    500: ServerError,
    502: ServerError,
    503: ServerError,
    504: ServerError,
}


def error_from_status(
    status_code: int,
    message: str,
    *,
    provider: str,
    raw: dict[str, Any] | None = None,
    retry_after: float | None = None,
) -> ProviderError:
    """Create the appropriate error type from an HTTP status code."""
    cls = STATUS_CODE_MAP.get(status_code, ServerError)
    return cls(
        message=message,
        provider=provider,
        status_code=status_code,
        raw=raw,
        retry_after=retry_after,
    )
