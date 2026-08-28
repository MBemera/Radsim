"""Profile representative local RadSim work after architectural optimisations."""

from __future__ import annotations

import argparse
import cProfile
import json
import platform
import pstats
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from radsim.learning.events import LearningEvent, TaskOutcome
from radsim.learning.retrieval import rank_learning_events, tokenize
from radsim.learning.store import LearningStore, fts5_available
from radsim.performance import request_payload_metrics
from radsim.tool_router import route_tool_schemas
from radsim.tool_schema import canonicalize_tool_schemas
from radsim.tools import TOOL_DEFINITIONS

DEFAULT_EVENT_COUNT = 2_000
DEFAULT_ITERATIONS = 500
RUST_KERNEL_MINIMUM_PERCENT = 15.0


def _events(count):
    created_at = datetime.now(timezone.utc).isoformat()
    return [
        LearningEvent.create(
            event_id=f"profile-event-{index}",
            task_id=f"profile-task-{index}",
            event_type="task_completion",
            task_category="bug_fix" if index % 2 else "feature",
            tool_name="run_tests" if index % 3 else "read_file",
            outcome=TaskOutcome.SUCCESSFUL,
            summary=f"Fix validation failure {index} and run focused tests",
            created_at=created_at,
        )
        for index in range(count)
    ]


def _prepare_store(directory, event_count):
    store = LearningStore(directory, max_events=10_000, migrate_legacy=False)
    store.append_many(_events(event_count))
    return store


def _run_workload(store, iterations):
    queries = (
        "fix validation failure and run tests",
        "inspect repository configuration and dependencies",
        "review tool policy security checks",
    )
    result_count = 0
    for index in range(iterations):
        query = queries[index % len(queries)]
        candidates = store.search_events(tokenize(query), limit=20)
        ranked = rank_learning_events(query, candidates, task_category="bug_fix", limit=5)
        routed = route_tool_schemas(TOOL_DEFINITIONS, query)
        schemas = canonicalize_tool_schemas(routed.tools)
        metrics = request_payload_metrics("stable system prompt", schemas)
        result_count += len(ranked) + metrics["tool_schema_count"]
    return result_count


def _profile_workload(store, iterations):
    profiler = cProfile.Profile()
    profiler.enable()
    result_count = _run_workload(store, iterations)
    profiler.disable()
    return profiler, result_count


def _profile_rows(profiler):
    stats = pstats.Stats(profiler)
    rows = []
    for (filename, line, function), values in stats.stats.items():
        if "/radsim/" not in filename:
            continue
        call_count = values[1]
        self_seconds = values[2]
        cumulative_seconds = values[3]
        rows.append(
            {
                "file": str(Path(filename).relative_to(Path.cwd())),
                "line": line,
                "function": function,
                "calls": call_count,
                "self_seconds": round(self_seconds, 6),
                "cumulative_seconds": round(cumulative_seconds, 6),
                "self_percent": round((self_seconds / max(stats.total_tt, 1e-12)) * 100, 4),
            }
        )
    return stats.total_tt, sorted(rows, key=lambda row: row["self_seconds"], reverse=True)


def _build_report(profiler, iterations, event_count, result_count):
    total_seconds, rows = _profile_rows(profiler)
    largest_share = rows[0]["self_percent"] if rows else 0.0
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "os": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "workload": {
            "iterations": iterations,
            "learning_events": event_count,
            "fts5_available": fts5_available(),
            "result_count": result_count,
        },
        "profiled_seconds": round(total_seconds, 6),
        "largest_python_kernel_percent": largest_share,
        "rust_admission_threshold_percent": RUST_KERNEL_MINIMUM_PERCENT,
        "rust_kernel_time_gate_met": largest_share >= RUST_KERNEL_MINIMUM_PERCENT,
        "top_python_functions": rows[:20],
    }


def run_profile(iterations=DEFAULT_ITERATIONS, event_count=DEFAULT_EVENT_COUNT):
    with tempfile.TemporaryDirectory(prefix="radsim-profile-") as directory:
        store = _prepare_store(Path(directory), event_count)
        profiler, result_count = _profile_workload(store, iterations)
    return _build_report(profiler, iterations, event_count, result_count)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--events", type=int, default=DEFAULT_EVENT_COUNT)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = run_profile(arguments.iterations, arguments.events)
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if arguments.output:
        arguments.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
