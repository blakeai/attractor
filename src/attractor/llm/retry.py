"""Retry logic with exponential backoff and jitter."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from attractor.llm.errors import SDKError


@dataclass
class RetryPolicy:
    max_retries: int = 2
    base_delay: float = 1.0
    max_delay: float = 60.0
    backoff_multiplier: float = 2.0
    jitter: bool = True
    on_retry: Callable[[Exception, int, float], Any] | None = None

    def delay_for_attempt(self, attempt: int) -> float:
        delay = min(self.base_delay * (self.backoff_multiplier**attempt), self.max_delay)
        if self.jitter:
            delay *= random.uniform(0.5, 1.5)
        return delay


DEFAULT_POLICY = RetryPolicy()


def _is_retryable(error: Exception) -> bool:
    if isinstance(error, SDKError):
        return getattr(error, "retryable", True)
    return False


async def retry[T](
    fn: Callable[[], Awaitable[T]],
    policy: RetryPolicy = DEFAULT_POLICY,
) -> T:
    """Execute an async function with retries on transient errors."""
    last_error: Exception | None = None

    for attempt in range(policy.max_retries + 1):
        try:
            return await fn()
        except Exception as e:
            last_error = e
            if attempt >= policy.max_retries or not _is_retryable(e):
                raise

            retry_after = getattr(e, "retry_after", None)
            if retry_after is not None and retry_after > policy.max_delay:
                raise

            delay = retry_after if retry_after is not None else policy.delay_for_attempt(attempt)

            if policy.on_retry:
                policy.on_retry(e, attempt, delay)

            await asyncio.sleep(delay)

    raise last_error  # type: ignore[misc]
