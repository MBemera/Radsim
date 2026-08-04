"""Validated model pricing and cache-aware cost estimates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

TOKENS_PER_MILLION = Decimal("1000000")
MAX_PRICE_PER_MILLION_USD = Decimal("100000")


@dataclass(frozen=True)
class ModelPricing:
    """One immutable provider and billing-mode pricing snapshot."""

    provider: str
    billing_mode: str
    model: str
    input_per_million_usd: Decimal
    output_per_million_usd: Decimal
    source: str
    fetched_at: str | None
    cache_read_per_million_usd: Decimal | None = None
    cache_write_per_million_usd: Decimal | None = None
    stale: bool = False

    def __post_init__(self) -> None:
        for field_name in ("provider", "billing_mode", "model", "source"):
            _validate_identifier(getattr(self, field_name), field_name)
        for field_name in (
            "input_per_million_usd",
            "output_per_million_usd",
            "cache_read_per_million_usd",
            "cache_write_per_million_usd",
        ):
            object.__setattr__(self, field_name, _validated_price(getattr(self, field_name)))

    @classmethod
    def from_per_token(
        cls,
        *,
        provider: str,
        billing_mode: str,
        model: str,
        input_price: Any,
        output_price: Any,
        source: str,
        fetched_at: str | None,
        cache_read_price: Any = None,
        cache_write_price: Any = None,
        stale: bool = False,
    ) -> ModelPricing:
        """Build a snapshot from per-token catalogue values."""
        return cls(
            provider=provider,
            billing_mode=billing_mode,
            model=model,
            input_per_million_usd=_per_token_to_million(input_price),
            output_per_million_usd=_per_token_to_million(output_price),
            cache_read_per_million_usd=_optional_per_token_to_million(cache_read_price),
            cache_write_per_million_usd=_optional_per_token_to_million(cache_write_price),
            source=source,
            fetched_at=fetched_at,
            stale=stale,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe manifest representation."""
        return {
            "provider": self.provider,
            "billing_mode": self.billing_mode,
            "model": self.model,
            "input_per_million_usd": str(self.input_per_million_usd),
            "output_per_million_usd": str(self.output_per_million_usd),
            "cache_read_per_million_usd": _optional_decimal_string(
                self.cache_read_per_million_usd
            ),
            "cache_write_per_million_usd": _optional_decimal_string(
                self.cache_write_per_million_usd
            ),
            "source": self.source,
            "fetched_at": self.fetched_at,
            "stale": self.stale,
        }


@dataclass(frozen=True)
class CostEstimate:
    """Exact decimal cost components for one normalized usage object."""

    total_usd: Decimal | None
    uncached_input_usd: Decimal | None
    output_usd: Decimal | None
    cache_read_usd: Decimal | None
    cache_write_usd: Decimal | None
    unavailable_reason: str | None = None


def estimate_usage_cost(usage: dict[str, Any], pricing: ModelPricing) -> CostEstimate:
    """Estimate usage without double-charging cached input tokens."""
    input_tokens = _token_count(usage, "input_tokens")
    output_tokens = _token_count(usage, "output_tokens")
    cache_read_tokens = _token_count(usage, "cache_read_input_tokens")
    cache_write_tokens = _token_count(usage, "cache_write_input_tokens")
    if cache_read_tokens + cache_write_tokens > input_tokens:
        return _unavailable_estimate("cached input exceeds total input")

    uncached_tokens = input_tokens - cache_read_tokens - cache_write_tokens
    uncached_cost = _token_cost(uncached_tokens, pricing.input_per_million_usd)
    output_cost = _token_cost(output_tokens, pricing.output_per_million_usd)
    cache_read_cost = _optional_token_cost(
        cache_read_tokens, pricing.cache_read_per_million_usd
    )
    cache_write_cost = _optional_token_cost(
        cache_write_tokens, pricing.cache_write_per_million_usd
    )
    if cache_read_cost is None or cache_write_cost is None:
        return _unavailable_estimate("catalogue omits a used cache price")
    return CostEstimate(
        total_usd=uncached_cost + output_cost + cache_read_cost + cache_write_cost,
        uncached_input_usd=uncached_cost,
        output_usd=output_cost,
        cache_read_usd=cache_read_cost,
        cache_write_usd=cache_write_cost,
    )


def describe_pricing_source(
    pricing: ModelPricing,
    *,
    now: datetime | None = None,
) -> str:
    """Describe provider, billing mode, source, and snapshot age."""
    age = _snapshot_age(pricing.fetched_at, now or datetime.now(tz=UTC))
    stale_label = ", stale" if pricing.stale else ""
    return (
        f"{pricing.provider}/{pricing.billing_mode}, {pricing.source}, "
        f"age {age}{stale_label}"
    )


def _validated_price(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("pricing values must be numeric")
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("pricing values must be numeric") from error
    if not price.is_finite() or not 0 <= price <= MAX_PRICE_PER_MILLION_USD:
        raise ValueError("pricing values must be finite and plausible")
    return price


def _snapshot_age(fetched_at: str | None, now: datetime) -> str:
    if not fetched_at:
        return "unknown"
    try:
        fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "unknown"
    age_seconds = max(0, int((now - fetched).total_seconds()))
    if age_seconds < 3600:
        return "<1h"
    if age_seconds < 172800:
        return f"{age_seconds // 3600}h"
    return f"{age_seconds // 86400}d"


def _per_token_to_million(value: Any) -> Decimal:
    price = _validated_price(value)
    if price is None:
        raise ValueError("input and output prices are required")
    return _validated_price(price * TOKENS_PER_MILLION)


def _optional_per_token_to_million(value: Any) -> Decimal | None:
    if value is None:
        return None
    return _per_token_to_million(value)


def _validate_identifier(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"{field_name} must be a bounded non-empty string")


def _token_count(usage: dict[str, Any], field_name: str) -> int:
    value = usage.get(field_name, 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return 0
    return value


def _token_cost(tokens: int, price_per_million: Decimal) -> Decimal:
    return Decimal(tokens) * price_per_million / TOKENS_PER_MILLION


def _optional_token_cost(tokens: int, price: Decimal | None) -> Decimal | None:
    if tokens == 0:
        return Decimal("0")
    if price is None:
        return None
    return _token_cost(tokens, price)


def _unavailable_estimate(reason: str) -> CostEstimate:
    return CostEstimate(None, None, None, None, None, reason)


def _optional_decimal_string(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
