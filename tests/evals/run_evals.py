"""Run the behavioural eval matrix and report the release gates.

    python -m tests.evals.run_evals                     # both candidates, 3 reps
    python -m tests.evals.run_evals --candidates B      # current prompt only
    python -m tests.evals.run_evals --cases S01,S03     # one group of ids

Live model calls are made against the provider and model given on the command
line, defaulting to the saved primary selection. Nothing here writes outside
the temporary project directory each run creates.
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .candidates import CANDIDATE_NAMES
from .harness import DEFAULT_MAX_ITERATIONS, run_case
from .preflight import EvalPreflight, prepare_preflight, print_preflight
from .scoring import evaluate_gates, grade_clarity, score_run, summarise

DEFAULT_REPETITIONS = 3
DEFAULT_WORKERS = 4
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0


def parse_arguments(argv=None):
    """Parse the command line."""
    parser = argparse.ArgumentParser(description="Run the RadSim behavioural eval matrix")
    parser.add_argument(
        "--candidates",
        default=",".join(CANDIDATE_NAMES),
        help="Comma-separated candidates to run: A (pinned baseline), B (current)",
    )
    parser.add_argument("--reps", type=int, default=DEFAULT_REPETITIONS, help="Repetitions per case")
    parser.add_argument("--group", default=None, help="Run one group only")
    parser.add_argument("--cases", default=None, help="Comma-separated case ids")
    parser.add_argument("--provider", default=None, help="Provider override")
    parser.add_argument("--model", default=None, help="Model override")
    parser.add_argument("--grader-model", default=None, help="Model used for rubric grading")
    parser.add_argument(
        "--effort",
        default="shipping",
        help="Reasoning effort or 'shipping' for the configured model default",
    )
    parser.add_argument("--grader-effort", default=None, help="Optional grader reasoning effort")
    parser.add_argument("--no-rubric", action="store_true", help="Skip model-graded clarity")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print bounds without API access")
    parser.add_argument("--max-cost-usd", default=None, help="Required hard spend cap for paid runs")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Parallel runs")
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        help="Timeout for each provider request",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=DEFAULT_MAX_ITERATIONS,
        help="Tool loop iterations per run",
    )
    parser.add_argument("--output", default="eval_results.json", help="Where to write results")
    return parser.parse_args(argv)


def resolve_model_selection(provider, model):
    """Resolve provider and model without reading a credential."""
    from radsim.config import load_env_file

    saved = load_env_file()
    provider = provider or saved.get("provider")
    model = model or saved.get("model")
    if not provider or not model:
        raise SystemExit("No provider/model configured. Pass --provider and --model.")

    return provider, model


def resolve_api_key(provider):
    """Read the selected provider credential only after preflight passes."""
    from radsim.config import get_provider_api_key

    api_key = get_provider_api_key(provider)
    if not api_key:
        raise SystemExit(f"No API key available for provider '{provider}'.")
    return api_key


def build_client(provider, api_key, model, reasoning_effort, request_timeout_seconds):
    """Create one API client for the whole run."""
    from radsim.api_client import create_client

    return create_client(
        provider,
        api_key,
        model,
        reasoning_effort=reasoning_effort,
        timeout=request_timeout_seconds,
    )


def run_matrix(arguments, client, grader_client, preflight: EvalPreflight):
    """Run every candidate, case, and repetition. Returns (records, scores)."""
    jobs = [
        (candidate, case, repetition)
        for candidate in preflight.candidate_names
        for case in preflight.cases
        for repetition in range(1, arguments.reps + 1)
    ]

    print(f"Running {len(jobs)} case runs ({len(preflight.cases)} cases)\n")

    def run_one(job):
        candidate, case, repetition = job
        record = run_case(
            case,
            candidate,
            preflight.prompts[candidate],
            client,
            max_iterations=arguments.max_iterations,
        )
        record.repetition = repetition
        score = score_run(case, record)
        if case.rubric and not arguments.no_rubric:
            score.rubric_score = grade_clarity(case, record, grader_client)
        _print_progress(candidate, case, repetition, score)
        return record, score

    with ThreadPoolExecutor(max_workers=max(1, arguments.workers)) as executor:
        results = list(executor.map(run_one, jobs))

    return [record for record, _score in results], [score for _record, score in results]


def _print_progress(candidate, case, repetition, score):
    """Print one line per finished run."""
    if not score.hard_security_pass:
        verdict = "SECURITY FAILURE: " + "; ".join(score.security_failures)
    elif score.error:
        verdict = f"error: {score.error[:60]}"
    else:
        verdict = (
            f"tool={'ok' if score.tool_choice_correct else 'wrong'} "
            f"done={'yes' if score.completed else 'no'} "
            f"honest={'yes' if score.honest else 'no'}"
        )
    print(f"  [{candidate}] {case.id} rep{repetition}  {verdict}")


def report(scores, records, output_path, manifest):
    """Print the gate table and write the full results.

    The written file keeps each run's answer and tool arguments, because a
    failed case is only actionable once you can see what the model actually
    asked for.
    """
    by_candidate = {}
    for score in scores:
        by_candidate.setdefault(score.candidate, []).append(score)

    summaries = {name: summarise(items) for name, items in by_candidate.items()}

    print("\nRates by candidate")
    for name, summary in sorted(summaries.items()):
        rubric = summary["rubric_average"]
        print(
            f"  {name}: runs={summary['runs']} "
            f"tool_choice={summary['tool_choice_rate']:.1%} "
            f"completion={summary['completion_rate']:.1%} "
            f"honesty={summary['honesty_rate']:.1%} "
            f"rubric={'n/a' if rubric is None else f'{rubric:.1%}'} "
            f"security_failures={len(summary['security_failures'])}"
        )

    if "B" not in summaries:
        print("\nCandidate B was not run, so the release gates do not apply.")
        _write_results(output_path, manifest, summaries, [], scores, records)
        return summaries, []

    gates = evaluate_gates(summaries.get("A"), summaries["B"])
    print("\nRelease gates (candidate B)")
    for gate in gates:
        print(f"  [{'PASS' if gate['passed'] else 'FAIL'}] {gate['name']} — {gate['detail']}")

    for failure in summaries["B"]["security_failures"]:
        print(f"  ! {failure['case']} rep{failure['repetition']}: {'; '.join(failure['failures'])}")

    _write_results(output_path, manifest, summaries, gates, scores, records)
    print(f"\nWrote {output_path}")
    return summaries, gates


def _write_results(output_path, manifest, summaries, gates, scores, records):
    """Write summaries, gates, scores, and full run transcripts."""
    Path(output_path).write_text(
        json.dumps(
            {
                "manifest": manifest,
                "summaries": summaries,
                "gates": gates,
                "scores": [score.as_dict() for score in scores],
                "runs": [record.as_dict() for record in records],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main(argv=None):
    """Entry point. Returns a process exit code."""
    arguments = parse_arguments(argv)
    provider, model = resolve_model_selection(arguments.provider, arguments.model)
    preflight = prepare_preflight(arguments, provider, model)
    print(f"Provider: {provider}  Model: {model}")
    print_preflight(preflight)

    if arguments.dry_run:
        return 0

    api_key = resolve_api_key(provider)
    client = build_client(
        provider,
        api_key,
        model,
        preflight.reasoning_effort,
        arguments.request_timeout_seconds,
    )
    grader_model = arguments.grader_model or model
    needs_grader_client = (
        grader_model != model or preflight.grader_effort != preflight.reasoning_effort
    )
    grader_client = (
        build_client(
            provider,
            api_key,
            grader_model,
            preflight.grader_effort,
            arguments.request_timeout_seconds,
        )
        if needs_grader_client
        else client
    )

    records, scores = run_matrix(arguments, client, grader_client, preflight)
    _summaries, gates = report(scores, records, arguments.output, preflight.manifest)

    return 0 if gates and all(gate["passed"] for gate in gates) else 1


if __name__ == "__main__":
    sys.exit(main())
