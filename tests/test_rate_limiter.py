"""Tests for rate limiting and protection mechanisms."""

import pytest

from radsim.rate_limiter import (
    BudgetExceeded,
    BudgetGuard,
    CircuitBreaker,
    CircuitBreakerOpen,
    ProtectionManager,
    RateLimiter,
    RateLimitExceeded,
)


class TestRateLimiter:
    """Tests for the RateLimiter class."""

    def test_allows_normal_usage(self):
        """Normal usage within limits should work."""
        limiter = RateLimiter(max_calls_per_turn=10, cooldown_ms=0)

        # Should allow several calls without issue
        for _ in range(5):
            limiter.check()
            # No warning until 80% (8 calls)

        assert limiter.calls_this_turn == 5

    def test_warns_at_threshold(self):
        """Should warn when approaching limit (now at 60%)."""
        limiter = RateLimiter(max_calls_per_turn=10, cooldown_ms=0, warn_threshold=0.6)

        # Make 5 calls (no warning yet - under 60%)
        for _ in range(5):
            warning = limiter.check()
            assert warning is None

        # 6th call should trigger info warning (60%)
        warning = limiter.check()
        assert warning is not None
        assert "Approaching" in warning

    def test_blocks_at_limit(self):
        """Should raise exception when limit exceeded."""
        limiter = RateLimiter(max_calls_per_turn=5, cooldown_ms=0)

        # Make calls up to limit
        for _ in range(4):
            limiter.check()

        # 5th call should raise
        with pytest.raises(RateLimitExceeded) as exc_info:
            limiter.check()

        assert "Rate limit exceeded" in str(exc_info.value)
        assert "5 API calls" in str(exc_info.value)

    def test_reset_clears_count(self):
        """Reset should clear the call count."""
        limiter = RateLimiter(max_calls_per_turn=5, cooldown_ms=0)

        for _ in range(3):
            limiter.check()

        assert limiter.calls_this_turn == 3

        limiter.reset()
        assert limiter.calls_this_turn == 0


class TestCircuitBreaker:
    """Tests for the CircuitBreaker class."""

    def test_allows_initial_errors(self):
        """Should allow errors up to threshold."""
        breaker = CircuitBreaker(threshold=3)

        # First 2 errors should be fine
        breaker.record_error("api_error")
        breaker.record_error("api_error")

        # No exception yet

    def test_trips_at_threshold(self):
        """Should trip after threshold errors."""
        breaker = CircuitBreaker(threshold=3)

        breaker.record_error("api_error")
        breaker.record_error("api_error")

        with pytest.raises(CircuitBreakerOpen) as exc_info:
            breaker.record_error("api_error")

        assert "Circuit breaker tripped" in str(exc_info.value)
        assert "3 consecutive" in str(exc_info.value)

    def test_success_resets_count(self):
        """Success should reset error count."""
        breaker = CircuitBreaker(threshold=3)

        breaker.record_error("api_error")
        breaker.record_error("api_error")
        breaker.record_success("api_error")

        # Should be able to have 2 more errors now
        breaker.record_error("api_error")
        breaker.record_error("api_error")
        # Would trip on 3rd

    def test_tracks_different_error_types(self):
        """Different error types tracked separately."""
        breaker = CircuitBreaker(threshold=3)

        breaker.record_error("api_error")
        breaker.record_error("api_error")
        breaker.record_error("tool_error")  # Different type
        breaker.record_error("tool_error")

        # api_error has 2, tool_error has 2 - neither at threshold yet


class TestBudgetGuard:
    """Tests for the BudgetGuard class."""

    def test_allows_normal_usage(self):
        """Normal usage within budget should work."""
        guard = BudgetGuard(max_input_tokens=10000, max_output_tokens=5000)

        warning = guard.record_usage(input_tokens=1000, output_tokens=500)
        assert warning is None

        assert guard.input_tokens == 1000
        assert guard.output_tokens == 500

    def test_warns_at_threshold(self):
        """Should warn when approaching budget limit."""
        guard = BudgetGuard(max_input_tokens=10000, max_output_tokens=5000, warn_threshold=0.8)

        # Use 79% - no warning
        guard.record_usage(input_tokens=7900, output_tokens=0)

        # Use more to hit 80%
        warning = guard.record_usage(input_tokens=100, output_tokens=0)
        assert warning is not None
        assert "80%" in warning

    def test_blocks_at_limit(self):
        """Should raise when budget exceeded."""
        guard = BudgetGuard(max_input_tokens=1000, max_output_tokens=500)

        guard.record_usage(input_tokens=900, output_tokens=0)

        with pytest.raises(BudgetExceeded) as exc_info:
            guard.record_usage(input_tokens=200, output_tokens=0)

        assert "budget exceeded" in str(exc_info.value).lower()

    def test_tracks_cumulative_usage(self):
        """Should track cumulative token usage."""
        guard = BudgetGuard(max_input_tokens=10000, max_output_tokens=5000)

        guard.record_usage(input_tokens=100, output_tokens=50)
        guard.record_usage(input_tokens=200, output_tokens=100)
        guard.record_usage(input_tokens=300, output_tokens=150)

        assert guard.input_tokens == 600
        assert guard.output_tokens == 300


class TestProtectionManager:
    """Tests for the ProtectionManager unified interface."""

    def test_check_before_api_call(self):
        """Should check rate limiter."""
        manager = ProtectionManager()

        # Should not raise for first calls
        for _ in range(5):
            manager.check_before_api_call()

    def test_on_user_input_resets_limiter(self):
        """User input should reset rate limiter."""
        manager = ProtectionManager()

        # Make some calls
        for _ in range(10):
            manager.check_before_api_call()

        # Reset on user input
        manager.on_user_input()

        # Should be able to make more calls
        for _ in range(10):
            manager.check_before_api_call()

    def test_record_api_success_tracks_tokens(self):
        """Should track tokens on success."""
        manager = ProtectionManager()

        manager.record_api_success(input_tokens=1000, output_tokens=500)

        assert manager.budget_guard.input_tokens == 1000
        assert manager.budget_guard.output_tokens == 500
