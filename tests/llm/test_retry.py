"""Tests for retry logic."""

import pytest

from attractor.llm.errors import AuthenticationError, RateLimitError
from attractor.llm.retry import RetryPolicy, retry


class TestRetryPolicy:
    def test_delay_calculation(self):
        policy = RetryPolicy(base_delay=1.0, backoff_multiplier=2.0, jitter=False)
        assert policy.delay_for_attempt(0) == 1.0
        assert policy.delay_for_attempt(1) == 2.0
        assert policy.delay_for_attempt(2) == 4.0

    def test_delay_capped_at_max(self):
        policy = RetryPolicy(base_delay=1.0, backoff_multiplier=2.0, max_delay=5.0, jitter=False)
        assert policy.delay_for_attempt(10) == 5.0

    def test_jitter_varies_delay(self):
        policy = RetryPolicy(base_delay=1.0, jitter=True)
        delays = {policy.delay_for_attempt(0) for _ in range(20)}
        # With jitter, we should get different values
        assert len(delays) > 1


class TestRetry:
    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry(fn, RetryPolicy(max_retries=2))
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_retryable_error(self):
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RateLimitError(
                    message="rate limited", provider="test", status_code=429
                )
            return "ok"

        result = await retry(fn, RetryPolicy(max_retries=3, base_delay=0.01, jitter=False))
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable(self):
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            raise AuthenticationError(
                message="bad key", provider="test", status_code=401
            )

        with pytest.raises(AuthenticationError):
            await retry(fn, RetryPolicy(max_retries=3, base_delay=0.01))
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            raise RateLimitError(
                message="rate limited", provider="test", status_code=429
            )

        with pytest.raises(RateLimitError):
            await retry(fn, RetryPolicy(max_retries=2, base_delay=0.01, jitter=False))
        assert call_count == 3  # initial + 2 retries

    @pytest.mark.asyncio
    async def test_on_retry_callback(self):
        retries = []

        async def fn():
            if len(retries) < 1:
                raise RateLimitError(
                    message="rate limited", provider="test", status_code=429
                )
            return "ok"

        policy = RetryPolicy(
            max_retries=2,
            base_delay=0.01,
            jitter=False,
            on_retry=lambda e, attempt, delay: retries.append((attempt, delay)),
        )
        result = await retry(fn, policy)
        assert result == "ok"
        assert len(retries) == 1
