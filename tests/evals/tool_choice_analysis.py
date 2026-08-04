"""Privacy-safe evidence for tool-schema confusion analysis."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

MAX_ANALYSIS_SAMPLES = 500
MAX_CONFUSION_PAIRS = 500
MAX_TOOL_NAMES_PER_RUN = 32
TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def analyse_tool_choice_failures(
    scores: list[dict[str, Any]],
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate failed tool choices without copying messages or arguments."""
    runs_by_key = _index_runs(runs)
    confusion_counts: Counter[tuple[str, str]] = Counter()
    samples = []
    for score in scores:
        if not isinstance(score, dict):
            continue
        if score.get("tool_choice_correct") is not False or score.get("error"):
            continue
        sample = _failure_sample(score, runs_by_key.get(_record_key(score), {}))
        samples.append(sample)
        for observed_tool in sample["observed_tools"]:
            confusion_counts[(sample["expected"], observed_tool)] += 1
    confusions = _ordered_confusions(confusion_counts)
    return {
        "failed_runs": len(samples),
        "confusions": confusions[:MAX_CONFUSION_PAIRS],
        "confusions_truncated": len(confusions) > MAX_CONFUSION_PAIRS,
        "samples": samples[:MAX_ANALYSIS_SAMPLES],
        "samples_truncated": len(samples) > MAX_ANALYSIS_SAMPLES,
    }


def _index_runs(runs: list[dict[str, Any]]) -> dict[tuple[str, str, int], dict[str, Any]]:
    indexed = {}
    for run in runs:
        key = _record_key(run)
        if key is not None:
            indexed[key] = run
    return indexed


def print_tool_choice_analysis(analysis: dict[str, Any]) -> None:
    """Print the most frequent confusion pairs, or an explicit empty result."""
    failed_runs = analysis.get("failed_runs", 0)
    if not failed_runs:
        print("\nTool-choice confusions: none observed")
        return
    print(f"\nTool-choice confusions: {failed_runs} failed runs")
    for confusion in analysis.get("confusions", [])[:10]:
        print(
            f"  expected={confusion['expected']} observed={confusion['observed']} "
            f"count={confusion['count']}"
        )


def _failure_sample(score: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    expected_tools = _tool_names(score.get("expected_tools"))
    forbidden_tools = _tool_names(score.get("forbidden_tools"))
    observed_tools = _observed_tools(run)
    expect_no_tools = score.get("expect_no_tools") is True
    return {
        "case_id": _bounded_string(score.get("case_id")),
        "candidate": _bounded_string(score.get("candidate")),
        "repetition": _nonnegative_integer(score.get("repetition")),
        "expected": _expectation_label(expected_tools, forbidden_tools, expect_no_tools),
        "observed_tools": _confused_tools(
            observed_tools,
            forbidden_tools,
            bool(expected_tools),
            expect_no_tools,
        ),
    }


def _expectation_label(expected: list[str], forbidden: list[str], expect_none: bool) -> str:
    if expected:
        return "one of: " + ", ".join(expected)
    if expect_none:
        return "[no tool]"
    if forbidden:
        return "[avoid forbidden tools]"
    return "[unspecified]"


def _confused_tools(
    observed: list[str],
    forbidden: list[str],
    has_expected: bool,
    expect_none: bool,
) -> list[str]:
    if has_expected or expect_none:
        return observed or ["[no tool]"]
    forbidden_observed = [name for name in observed if name in forbidden]
    return forbidden_observed or ["[unresolved]"]


def _observed_tools(run: dict[str, Any]) -> list[str]:
    calls = run.get("tool_calls", []) if isinstance(run, dict) else []
    if not isinstance(calls, list):
        return []
    names = [call.get("name") for call in calls[:MAX_TOOL_NAMES_PER_RUN] if isinstance(call, dict)]
    return _tool_names(names)


def _tool_names(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    names = set()
    for name in value[:MAX_TOOL_NAMES_PER_RUN]:
        safe_name = _safe_tool_name(name)
        if safe_name:
            names.add(safe_name)
    return sorted(names)


def _safe_tool_name(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if TOOL_NAME_PATTERN.fullmatch(value):
        return value
    return "[invalid tool name]"


def _ordered_confusions(counts: Counter[tuple[str, str]]) -> list[dict[str, Any]]:
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"expected": expected, "observed": observed, "count": count}
        for (expected, observed), count in ordered
    ]


def _record_key(value: Any) -> tuple[str, str, int] | None:
    if not isinstance(value, dict):
        return None
    case_id = value.get("case_id")
    candidate = value.get("candidate")
    repetition = value.get("repetition")
    if not isinstance(case_id, str) or not isinstance(candidate, str):
        return None
    if not isinstance(repetition, int) or isinstance(repetition, bool) or repetition < 0:
        return None
    return case_id[:64], candidate[:64], repetition


def _bounded_string(value: Any) -> str | None:
    return value[:64] if isinstance(value, str) and value else None


def _nonnegative_integer(value: Any) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value
