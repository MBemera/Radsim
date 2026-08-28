"""Select changed mutation targets and enforce mutation-score policy."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

TIER_ONE_PATHS = {
    "radsim/agent_api.py",
    "radsim/agent_policy.py",
    "radsim/bounded_cache.py",
    "radsim/context_budget.py",
    "radsim/learning/buffer.py",
    "radsim/learning/retrieval.py",
    "radsim/learning/store.py",
    "radsim/performance.py",
    "radsim/prompt_cache.py",
    "radsim/rate_limiter.py",
    "radsim/response_validator.py",
    "radsim/safety.py",
    "radsim/tool_router.py",
    "radsim/tool_schema.py",
    "radsim/tool_scheduler.py",
    "radsim/tools/command_policy.py",
    "radsim/tools/validation.py",
}
DEFAULT_SMOKE_TARGET = "radsim.performance.*"
FAILED_STATUSES = ("survived", "no_tests", "suspicious", "timeout", "segfault")


def changed_targets(base: str, head: str) -> list[str]:
    """Return mutmut module patterns for changed Tier 1 files."""
    completed = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    paths = {line.strip() for line in completed.stdout.splitlines() if line.strip()}
    targets = [_path_to_pattern(path) for path in sorted(paths & TIER_ONE_PATHS)]
    return targets or [DEFAULT_SMOKE_TARGET]


def mutation_score(stats: dict) -> tuple[float, int, int]:
    """Return score, killed count, and policy denominator."""
    killed = _nonnegative_int(stats.get("killed"))
    failed = sum(_nonnegative_int(stats.get(name)) for name in FAILED_STATUSES)
    denominator = killed + failed
    score = killed / denominator if denominator else 0.0
    return score, killed, denominator


def check_stats(path: Path, minimum: float, baseline_path: Path | None = None) -> int:
    """Print a bounded summary and return a CI-compatible exit code."""
    stats = json.loads(path.read_text(encoding="utf-8"))
    score, killed, denominator = mutation_score(stats)
    baseline_score = None
    if baseline_path is not None:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline_stats = baseline.get("stats", baseline)
        baseline_score, _, _ = mutation_score(baseline_stats)
        minimum = max(minimum, baseline_score)
    summary = {
        "baseline_score": round(baseline_score, 6) if baseline_score is not None else None,
        "killed": killed,
        "considered": denominator,
        "score": round(score, 6),
        "minimum": minimum,
        "survived": _nonnegative_int(stats.get("survived")),
        "no_tests": _nonnegative_int(stats.get("no_tests")),
        "timeout": _nonnegative_int(stats.get("timeout")),
    }
    print(json.dumps(summary, sort_keys=True))
    if stats.get("check_was_interrupted_by_user"):
        return 2
    if denominator == 0 or score < minimum:
        return 1
    return 0


def _path_to_pattern(path: str) -> str:
    return f"{Path(path).with_suffix('').as_posix().replace('/', '.')}.*"


def _nonnegative_int(value) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, parsed)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    targets_parser = subparsers.add_parser("targets")
    targets_parser.add_argument("--base", required=True)
    targets_parser.add_argument("--head", required=True)

    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("stats", type=Path)
    check_parser.add_argument("--minimum", type=float, default=0.0)
    check_parser.add_argument("--baseline", type=Path)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "targets":
        print("\n".join(changed_targets(args.base, args.head)))
        return 0
    if not 0 <= args.minimum <= 1:
        raise SystemExit("--minimum must be between 0 and 1")
    return check_stats(args.stats, args.minimum, args.baseline)


if __name__ == "__main__":
    raise SystemExit(main())
