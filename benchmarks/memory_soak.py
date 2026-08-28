"""Run the item-9 long-session memory release gate with mocked turns."""

from __future__ import annotations

import argparse
import gc
import json
import platform
import resource
import sqlite3
import subprocess
import threading
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

from radsim.agent_api import serialize_tool_result
from radsim.agent_conversation import MAX_RETAINED_MESSAGES, AgentConversationMixin
from radsim.agent_subagents import AgentSubAgentMixin
from radsim.background import (
    DEFAULT_MAX_FINISHED_JOBS,
    get_job_manager,
    reset_job_manager,
)
from radsim.repo_map import _cache_symbols
from radsim.runtime_context import RuntimeContext
from radsim.skill_registry import get_skill_registry
from radsim.tool_schema import canonicalize_tool_schemas
from radsim.tools import TOOL_DEFINITIONS

DEFAULT_TURNS = 1_000
DEFAULT_WARMUP_TURNS = 1_000


class SoakConversation(AgentConversationMixin, AgentSubAgentMixin):
    """Own only the state used by the mocked conversation lifecycle."""

    def __init__(self):
        self.messages = []
        self._injected_job_ids = set()
        self._memory_evicted_messages = 0
        self._memory_released_media_blocks = 0
        self.runtime_context = RuntimeContext()


def _mock_result(turn):
    return SimpleNamespace(
        content=f"background result {turn}",
        input_tokens=10,
        output_tokens=5,
        tool_calls=1,
    )


def _append_mock_turn(agent, turn):
    tool_id = f"tool-{turn}"
    agent.messages.append({"role": "user", "content": f"request {turn}"})
    agent.messages.append(
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": tool_id, "name": "read_file"}],
        }
    )
    result = serialize_tool_result({"success": True, "content": "x" * 20_000})
    content = [{"type": "tool_result", "tool_use_id": tool_id, "content": result}]
    if turn % 10 == 0:
        content.append({"type": "image", "source": {"data": "A" * 200_000}})
    agent.messages.append({"role": "user", "content": content})
    agent.messages.append({"role": "assistant", "content": f"answer {turn}"})


def _run_mock_turn(agent, turn):
    _append_mock_turn(agent, turn)
    _exercise_caches(agent, turn)
    if turn % 5 == 0:
        manager = get_job_manager()
        job = manager.start_job(f"job {turn}", lambda: _mock_result(turn))
        job._thread.join(timeout=2)
        background_result = agent._collect_finished_background_results()
        if background_result:
            agent.messages.append({"role": "user", "content": background_result})
    agent._release_processed_media()
    agent._enforce_message_retention()


def _exercise_caches(agent, turn):
    agent.runtime_context.get_cached_prompt_fragment(
        f"prompt-{turn}", [], lambda: f"fragment {turn}"
    )
    agent.runtime_context.get_cached_project_detection(
        f"project-{turn}", [], lambda: {"kind": "python", "turn": turn}
    )
    _cache_symbols((f"digest-{turn}", 2, "python"), [{"name": f"symbol-{turn}"}])
    skills = get_skill_registry().list_available_skills()
    if skills:
        get_skill_registry().get_skill_docs(skills[turn % len(skills)])
    tool_count = (turn % len(TOOL_DEFINITIONS)) + 1
    canonicalize_tool_schemas(TOOL_DEFINITIONS[:tool_count])


def _rss_bytes():
    maximum_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if platform.system() == "Darwin":
        return int(maximum_rss)
    return int(maximum_rss * 1_024)


def _file_descriptor_count():
    for directory in (Path("/proc/self/fd"), Path("/dev/fd")):
        try:
            return len(list(directory.iterdir()))
        except OSError:
            continue
    return None


def _child_process_count():
    return sum(
        isinstance(item, subprocess.Popen) and item.poll() is None
        for item in gc.get_objects()
    )


def _sqlite_connection_count():
    return sum(isinstance(item, sqlite3.Connection) for item in gc.get_objects())


def _snapshot(agent):
    gc.collect()
    current_allocated, peak_allocated = tracemalloc.get_traced_memory()
    return {
        "rss_bytes": _rss_bytes(),
        "tracemalloc_current_bytes": current_allocated,
        "tracemalloc_peak_bytes": peak_allocated,
        "file_descriptors": _file_descriptor_count(),
        "threads": threading.active_count(),
        "subprocesses": _child_process_count(),
        "sqlite_connections": _sqlite_connection_count(),
        "messages": len(agent.messages),
        "injected_job_ids": len(agent._injected_job_ids),
        "background": get_job_manager().stats(),
        "caches": agent.runtime_context.cache_stats(),
    }


def _growth_percent(start, end):
    return round(((end - start) / max(1, start)) * 100, 4)


def _evaluate(warm, end):
    rss_growth = _growth_percent(warm["rss_bytes"], end["rss_bytes"])
    allocation_growth = _growth_percent(
        warm["tracemalloc_current_bytes"], end["tracemalloc_current_bytes"]
    )
    fd_growth = None
    if warm["file_descriptors"] is not None and end["file_descriptors"] is not None:
        fd_growth = end["file_descriptors"] - warm["file_descriptors"]
    checks = {
        "rss_growth_under_10_percent": rss_growth < 10,
        "tracemalloc_growth_under_10_percent": allocation_growth < 10,
        "message_bound_held": end["messages"] <= MAX_RETAINED_MESSAGES,
        "background_bound_held": (
            end["background"]["finished"] <= DEFAULT_MAX_FINISHED_JOBS
        ),
        "injected_identifier_bound_held": (
            end["injected_job_ids"] <= DEFAULT_MAX_FINISHED_JOBS
        ),
        "thread_count_stable": end["threads"] <= warm["threads"],
        "subprocess_count_stable": end["subprocesses"] <= warm["subprocesses"],
        "file_descriptors_stable": fd_growth is None or fd_growth <= 2,
        "sqlite_connections_stable": end["sqlite_connections"] <= warm["sqlite_connections"],
    }
    return checks, rss_growth, allocation_growth, fd_growth


def run_soak(turns=DEFAULT_TURNS, warmup_turns=DEFAULT_WARMUP_TURNS):
    """Run warm-up plus the requested mocked turns and return a JSON-safe report."""
    reset_job_manager()
    agent = SoakConversation()
    tracemalloc.start()
    baseline = _snapshot(agent)
    for turn in range(warmup_turns):
        _run_mock_turn(agent, turn)
    warm = _snapshot(agent)
    for turn in range(warmup_turns, warmup_turns + turns):
        _run_mock_turn(agent, turn)
    end = _snapshot(agent)
    checks, rss_growth, allocation_growth, fd_growth = _evaluate(warm, end)
    tracemalloc.stop()
    return {
        "schema_version": 1,
        "turns_after_warmup": turns,
        "warmup_turns": warmup_turns,
        "environment": {
            "os": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "snapshots": {"baseline": baseline, "warm": warm, "end": end},
        "growth": {
            "rss_percent_after_warmup": rss_growth,
            "tracemalloc_current_percent_after_warmup": allocation_growth,
            "file_descriptors_after_warmup": fd_growth,
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=DEFAULT_TURNS)
    parser.add_argument("--warmup-turns", type=int, default=DEFAULT_WARMUP_TURNS)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = run_soak(arguments.turns, arguments.warmup_turns)
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if arguments.output:
        arguments.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
