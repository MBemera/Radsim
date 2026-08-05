"""Normalized, defensively parsed model usage accounting."""

from __future__ import annotations

import math
from typing import Any

TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_write_input_tokens",
    "reasoning_output_tokens",
)


def normalize_usage(
    provider_usage: Any,
    *,
    provider: str | None = None,
    response: Any = None,
    latency_ms: float | None = None,
) -> dict[str, Any]:
    """Return a stable usage dictionary from dict or SDK response objects."""
    tokens = _normalize_tokens(provider_usage, provider)
    return {
        **tokens,
        "reported_cost_usd": _nonnegative_number(_read_field(provider_usage, "cost")),
        "estimated_cost_usd": _nonnegative_number(
            _read_field(provider_usage, "estimated_cost_usd")
        ),
        "retry_attempts": _token_count(provider_usage, "retry_attempts"),
        "request_id": _request_id(response),
        "provider_name": _bounded_string(provider),
        "routed_provider": _first_string(
            (response, "provider"),
            (provider_usage, "provider"),
        ),
        "response_model": _first_string(
            (response, "model"),
            (provider_usage, "model"),
        ),
        "latency_ms": _nonnegative_number(latency_ms),
    }


def _normalize_tokens(provider_usage: Any, provider: str | None) -> dict[str, int]:
    """Normalize token counts while preserving provider accounting semantics."""
    prompt_details = _read_field(provider_usage, "prompt_tokens_details")
    completion_details = _read_field(provider_usage, "completion_tokens_details")
    cache_read_tokens = _first_token_count(
        (prompt_details, "cached_tokens"),
        (provider_usage, "cache_read_input_tokens"),
    )
    cache_write_tokens = _first_token_count(
        (prompt_details, "cache_write_tokens"),
        (provider_usage, "cache_creation_input_tokens"),
    )
    input_tokens = _token_count(provider_usage, "prompt_tokens", "input_tokens")
    if provider == "anthropic":
        input_tokens += cache_read_tokens + cache_write_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": _token_count(provider_usage, "completion_tokens", "output_tokens"),
        "cache_read_input_tokens": cache_read_tokens,
        "cache_write_input_tokens": cache_write_tokens,
        "reasoning_output_tokens": _first_token_count(
            (completion_details, "reasoning_tokens"),
            (provider_usage, "reasoning_tokens"),
        ),
    }


def empty_usage_totals() -> dict[str, Any]:
    """Return new mutable session totals."""
    return {
        **dict.fromkeys(TOKEN_FIELDS, 0),
        "reported_cost_usd": 0.0,
        "reported_cost_requests": 0,
        "estimated_cost_usd": 0.0,
        "estimated_cost_requests": 0,
        "retry_attempts": 0,
        "request_count": 0,
        "latency_ms": 0.0,
    }


def accumulate_usage(totals: dict[str, Any], usage: dict[str, Any]) -> None:
    """Add one normalized response into session or eval totals."""
    for field in TOKEN_FIELDS:
        totals[field] = totals.get(field, 0) + _token_count(usage, field)
    totals["request_count"] = totals.get("request_count", 0) + 1
    totals["retry_attempts"] = totals.get("retry_attempts", 0) + _token_count(
        usage, "retry_attempts"
    )
    totals["latency_ms"] = totals.get("latency_ms", 0.0) + (
        _nonnegative_number(usage.get("latency_ms")) or 0.0
    )
    _accumulate_cost(totals, usage, "reported")
    _accumulate_cost(totals, usage, "estimated")


def merge_usage_snapshots(
    current: dict[str, Any],
    latest: dict[str, Any],
) -> dict[str, Any]:
    """Merge cumulative streaming snapshots without double-counting."""
    merged = dict(current)
    for field in TOKEN_FIELDS:
        merged[field] = max(_token_count(current, field), _token_count(latest, field))
    for field in ("reported_cost_usd", "estimated_cost_usd", "latency_ms"):
        if latest.get(field) is not None:
            merged[field] = latest[field]
    merged["retry_attempts"] = max(
        _token_count(current, "retry_attempts"),
        _token_count(latest, "retry_attempts"),
    )
    for field in ("request_id", "provider_name", "routed_provider", "response_model"):
        if latest.get(field):
            merged[field] = latest[field]
    return merged


def _accumulate_cost(totals: dict[str, Any], usage: dict[str, Any], kind: str) -> None:
    field = f"{kind}_cost_usd"
    cost = _nonnegative_number(usage.get(field))
    if cost is None:
        return
    totals[field] = totals.get(field, 0.0) + cost
    request_field = f"{kind}_cost_requests"
    totals[request_field] = totals.get(request_field, 0) + 1


def _first_token_count(*locations: tuple[Any, str]) -> int:
    for value, name in locations:
        raw_value = _read_field(value, name)
        if raw_value is not None:
            return _valid_token_count(raw_value)
    return 0


def _token_count(value: Any, *names: str) -> int:
    for name in names:
        raw_value = _read_field(value, name)
        if raw_value is not None:
            return _valid_token_count(raw_value)
    return 0


def _valid_token_count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return number if number >= 0 else 0


def _nonnegative_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _request_id(response: Any) -> str | None:
    for name in ("id", "request_id", "_request_id"):
        value = _read_field(response, name)
        if isinstance(value, str) and value:
            return value[:256]
    return None


def _first_string(*locations: tuple[Any, str]) -> str | None:
    """Return the first bounded, non-empty string from provider metadata."""
    for value, name in locations:
        normalized = _bounded_string(_read_field(value, name))
        if normalized:
            return normalized
    return None


def _bounded_string(value: Any) -> str | None:
    """Bound untrusted metadata without coercing objects or numbers."""
    if not isinstance(value, str) or not value:
        return None
    return value[:256]


def _read_field(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    direct = getattr(value, name, None)
    if direct is not None:
        return direct
    model_extra = getattr(value, "model_extra", None)
    return model_extra.get(name) if isinstance(model_extra, dict) else None
