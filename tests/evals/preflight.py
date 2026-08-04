"""Paid-run preflight and immutable provenance for behavioural evals."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .candidates import CANDIDATE_NAMES, get_candidate
from .cases import get_cases
from .fake_tools import FakeToolRunner

MANIFEST_SCHEMA_VERSION = 1
MAX_REPETITIONS = 20
MAX_WORKERS = 32
MAX_ITERATIONS = 50
MAX_REQUEST_TIMEOUT_SECONDS = 600.0
SUPPORTED_PROVIDERS = ("claude", "openai", "openrouter")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVAL_SOURCE_FILES = (
    "candidates.py",
    "cases.py",
    "fake_tools.py",
    "harness.py",
    "preflight.py",
    "run_evals.py",
    "scoring.py",
)


@dataclass(frozen=True)
class EvalPreflight:
    """Validated inputs needed to run a behavioural matrix."""

    candidate_names: tuple[str, ...]
    cases: tuple[Any, ...]
    prompts: dict[str, str]
    manifest: dict[str, Any]


def prepare_preflight(arguments: Any, provider: str, model: str) -> EvalPreflight:
    """Validate a run and build its manifest without contacting a provider."""
    _validate_selection(arguments, provider, model)
    candidate_names = _parse_candidate_names(arguments.candidates)
    cases = _select_cases(arguments)
    cost_limit = _validate_limits(arguments)
    prompts = {name: get_candidate(name)[1] for name in candidate_names}
    manifest = _build_manifest(
        arguments,
        provider,
        model,
        candidate_names,
        cases,
        prompts,
        cost_limit,
    )
    return EvalPreflight(candidate_names, cases, prompts, manifest)


def print_preflight(preflight: EvalPreflight) -> None:
    """Print bounded execution details without sensitive configuration."""
    execution = preflight.manifest["execution"]
    print(
        "Preflight: "
        f"runs={execution['case_runs']} "
        f"logical_requests<={execution['logical_request_limit']} "
        f"provider_attempts<={execution['provider_attempt_limit']} "
        f"workers={execution['workers']} "
        f"timeout={execution['request_timeout_seconds']}s "
        f"cost_cap=${execution['max_cost_usd'] or 'dry-run'}"
    )
    print(f"Artifact: {preflight.manifest['artifact_digest']}")


def _parse_candidate_names(raw_names: str) -> tuple[str, ...]:
    names = tuple(name.strip().upper() for name in raw_names.split(",") if name.strip())
    if not names:
        raise SystemExit("At least one candidate is required.")
    if len(names) != len(set(names)):
        raise SystemExit("Candidate names must not be repeated.")
    unknown = [name for name in names if name not in CANDIDATE_NAMES]
    if unknown:
        raise SystemExit(f"Unknown candidate(s): {', '.join(unknown)}")
    return names


def _validate_selection(arguments: Any, provider: str, model: str) -> None:
    if provider not in SUPPORTED_PROVIDERS:
        raise SystemExit(f"Unsupported provider: {provider}")
    if not isinstance(model, str) or not model.strip():
        raise SystemExit("A non-empty model identifier is required.")
    if arguments.no_rubric and arguments.grader_model:
        raise SystemExit("--grader-model cannot be combined with --no-rubric.")


def _select_cases(arguments: Any) -> tuple[Any, ...]:
    case_ids = arguments.cases.split(",") if arguments.cases else None
    cases = tuple(get_cases(group=arguments.group, case_ids=case_ids))
    if not cases:
        raise SystemExit("No cases matched the filter.")
    return cases


def _validate_limits(arguments: Any) -> str | None:
    _validate_integer("repetitions", arguments.reps, 1, MAX_REPETITIONS)
    _validate_integer("workers", arguments.workers, 1, MAX_WORKERS)
    _validate_integer("max iterations", arguments.max_iterations, 1, MAX_ITERATIONS)
    timeout = arguments.request_timeout_seconds
    if not math.isfinite(timeout) or not 0 < timeout <= MAX_REQUEST_TIMEOUT_SECONDS:
        raise SystemExit(
            f"Request timeout must be between 0 and {MAX_REQUEST_TIMEOUT_SECONDS:g} seconds."
        )
    if arguments.dry_run:
        return _optional_cost_limit(arguments.max_cost_usd)
    if arguments.max_cost_usd is None:
        raise SystemExit("Paid evals require an explicit positive --max-cost-usd limit.")
    return _required_cost_limit(arguments.max_cost_usd)


def _validate_integer(name: str, value: int, minimum: int, maximum: int) -> None:
    if minimum <= value <= maximum:
        return
    raise SystemExit(f"{name.capitalize()} must be between {minimum} and {maximum}.")


def _optional_cost_limit(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    return _required_cost_limit(raw_value)


def _required_cost_limit(raw_value: str) -> str:
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        raise SystemExit("--max-cost-usd must be a positive finite number.") from None
    if not math.isfinite(value) or value <= 0:
        raise SystemExit("--max-cost-usd must be a positive finite number.")
    return format(value, ".12g")


def _build_manifest(
    arguments: Any,
    provider: str,
    model: str,
    candidate_names: tuple[str, ...],
    cases: tuple[Any, ...],
    prompts: dict[str, str],
    cost_limit: str | None,
) -> dict[str, Any]:
    artifact_inputs = _artifact_inputs(candidate_names, cases, prompts)
    logical_requests = _logical_request_limit(arguments, candidate_names, cases)
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifact_digest": _digest_json(artifact_inputs),
        "artifacts": artifact_inputs,
        "repository": _repository_state(),
        "runtime": {"python": sys.version.split()[0]},
        "selection": _selection(arguments, provider, model, candidate_names),
        "execution": _execution(
            arguments,
            candidate_names,
            cases,
            logical_requests,
            cost_limit,
        ),
    }


def _artifact_inputs(
    candidate_names: tuple[str, ...],
    cases: tuple[Any, ...],
    prompts: dict[str, str],
) -> dict[str, Any]:
    schemas = FakeToolRunner(REPOSITORY_ROOT).schemas()
    return {
        "prompt_digests": {name: _digest_text(prompts[name]) for name in candidate_names},
        "case_set_digest": _digest_json([asdict(case) for case in cases]),
        "tool_schema_digest": _digest_json(schemas),
        "harness_digest": _digest_files(EVAL_SOURCE_FILES),
    }


def _selection(
    arguments: Any,
    provider: str,
    model: str,
    candidate_names: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": model,
        "grader_model": None if arguments.no_rubric else arguments.grader_model or model,
        "candidates": list(candidate_names),
    }


def _execution(
    arguments: Any,
    candidate_names: tuple[str, ...],
    cases: tuple[Any, ...],
    logical_requests: int,
    cost_limit: str | None,
) -> dict[str, Any]:
    case_runs = len(candidate_names) * len(cases) * arguments.reps
    return {
        "case_runs": case_runs,
        "repetitions": arguments.reps,
        "workers": arguments.workers,
        "max_iterations": arguments.max_iterations,
        "request_timeout_seconds": arguments.request_timeout_seconds,
        "logical_request_limit": logical_requests,
        "provider_attempt_limit": logical_requests * 4,
        "max_cost_usd": cost_limit,
        "dry_run": arguments.dry_run,
    }


def _logical_request_limit(
    arguments: Any,
    candidate_names: tuple[str, ...],
    cases: tuple[Any, ...],
) -> int:
    case_runs = len(candidate_names) * len(cases) * arguments.reps
    candidate_requests = case_runs * arguments.max_iterations
    if arguments.no_rubric:
        return candidate_requests
    rubric_cases = sum(1 for case in cases if case.rubric)
    return candidate_requests + (len(candidate_names) * rubric_cases * arguments.reps)


def _repository_state() -> dict[str, Any]:
    return {
        "commit": _git_output("rev-parse", "HEAD"),
        "branch": _git_output("branch", "--show-current"),
        "dirty": bool(_git_output("status", "--porcelain")),
    }


def _git_output(*arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPOSITORY_ROOT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _digest_files(relative_paths: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    source_dir = Path(__file__).resolve().parent
    for relative_path in relative_paths:
        digest.update(relative_path.encode("utf-8"))
        digest.update((source_dir / relative_path).read_bytes())
    return digest.hexdigest()


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _digest_text(encoded)
