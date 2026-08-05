"""Thread-safe provider-reported spend guard for live evals."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from threading import Lock
from typing import Any

from radsim.pricing import ModelPricing, estimate_usage_cost
from radsim.request_options import RequestOptions


class EvalBudgetExceeded(RuntimeError):
    """Raised before a request when live eval spend is no longer authorized."""


class EvalCostBudget:
    """Stop new eval requests at a provider-reported USD cost cap."""

    def __init__(self, max_cost_usd: str) -> None:
        self.max_cost_usd = Decimal(max_cost_usd)
        self.reported_cost_usd = Decimal("0")
        self.requests_started = 0
        self.provider_attempts = 0
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
            self.provider_attempts += 1 + _retry_attempts(usage)
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

    def record_error(self, error: Exception) -> None:
        """Fail closed when a request may have incurred unreported spend."""
        with self._lock:
            self.provider_attempts += 1 + _retry_attempts(error)
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
                "provider_attempts": self.provider_attempts,
                "responses_received": self.responses_received,
                "responses_with_reported_cost": self.responses_with_cost,
                "unknown_cost_events": self.unknown_cost_events,
                "cost_accounting_complete": self.unknown_cost_events == 0,
                "blocked_reason": self.blocked_reason,
            }


class BudgetedEvalClient:
    """Apply one shared cost budget around an eval API client."""

    def __init__(
        self,
        client: Any,
        budget: EvalCostBudget,
        pricing: ModelPricing | None = None,
        request_options: RequestOptions | None = None,
    ) -> None:
        self.client = client
        self.budget = budget
        self.pricing = pricing
        self.request_options = request_options

    def chat(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if self.request_options is not None:
            supplied_options = kwargs.get("request_options")
            if supplied_options is not None and supplied_options != self.request_options:
                raise ValueError("Eval request options cannot change during a run")
            kwargs["request_options"] = self.request_options
        self.budget.before_request()
        try:
            response = self.client.chat(*args, **kwargs)
        except Exception as error:
            self.budget.record_error(error)
            raise
        _attach_estimated_cost(response, self.pricing)
        self.budget.record_response(response)
        return response


def _attach_estimated_cost(response: Any, pricing: ModelPricing | None) -> None:
    """Attach one estimate from the immutable run pricing snapshot."""
    if pricing is None or not isinstance(response, dict):
        return
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return
    estimate = estimate_usage_cost(usage, pricing)
    usage["estimated_cost_usd"] = (
        None if estimate.total_usd is None else float(estimate.total_usd)
    )
    usage["pricing_source"] = pricing.source


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


def _retry_attempts(value: Any) -> int:
    if isinstance(value, dict):
        raw_value = value.get("retry_attempts", 0)
    else:
        raw_value = getattr(value, "retry_attempts", 0)
    if not isinstance(raw_value, int) or isinstance(raw_value, bool) or raw_value < 0:
        return 0
    return raw_value
