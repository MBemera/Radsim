"""Bounded parallel execution of proven-independent read-only tool calls.

A provider emits every tool call in a round together, so no call in a round can
consume another's result. That removes one class of dependency but not the
others, so a call runs concurrently only when all of these hold:

- its name is in :data:`PARALLEL_SAFE_TOOLS`, an explicit allowlist
- the tool is read-only and performs no implicit mutation
- it needs no user confirmation, checked before dispatch rather than during it
- its arguments parsed cleanly
- no order-sensitive hook or extension is registered
- it sits in the leading run of the round, so no earlier call can have mutated
  the state it reads

Results are returned by original index, never in completion order, so the
provider always sees the order it asked for.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

PARALLEL_TOOLS_ENV_VAR = "RADSIM_PARALLEL_TOOLS"
MAX_PARALLEL_WORKERS = 4
MIN_PARALLEL_GROUP = 2

_TRUTHY_VALUES = {"1", "true", "yes", "on"}

# Read-only inspection and repository metadata only. Writes, shell, tests, git
# mutations, database work, and anything needing confirmation are absent by
# design and must stay absent.
PARALLEL_SAFE_TOOLS = frozenset(
    {
        "find_definition",
        "find_references",
        "get_project_info",
        "git_branch",
        "git_diff",
        "git_log",
        "git_status",
        "glob_files",
        "grep_search",
        "list_dependencies",
        "list_directory",
        "read_file",
        "read_many_files",
        "repo_map",
        "search_files",
    }
)


@dataclass(frozen=True)
class ParallelPlan:
    """Which calls in a round may run together, and why the rest may not."""

    indexes: tuple[int, ...]
    worker_count: int
    skipped_reason: str

    @property
    def is_parallel(self) -> bool:
        """Return whether the round has a group worth dispatching."""
        return len(self.indexes) >= MIN_PARALLEL_GROUP


def parallel_tools_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether bounded parallel tool execution is switched on."""
    source = os.environ if environ is None else environ
    return source.get(PARALLEL_TOOLS_ENV_VAR, "").strip().lower() in _TRUTHY_VALUES


def plan_parallel_group(
    tool_uses: Sequence[Mapping[str, Any]],
    *,
    needs_confirmation: Callable[[str, Any], bool],
    hooks_present: bool = False,
    environ: Mapping[str, str] | None = None,
    max_workers: int = MAX_PARALLEL_WORKERS,
) -> ParallelPlan:
    """Choose the leading run of calls that is safe to execute concurrently."""
    if not parallel_tools_enabled(environ):
        return _skipped("disabled")
    if hooks_present:
        return _skipped("order_sensitive_hooks")

    indexes: list[int] = []
    for index, tool_use in enumerate(tool_uses):
        if not _is_parallel_safe(tool_use):
            break
        if needs_confirmation(tool_use["name"], tool_use["input"]):
            break
        indexes.append(index)

    if len(indexes) < MIN_PARALLEL_GROUP:
        return _skipped("group_too_small")
    return ParallelPlan(tuple(indexes), min(max(1, int(max_workers)), len(indexes)), "")


def run_parallel_group(
    execute: Callable[[str, Any], Any],
    tool_uses: Sequence[Mapping[str, Any]],
    plan: ParallelPlan,
    *,
    interrupted: threading.Event | None = None,
) -> dict[int, tuple[Any, float]]:
    """Run the planned group and return (result, duration_ms) by original index.

    An interrupt stops further dispatch and cancels work that has not started.
    Work already running is allowed to finish: a Python thread cannot be killed
    safely, and abandoning one would leave a tool_use with no tool_result and
    corrupt the conversation.
    """
    results: dict[int, tuple[Any, float]] = {}
    if not plan.is_parallel:
        return results

    with ThreadPoolExecutor(
        max_workers=plan.worker_count,
        thread_name_prefix="radsim-tool",
    ) as pool:
        futures = {}
        for index in plan.indexes:
            if _is_interrupted(interrupted):
                break
            tool_use = tool_uses[index]
            future = pool.submit(_timed_call, execute, tool_use["name"], tool_use["input"])
            futures[future] = index

        for future, index in futures.items():
            if _is_interrupted(interrupted) and future.cancel():
                continue
            results[index] = future.result()
    return results


def _timed_call(
    execute: Callable[[str, Any], Any],
    tool_name: str,
    tool_input: Any,
) -> tuple[Any, float]:
    started_at = time.perf_counter()
    result = execute(tool_name, tool_input)
    return result, (time.perf_counter() - started_at) * 1000


def _is_parallel_safe(tool_use: Mapping[str, Any]) -> bool:
    """Return whether one call is allowlisted and has usable arguments."""
    if tool_use.get("name") not in PARALLEL_SAFE_TOOLS:
        return False
    tool_input = tool_use.get("input")
    if not isinstance(tool_input, dict):
        return False
    return "__parse_error__" not in tool_input


def _is_interrupted(interrupted: threading.Event | None) -> bool:
    return interrupted is not None and interrupted.is_set()


def _skipped(reason: str) -> ParallelPlan:
    return ParallelPlan((), 0, reason)
