"""Contracts for provider-aware pricing and cache-aware estimates."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from radsim.config import get_model_pricing, get_static_model_pricing
from radsim.pricing import ModelPricing, describe_pricing_source, estimate_usage_cost


def build_pricing(**overrides) -> ModelPricing:
    values = {
        "provider": "openrouter",
        "billing_mode": "routing",
        "model": "vendor/model",
        "input_per_million_usd": "2.00",
        "output_per_million_usd": "10.00",
        "cache_read_per_million_usd": "0.50",
        "cache_write_per_million_usd": "2.50",
        "source": "catalogue-cache",
        "fetched_at": "2026-08-04T00:00:00Z",
    }
    values.update(overrides)
    return ModelPricing(**values)


def test_cache_aware_estimate_matches_hand_calculation_exactly():
    usage = {
        "input_tokens": 1_000,
        "output_tokens": 500,
        "cache_read_input_tokens": 600,
        "cache_write_input_tokens": 100,
    }

    estimate = estimate_usage_cost(usage, build_pricing())

    assert estimate.uncached_input_usd == Decimal("0.0006")
    assert estimate.cache_read_usd == Decimal("0.0003")
    assert estimate.cache_write_usd == Decimal("0.00025")
    assert estimate.output_usd == Decimal("0.005")
    assert estimate.total_usd == Decimal("0.00615")


def test_used_cache_without_a_catalogue_price_is_not_reported_as_free():
    pricing = build_pricing(cache_read_per_million_usd=None)

    estimate = estimate_usage_cost(
        {"input_tokens": 100, "cache_read_input_tokens": 50}, pricing
    )

    assert estimate.total_usd is None
    assert estimate.unavailable_reason == "catalogue omits a used cache price"


def test_inconsistent_cache_usage_fails_closed():
    estimate = estimate_usage_cost(
        {"input_tokens": 10, "cache_read_input_tokens": 11}, build_pricing()
    )

    assert estimate.total_usd is None
    assert estimate.unavailable_reason == "cached input exceeds total input"


@pytest.mark.parametrize("price", [-1, float("inf"), float("nan"), True, "invalid", 100001])
def test_invalid_or_implausible_prices_are_rejected(price):
    with pytest.raises(ValueError):
        build_pricing(input_per_million_usd=price)


def test_pricing_snapshot_is_immutable():
    pricing = build_pricing()

    with pytest.raises(FrozenInstanceError):
        pricing.source = "changed"


def test_pricing_source_description_includes_provider_mode_source_and_age():
    description = describe_pricing_source(
        build_pricing(stale=True),
        now=datetime(2026, 8, 4, 3, tzinfo=UTC),
    )

    assert description == "openrouter/routing, catalogue-cache, age 3h, stale"


def test_glm_openrouter_fallback_uses_verified_routing_prices():
    pricing = get_static_model_pricing("z-ai/glm-5.2", "openrouter", "routing")

    assert pricing.input_per_million_usd == Decimal("0.76")
    assert pricing.output_per_million_usd == Decimal("2.42")
    assert pricing.cache_read_per_million_usd == Decimal("0.14")
    assert pricing.source == "static-fallback"
    assert pricing.stale is True


def test_unknown_model_pricing_remains_unknown():
    assert get_model_pricing("unknown/model", "openrouter") is None
