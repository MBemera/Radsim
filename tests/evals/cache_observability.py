"""Natural cache priming and cache evidence for behavioural evals."""

from __future__ import annotations

import math
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

Job = tuple[Any, ...]
IndexedJob = tuple[int, Job]


def split_cache_priming_jobs(jobs: list[Job]) -> tuple[list[IndexedJob], list[IndexedJob]]:
    """Select the first scored run for each candidate prefix as its primer."""
    primed_candidates = set()
    priming_jobs = []
    remaining_jobs = []
    for indexed_job in enumerate(jobs):
        candidate = indexed_job[1][0]
        target = priming_jobs if candidate not in primed_candidates else remaining_jobs
        target.append(indexed_job)
        primed_candidates.add(candidate)
    return priming_jobs, remaining_jobs


def run_jobs_with_natural_priming(
    priming_jobs: list[IndexedJob],
    remaining_jobs: list[IndexedJob],
    run_one: Callable[[Job], Any],
    workers: int,
) -> list[Any]:
    """Score natural primers first, then fan out and restore seeded job order."""
    indexed_results = {index: run_one(job) for index, job in priming_jobs}
    remaining = [job for _index, job in remaining_jobs]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        concurrent_results = executor.map(run_one, remaining)
        for (index, _job), result in zip(remaining_jobs, concurrent_results, strict=True):
            indexed_results[index] = result
    return [indexed_results[index] for index in range(len(indexed_results))]


def summarise_cache_observability(records: list[Any]) -> dict[str, dict[str, Any]]:
    """Summarise cache evidence after each candidate's natural first request."""
    candidates = {}
    primed_candidates = set()
    for record in records:
        summary = candidates.setdefault(record.candidate, _empty_cache_summary())
        for observation in record.request_observations:
            if record.candidate not in primed_candidates:
                primed_candidates.add(record.candidate)
                continue
            _add_cache_observation(summary, observation)
    return {name: _finish_cache_summary(value) for name, value in sorted(candidates.items())}


def print_cache_observability(cache_observability: dict[str, dict[str, Any]]) -> None:
    """Print cache status without treating a missing remote hit as success."""
    print("\nCache after each candidate's first scored request")
    for name, summary in cache_observability.items():
        _print_candidate_cache(name, summary)


def _empty_cache_summary() -> dict[str, Any]:
    return {
        "eligible_requests": 0,
        "input_tokens": 0,
        "cache_read_input_tokens": 0,
        "latency_ms": 0.0,
        "latency_samples": 0,
        "routed_providers": set(),
        "provider_names": set(),
    }


def _add_cache_observation(summary: dict[str, Any], observation: dict[str, Any]) -> None:
    summary["eligible_requests"] += 1
    summary["input_tokens"] += _nonnegative_int(observation.get("input_tokens"))
    summary["cache_read_input_tokens"] += _nonnegative_int(
        observation.get("cache_read_input_tokens")
    )
    _add_latency(summary, observation.get("latency_ms"))
    _add_observed_string(summary["routed_providers"], observation.get("routed_provider"))
    _add_observed_string(summary["provider_names"], observation.get("provider_name"))


def _add_latency(summary: dict[str, Any], latency: Any) -> None:
    if not _is_nonnegative_number(latency):
        return
    summary["latency_ms"] += latency
    summary["latency_samples"] += 1


def _finish_cache_summary(summary: dict[str, Any]) -> dict[str, Any]:
    input_tokens = summary["input_tokens"]
    cache_tokens = summary["cache_read_input_tokens"]
    invalid = cache_tokens > input_tokens
    return {
        "status": _cache_status(cache_tokens, invalid),
        "eligible_requests": summary["eligible_requests"],
        "input_tokens": input_tokens,
        "cache_read_input_tokens": cache_tokens,
        "cached_fraction": None if not input_tokens or invalid else cache_tokens / input_tokens,
        "mean_latency_ms": _mean_latency(summary),
        "provider_names": sorted(summary["provider_names"]),
        "routed_providers": sorted(summary["routed_providers"]),
    }


def _cache_status(cache_tokens: int, invalid: bool) -> str:
    if invalid:
        return "invalid accounting"
    if cache_tokens:
        return "observed"
    return "not observed"


def _mean_latency(summary: dict[str, Any]) -> float | None:
    if not summary["latency_samples"]:
        return None
    return summary["latency_ms"] / summary["latency_samples"]


def _add_observed_string(values: set[str], value: Any) -> None:
    if isinstance(value, str) and value:
        values.add(value[:256])


def _nonnegative_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _is_nonnegative_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _print_candidate_cache(name: str, summary: dict[str, Any]) -> None:
    fraction = summary["cached_fraction"]
    fraction_text = "n/a" if fraction is None else f"{fraction:.1%}"
    routes = ", ".join(summary["routed_providers"]) or "not reported"
    providers = ", ".join(summary["provider_names"]) or "not reported"
    mean_latency = summary["mean_latency_ms"]
    latency_text = "n/a" if mean_latency is None else f"{mean_latency:.0f}ms"
    print(
        f"  {name}: {summary['status']}; cached_fraction={fraction_text} "
        f"requests={summary['eligible_requests']} mean_latency={latency_text} "
        f"provider={providers} routed_provider={routes}"
    )
