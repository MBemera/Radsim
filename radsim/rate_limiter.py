"""Rate limiting and loop protection for RadSim Agent.

Provides three layers of protection:
1. RateLimiter - Prevents infinite loops by limiting API calls per turn
2. CircuitBreaker - Stops on repeated errors of the same type
3. BudgetGuard - Enforces token/cost limits per session
"""

import time
from dataclasses import dataclass, field


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    pass


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open due to repeated errors."""

    pass


class BudgetExceeded(Exception):
    """Raised when token/cost budget is exceeded."""

    pass


@dataclass
class RateLimiter:
    """Limits API calls per conversation turn to prevent infinite loops.

    Tracks consecutive API calls without user input. Applies strict limits only
    for failed calls and loop detection, while allowing more calls for successful work.
    """

    max_calls_per_turn: int = 50  # Higher limit for successful calls
    max_failures_per_turn: int = 5  # Strict limit for consecutive failures
    cooldown_ms: int = 100
    warn_threshold: float = 0.7  # Warn at 70% of limit

    # Internal state
    _calls_this_turn: int = field(default=0, init=False)
    _failures_this_turn: int = field(default=0, init=False)
    _last_call_time: float = field(default=0.0, init=False)
    _warned: bool = field(default=False, init=False)

    def check(self) -> str | None:
        """Check if another API call is allowed.

        Returns:
            Warning message if approaching limit, None otherwise.

        Raises:
            RateLimitExceeded: If limit is reached.
        """
        # Enforce cooldown
        now = time.time()
        time_since_last = (now - self._last_call_time) * 1000  # ms
        if self._last_call_time > 0 and time_since_last < self.cooldown_ms:
            time.sleep((self.cooldown_ms - time_since_last) / 1000)

        self._calls_this_turn += 1
        self._last_call_time = time.time()

        # Check total call limit (for very long tasks)
        if self._calls_this_turn >= self.max_calls_per_turn:
            raise RateLimitExceeded(
                f"Rate limit exceeded: {self._calls_this_turn} API calls this turn. "
                f"Maximum is {self.max_calls_per_turn}. "
                "Please try a simpler request or break your task into smaller steps."
            )

        # Warn if approaching limit
        warn_at = int(self.max_calls_per_turn * self.warn_threshold)
        if self._calls_this_turn >= warn_at and not self._warned:
            self._warned = True
            return (
                f"ℹ️  Approaching rate limit: {self._calls_this_turn}/{self.max_calls_per_turn} "
                f"API calls this turn."
            )

        return None

    def record_failure(self) -> None:
        """Record a failed API call. Raises if too many consecutive failures.

        Raises:
            RateLimitExceeded: If consecutive failure limit reached.
        """
        self._failures_this_turn += 1
        if self._failures_this_turn >= self.max_failures_per_turn:
            raise RateLimitExceeded(
                f"Too many consecutive failures: {self._failures_this_turn} failed API calls. "
                f"Maximum is {self.max_failures_per_turn}. "
                "This prevents infinite error loops. Check your request or API key."
            )

    def record_success(self) -> None:
        """Record a successful API call. Resets failure counter."""
        self._failures_this_turn = 0

    def reset(self):
        """Reset counter after user input."""
        self._calls_this_turn = 0
        self._failures_this_turn = 0
        self._warned = False

    def get_status(self) -> dict:
        """Get current rate limit status for display.

        Returns:
            Dict with calls, max, percentage, and remaining.
        """
        return {
            "calls": self._calls_this_turn,
            "max": self.max_calls_per_turn,
            "failures": self._failures_this_turn,
            "percentage": (self._calls_this_turn / self.max_calls_per_turn) * 100 if self.max_calls_per_turn > 0 else 0,
            "remaining": self.max_calls_per_turn - self._calls_this_turn,
        }

    @property
    def calls_this_turn(self) -> int:
        """Get current call count."""
        return self._calls_this_turn


@dataclass
class CircuitBreaker:
    """Stops execution after repeated errors of the same type.

    Prevents hammering failed endpoints or getting stuck in error loops.
    """

    threshold: int = 3  # Errors before circuit opens
    cooldown_seconds: float = 60.0  # Cooldown before retry allowed

    # Internal state
    _error_counts: dict = field(default_factory=dict, init=False)
    _circuit_opened_at: dict = field(default_factory=dict, init=False)

    def record_error(self, error_type: str) -> None:
        """Record an error occurrence.

        Args:
            error_type: Type/category of the error (e.g., "api_error", "tool_failed")

        Raises:
            CircuitBreakerOpen: If error threshold is reached.
        """
        self._error_counts[error_type] = self._error_counts.get(error_type, 0) + 1

        if self._error_counts[error_type] >= self.threshold:
            self._circuit_opened_at[error_type] = time.time()
            raise CircuitBreakerOpen(
                f"Circuit breaker tripped: {self._error_counts[error_type]} consecutive "
                f"'{error_type}' errors. Stopping to prevent further issues. "
                f"Wait {self.cooldown_seconds}s or try a different approach."
            )

    def record_success(self, error_type: str = None) -> None:
        """Record a successful operation, resetting error count.

        Args:
            error_type: Specific error type to reset, or None to reset all.
        """
        if error_type:
            self._error_counts[error_type] = 0
        else:
            self._error_counts.clear()

    def is_open(self, error_type: str) -> bool:
        """Check if circuit is currently open for an error type."""
        if error_type not in self._circuit_opened_at:
            return False

        elapsed = time.time() - self._circuit_opened_at[error_type]
        if elapsed >= self.cooldown_seconds:
            # Cooldown passed, reset
            del self._circuit_opened_at[error_type]
            self._error_counts[error_type] = 0
            return False

        return True

    def reset(self):
        """Reset all circuit breaker state."""
        self._error_counts.clear()
        self._circuit_opened_at.clear()


@dataclass
class BudgetGuard:
    """Enforces token/cost limits per session.

    Tracks cumulative token usage and warns/stops at thresholds.
    """

    max_input_tokens: int = 500_000
    max_output_tokens: int = 100_000
    warn_threshold: float = 0.8  # Warn at 80%

    # Internal state
    _input_tokens: int = field(default=0, init=False)
    _output_tokens: int = field(default=0, init=False)
    _input_warned: bool = field(default=False, init=False)
    _output_warned: bool = field(default=False, init=False)

    def record_usage(self, input_tokens: int = 0, output_tokens: int = 0) -> str | None:
        """Record token usage and check limits.

        Args:
            input_tokens: Number of input tokens used.
            output_tokens: Number of output tokens used.

        Returns:
            Warning message if approaching limit, None otherwise.

        Raises:
            BudgetExceeded: If budget limit is reached.
        """
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens

        warnings = []

        # Check input limit (0 = unlimited)
        if self.max_input_tokens > 0 and self._input_tokens >= self.max_input_tokens:
            raise BudgetExceeded(
                f"Input token budget exceeded: {self._input_tokens:,} tokens used. "
                f"Maximum is {self.max_input_tokens:,}. "
                "Use '/reset budget' to reset or set max_session_input_tokens=0 for unlimited."
            )

        # Check output limit (0 = unlimited)
        if self.max_output_tokens > 0 and self._output_tokens >= self.max_output_tokens:
            raise BudgetExceeded(
                f"Output token budget exceeded: {self._output_tokens:,} tokens used. "
                f"Maximum is {self.max_output_tokens:,}. "
                "Use '/reset budget' to reset or set max_session_output_tokens=0 for unlimited."
            )

        # Warn if approaching input limit (skip if unlimited)
        if self.max_input_tokens > 0:
            input_warn_at = int(self.max_input_tokens * self.warn_threshold)
            if self._input_tokens >= input_warn_at and not self._input_warned:
                self._input_warned = True
                pct = (self._input_tokens / self.max_input_tokens) * 100
                warnings.append(f"⚠️  Input token usage at {pct:.0f}%")

        # Warn if approaching output limit (skip if unlimited)
        if self.max_output_tokens > 0:
            output_warn_at = int(self.max_output_tokens * self.warn_threshold)
            if self._output_tokens >= output_warn_at and not self._output_warned:
                self._output_warned = True
                pct = (self._output_tokens / self.max_output_tokens) * 100
                warnings.append(f"⚠️  Output token usage at {pct:.0f}%")

        return " | ".join(warnings) if warnings else None

    @property
    def input_tokens(self) -> int:
        """Get current input token count."""
        return self._input_tokens

    @property
    def output_tokens(self) -> int:
        """Get current output token count."""
        return self._output_tokens

    @property
    def input_percentage(self) -> float:
        """Get input usage as percentage (0 if unlimited)."""
        if self.max_input_tokens <= 0:
            return 0
        return (self._input_tokens / self.max_input_tokens) * 100

    @property
    def output_percentage(self) -> float:
        """Get output usage as percentage (0 if unlimited)."""
        if self.max_output_tokens <= 0:
            return 0
        return (self._output_tokens / self.max_output_tokens) * 100

    def reset(self):
        """Reset all budget tracking."""
        self._input_tokens = 0
        self._output_tokens = 0
        self._input_warned = False
        self._output_warned = False


@dataclass
class ProtectionManager:
    """Unified manager for all protection mechanisms.

    Combines RateLimiter, CircuitBreaker, and BudgetGuard into a single
    interface for the agent to use.
    """

    rate_limiter: RateLimiter = field(default_factory=RateLimiter)
    circuit_breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    budget_guard: BudgetGuard = field(default_factory=BudgetGuard)

    def check_before_api_call(self) -> str | None:
        """Check all protections before making an API call.

        Returns:
            Warning message if any, None otherwise.

        Raises:
            RateLimitExceeded, CircuitBreakerOpen: If limits exceeded.
        """
        return self.rate_limiter.check()

    def record_api_success(self, input_tokens: int = 0, output_tokens: int = 0) -> str | None:
        """Record a successful API call.

        Args:
            input_tokens: Tokens used for input.
            output_tokens: Tokens used for output.

        Returns:
            Warning message if approaching limits, None otherwise.
        """
        self.rate_limiter.record_success()  # Reset failure counter
        self.circuit_breaker.record_success("api_error")
        return self.budget_guard.record_usage(input_tokens, output_tokens)

    def record_api_error(self, error_type: str = "api_error") -> None:
        """Record an API error.

        Raises:
            CircuitBreakerOpen, RateLimitExceeded: If error threshold reached.
        """
        self.rate_limiter.record_failure()  # Track consecutive failures
        self.circuit_breaker.record_error(error_type)

    def on_user_input(self):
        """Reset per-turn counters when user provides new input."""
        self.rate_limiter.reset()
        self.circuit_breaker.reset()

    def reset_all(self):
        """Reset all protection state (new session)."""
        self.rate_limiter.reset()
        self.circuit_breaker.reset()
        self.budget_guard.reset()
