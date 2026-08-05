"""Offline contracts for normalized provider usage accounting."""

from types import SimpleNamespace

from radsim.usage import (
    accumulate_usage,
    empty_usage_totals,
    merge_usage_snapshots,
    normalize_usage,
)


def test_normalizes_complete_openrouter_usage():
    usage = SimpleNamespace(
        prompt_tokens=120,
        completion_tokens=30,
        prompt_tokens_details=SimpleNamespace(cached_tokens=80, cache_write_tokens=20),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=12),
        cost=0.0042,
    )

    normalized = normalize_usage(
        usage,
        response=SimpleNamespace(id="request-123"),
        latency_ms=14.5,
    )

    assert normalized == {
        "input_tokens": 120,
        "output_tokens": 30,
        "cache_read_input_tokens": 80,
        "cache_write_input_tokens": 20,
        "reasoning_output_tokens": 12,
        "reported_cost_usd": 0.0042,
        "estimated_cost_usd": None,
        "retry_attempts": 0,
        "request_id": "request-123",
        "provider_name": None,
        "routed_provider": None,
        "response_model": None,
        "latency_ms": 14.5,
    }


def test_normalizes_bounded_provider_route_and_model_metadata():
    normalized = normalize_usage(
        {"provider": "fallback-provider"},
        provider="openrouter",
        response=SimpleNamespace(
            provider="upstream-provider",
            model="vendor/model",
        ),
    )

    assert normalized["provider_name"] == "openrouter"
    assert normalized["routed_provider"] == "upstream-provider"
    assert normalized["response_model"] == "vendor/model"


def test_malformed_provider_metadata_is_ignored_and_bounded():
    normalized = normalize_usage(
        {"provider": 42, "model": object()},
        provider="x" * 400,
        response={"provider": "y" * 400},
    )

    assert len(normalized["provider_name"]) == 256
    assert len(normalized["routed_provider"]) == 256
    assert normalized["response_model"] is None


def test_normalizes_anthropic_cache_fields_and_model_extra():
    usage = SimpleNamespace(
        input_tokens=75,
        output_tokens=25,
        cache_read_input_tokens=50,
        cache_creation_input_tokens=10,
        model_extra={"cost": "0.0025"},
    )

    normalized = normalize_usage(
        usage,
        provider="anthropic",
        response=SimpleNamespace(request_id="anthropic-1"),
    )

    assert normalized["input_tokens"] == 135
    assert normalized["cache_read_input_tokens"] == 50
    assert normalized["cache_write_input_tokens"] == 10
    assert normalized["reported_cost_usd"] == 0.0025
    assert normalized["request_id"] == "anthropic-1"


def test_missing_and_malformed_values_fail_to_safe_defaults():
    normalized = normalize_usage(
        {
            "prompt_tokens": -1,
            "completion_tokens": "not-a-number",
            "cost": float("nan"),
            "prompt_tokens_details": {"cached_tokens": True},
        },
        response={"id": "x" * 400},
        latency_ms=-10,
    )

    assert normalized["input_tokens"] == 0
    assert normalized["output_tokens"] == 0
    assert normalized["cache_read_input_tokens"] == 0
    assert normalized["reported_cost_usd"] is None
    assert normalized["latency_ms"] is None
    assert len(normalized["request_id"]) == 256


def test_streaming_snapshots_merge_without_double_counting():
    current = normalize_usage({"input_tokens": 100, "cache_read_input_tokens": 80})
    latest = normalize_usage(
        {"output_tokens": 20, "reasoning_tokens": 8, "cost": 0.003},
        response={"id": "stream-request"},
        latency_ms=25,
    )

    merged = merge_usage_snapshots(current, latest)

    assert merged["input_tokens"] == 100
    assert merged["cache_read_input_tokens"] == 80
    assert merged["output_tokens"] == 20
    assert merged["reasoning_output_tokens"] == 8
    assert merged["reported_cost_usd"] == 0.003
    assert merged["request_id"] == "stream-request"


def test_streaming_snapshots_keep_latest_route_metadata():
    current = normalize_usage({}, provider="openrouter", response={"provider": "route-a"})
    latest = normalize_usage({}, provider="openrouter", response={"provider": "route-b"})

    merged = merge_usage_snapshots(current, latest)

    assert merged["provider_name"] == "openrouter"
    assert merged["routed_provider"] == "route-b"


def test_session_totals_track_cost_coverage_separately():
    totals = empty_usage_totals()
    accumulate_usage(
        totals,
        normalize_usage(
            {
                "input_tokens": 10,
                "output_tokens": 5,
                "cost": 0.001,
                "estimated_cost_usd": 0.0012,
                "retry_attempts": 2,
            }
        ),
    )
    accumulate_usage(totals, normalize_usage({"input_tokens": 20, "output_tokens": 7}))

    assert totals["input_tokens"] == 30
    assert totals["output_tokens"] == 12
    assert totals["reported_cost_usd"] == 0.001
    assert totals["reported_cost_requests"] == 1
    assert totals["estimated_cost_usd"] == 0.0012
    assert totals["estimated_cost_requests"] == 1
    assert totals["retry_attempts"] == 2
    assert totals["request_count"] == 2
