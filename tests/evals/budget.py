"""Thread-safe provider-reported spend guard for live evals."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from threading import Lock
from typing import Any


class EvalBudgetExceeded(RuntimeError):
    """Raised before a request when live eval spend is no longer authorized."""


class EvalCostBudget:
    """Stop new eval requests at a provider-reported USD cost cap."""

    def __init__(self, max_cost_usd: str) -> None:
        self.max_cost_usd = Decimal(max_cost_usd)
        self.reported_cost_usd = Decimal("0")
        self.requests_started = 0
        self.responses_received = 0
        self.responses_with_cost = 0
        self.unknown_cost_events = 0
        self.blocked_reason: str | None = None
        self._lock = Lock()

    def before_request(self) -> None:
        """Authorize one request or fail before provider I/O."""
        with self._lock:
            if self.blocked_reason:
                raise EvalBudgetExceeded(self.blocked_reason)
            if self.reported_cost_usd >= self.max_cost_usd:
                self.blocked_reason = "Eval cost cap reached; no new requests are authorized."
                raise EvalBudgetExceeded(self.blocked_reason)
            self.requests_started += 1

    def record_response(self, response: Any) -> None:
        """Record provider spend and close the budget on missing cost data."""
        usage = response.get("usage", {}) if isinstance(response, dict) else {}
        reported_cost = _cost_decimal(usage.get("reported_cost_usd"))
        with self._lock:
            self.responses_received += 1
            if reported_cost is None:
                self.unknown_cost_events += 1
                self.blocked_reason = (
                    "Provider omitted valid cost data; no new requests are authorized."
                )
                return
            self.responses_with_cost += 1
            self.reported_cost_usd += reported_cost
            if self.reported_cost_usd >= self.max_cost_usd:
                self.blocked_reason = "Eval cost cap reached; no new requests are authorized."

    def record_error(self) -> None:
        """Fail closed when a request may have incurred unreported spend."""
        with self._lock:
            self.unknown_cost_events += 1
            self.blocked_reason = (
                "A provider request failed without cost data; no new requests are authorized."
            )

    def snapshot(self) -> dict[str, Any]:
        """Return JSON-safe budget evidence for the run manifest."""
        with self._lock:
            return {
                "configured_cap_usd": str(self.max_cost_usd),
                "provider_reported_cost_usd": str(self.reported_cost_usd),
                "requests_started": self.requests_started,
                "responses_received": self.responses_received,
                "responses_with_reported_cost": self.responses_with_cost,
                "unknown_cost_events": self.unknown_cost_events,
                "cost_accounting_complete": self.unknown_cost_events == 0,
                "blocked_reason": self.blocked_reason,
            }


class BudgetedEvalClient:
    """Apply one shared cost budget around an eval API client."""

    def __init__(self, client: Any, budget: EvalCostBudget) -> None:
        self.client = client
        self.budget = budget

    def chat(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.budget.before_request()
        try:
            response = self.client.chat(*args, **kwargs)
        except Exception:
            self.budget.record_error()
            raise
        self.budget.record_response(response)
        return response


def _cost_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        cost = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not cost.is_finite() or cost < 0:
        return None
    return cost
