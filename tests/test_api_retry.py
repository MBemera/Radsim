"""Tests for API client retry logic."""

import pytest

from radsim.api_client import (
    RetryableError,
    calculate_backoff_delay,
    is_retryable_error,
    with_retry,
)


class TestCalculateBackoffDelay:
    """Tests for exponential backoff calculation."""

    def test_first_attempt_delay(self):
        """First attempt should use base delay."""
        delay = calculate_backoff_delay(0, base_delay=1.0, jitter=False)
        assert delay == 1.0

    def test_exponential_growth(self):
        """Delays should grow exponentially."""
        delays = [
            calculate_backoff_delay(i, base_delay=1.0, jitter=False)
            for i in range(5)
        ]
        # 1, 2, 4, 8, 16
        assert delays == [1.0, 2.0, 4.0, 8.0, 16.0]

    def test_max_delay_cap(self):
        """Delay should be capped at max_delay."""
        delay = calculate_backoff_delay(
            10, base_delay=1.0, max_delay=30.0, jitter=False
        )
        assert delay == 30.0  # 2^10 = 1024, but capped at 30

    def test_jitter_adds_randomness(self):
        """Jitter should add 0-50% random variance."""
        delays = [
            calculate_backoff_delay(0, base_delay=1.0, jitter=True)
            for _ in range(100)
        ]
        # All delays should be between 1.0 and 1.5 (base + 50%)
        assert all(1.0 <= d <= 1.5 for d in delays)
        # Should have some variance (not all identical)
        assert len(set(delays)) > 1


class TestIsRetryableError:
    """Tests for error classification."""

    def test_rate_limit_errors(self):
        """Rate limit errors should be retryable."""
        rate_limit_messages = [
            "rate_limit_exceeded",
            "Too Many Requests",
            "Error 429: quota exceeded",
            "Request throttled",
        ]
        for msg in rate_limit_messages:
            is_retryable, is_rate_limit = is_retryable_error(Exception(msg))
            assert is_retryable is True, f"Should be retryable: {msg}"
            assert is_rate_limit is True, f"Should be rate limit: {msg}"

    def test_connection_errors(self):
        """Connection errors should be retryable but not rate limits."""
        is_retryable, is_rate_limit = is_retryable_error(
            ConnectionError("Connection refused")
        )
        assert is_retryable is True
        assert is_rate_limit is False

    def test_timeout_errors(self):
        """Timeout errors should be retryable."""
        is_retryable, is_rate_limit = is_retryable_error(
            TimeoutError("Request timed out")
        )
        assert is_retryable is True
        assert is_rate_limit is False

    def test_server_errors(self):
        """Server errors (5xx) should be retryable."""
        server_error_messages = [
            "500 Internal Server Error",
            "502 Bad Gateway",
            "503 Service Unavailable",
            "Server temporarily unavailable",
            "Service overloaded",
        ]
        for msg in server_error_messages:
            is_retryable, _ = is_retryable_error(Exception(msg))
            assert is_retryable is True, f"Should be retryable: {msg}"

    def test_non_retryable_errors(self):
        """Client errors should not be retryable."""
        non_retryable_messages = [
            "Invalid API key",
            "Authentication failed",
            "Bad request: missing parameter",
            "Invalid model specified",
        ]
        for msg in non_retryable_messages:
            is_retryable, _ = is_retryable_error(Exception(msg))
            assert is_retryable is False, f"Should NOT be retryable: {msg}"


class TestRetryableError:
    """Tests for RetryableError wrapper."""

    def test_wraps_original_error(self):
        """RetryableError should wrap original error."""
        original = ValueError("Original error")
        wrapped = RetryableError(original, is_rate_limit=False)

        assert wrapped.original_error is original
        assert wrapped.is_rate_limit is False
        assert str(wrapped) == str(original)

    def test_rate_limit_flag(self):
        """RetryableError should track rate limit status."""
        wrapped = RetryableError(Exception("429"), is_rate_limit=True)
        assert wrapped.is_rate_limit is True


class TestWithRetryDecorator:
    """Tests for the @with_retry decorator."""

    def test_success_no_retry(self):
        """Successful call should not retry."""
        call_count = 0

        @with_retry(max_retries=3)
        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_func()
        assert result == "success"
        assert call_count == 1

    def test_retry_on_retryable_error(self):
        """Should retry on RetryableError."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)  # Fast for testing
        def failing_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RetryableError(Exception("Temporary failure"))
            return "success"

        result = failing_then_success()
        assert result == "success"
        assert call_count == 3

    def test_max_retries_exceeded(self):
        """Should raise after max retries exceeded."""
        call_count = 0

        @with_retry(max_retries=2, base_delay=0.01)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise RetryableError(Exception("Always fails"))

        with pytest.raises(RetryableError):
            always_fails()

        assert call_count == 3  # Initial + 2 retries

    def test_non_retryable_error_propagates(self):
        """Non-retryable errors should propagate immediately."""
        call_count = 0

        @with_retry(max_retries=3)
        def raises_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("Not retryable")

        with pytest.raises(ValueError):
            raises_value_error()

        assert call_count == 1  # No retries
