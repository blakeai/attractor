"""Tests for the LLM error hierarchy."""

from attractor.llm.errors import (
    AuthenticationError,
    ConfigurationError,
    InvalidRequestError,
    NetworkError,
    RateLimitError,
    SDKError,
    ServerError,
    error_from_status,
)


class TestErrorHierarchy:
    def test_sdk_error_is_exception(self):
        err = SDKError("test")
        assert isinstance(err, Exception)
        assert str(err) == "test"

    def test_authentication_not_retryable(self):
        err = AuthenticationError(message="bad key", provider="anthropic", status_code=401)
        assert err.retryable is False

    def test_rate_limit_retryable(self):
        err = RateLimitError(
            message="too fast", provider="anthropic", status_code=429, retry_after=5.0
        )
        assert err.retryable is True
        assert err.retry_after == 5.0

    def test_server_error_retryable(self):
        err = ServerError(message="internal", provider="anthropic", status_code=500)
        assert err.retryable is True

    def test_network_error_retryable(self):
        err = NetworkError("connection lost")
        assert err.retryable is True

    def test_configuration_error_not_retryable(self):
        err = ConfigurationError("no provider")
        assert err.retryable is False


class TestErrorFromStatus:
    def test_400_invalid_request(self):
        err = error_from_status(400, "bad request", provider="anthropic")
        assert isinstance(err, InvalidRequestError)
        assert err.retryable is False

    def test_401_authentication(self):
        err = error_from_status(401, "unauthorized", provider="anthropic")
        assert isinstance(err, AuthenticationError)

    def test_429_rate_limit(self):
        err = error_from_status(429, "rate limited", provider="anthropic", retry_after=10.0)
        assert isinstance(err, RateLimitError)
        assert err.retry_after == 10.0

    def test_500_server_error(self):
        err = error_from_status(500, "internal", provider="anthropic")
        assert isinstance(err, ServerError)
        assert err.retryable is True

    def test_unknown_status_defaults_to_server_error(self):
        err = error_from_status(418, "teapot", provider="anthropic")
        assert isinstance(err, ServerError)
