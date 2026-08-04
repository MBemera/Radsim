"""Run the behavioural eval matrix and report the release gates.

    python -m tests.evals.run_evals                     # both candidates, 3 reps
    python -m tests.evals.run_evals --candidates B      # current prompt only
    python -m tests.evals.run_evals --cases S01,S03     # one group of ids

Live model calls are made against the provider and model given on the command
line, defaulting to the saved primary selection. Case tools stay inside a
temporary project; sanitized run artifacts go to the private result directory.
"""

import argparse
import random
import sys

from .budget import BudgetedEvalClient, EvalCostBudget
from .cache_observability import (
    print_cache_observability,
    run_jobs_with_natural_priming,
    split_cache_priming_jobs,
    summarise_cache_observability,
)
from .candidates import CANDIDATE_NAMES
from .harness import DEFAULT_MAX_ITERATIONS, run_case
from .preflight import EvalPreflight, prepare_preflight, print_preflight
from .profiles import (
    PROFILE_NAMES,
    ReusedBaseline,
    apply_profile,
    describe_profile,
    load_reused_baseline,
)
from .results import write_eval_result
from .scoring import (
    evaluate_gates,
    grade_clarity,
    paired_completion_difference,
    score_run,
    summarise,
)
from .tool_choice_analysis import analyse_tool_choice_failures, print_tool_choice_analysis

DEFAULT_CANDIDATES = ",".join(CANDIDATE_NAMES)
DEFAULT_REPETITIONS = 3
DEFAULT_WORKERS = 4
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0
DEFAULT_HARNESS_SEED = 20260804
DEFAULT_TEMPERATURE = 0.0
DEFAULT_TOP_P = 1.0


def parse_arguments(argv=None):
    """Parse the command line."""
    parser = argparse.ArgumentParser(description="Run the RadSim behavioural eval matrix")
    parser.add_argument(
        "--candidates",
        default=DEFAULT_CANDIDATES,
        help="Comma-separated candidates to run: A (pinned baseline), B (current)",
    )
    parser.add_argument("--reps", type=int, default=DEFAULT_REPETITIONS, help="Repetitions per case")
    parser.add_argument("--group", default=None, help="Run one group only")
    parser.add_argument("--cases", default=None, help="Comma-separated case ids")
    parser.add_argument(
        "--case-set",
        choices=("development", "holdout", "release"),
        default="release",
        help="Case profile; development excludes the tuning holdout",
    )
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
    parser.add_argument(
        "--max-cost-usd",
        default=None,
        help="Required provider-spend stop threshold; in-flight calls may exceed it",
    )
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Parallel runs")
    parser.add_argument("--seed", type=int, default=DEFAULT_HARNESS_SEED, help="Job-order seed")
    parser.add_argument(
        "--sampling-seed",
        type=int,
        default=DEFAULT_HARNESS_SEED,
        help="Best-effort provider sampling seed",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help="Candidate and grader sampling temperature",
    )
    parser.add_argument(
        "--top-p",
        type=float,
        default=DEFAULT_TOP_P,
        help="Candidate and grader nucleus-sampling threshold",
    )
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
    parser.add_argument(
        "--result-dir",
        default="eval_results",
        help="Private directory for unique result artifacts",
    )
    parser.add_argument(
        "--profile",
        choices=PROFILE_NAMES,
        default=None,
        help=(
            "release: both candidates measured live, full gates. "
            "commit: candidate B only against a stored compatible baseline; "
            "cheaper, provisional, not release evidence."
        ),
    )
    arguments = parser.parse_args(argv)
    apply_profile(arguments, DEFAULT_CANDIDATES, DEFAULT_REPETITIONS)
    return arguments


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


def capture_pricing(provider, model):
    """Capture one immutable price record before any paid eval request."""
    from radsim.config import get_model_pricing

    return get_model_pricing(model, provider, allow_network=True)


def run_matrix(arguments, client, grader_client, preflight: EvalPreflight):
    """Run every candidate, case, and repetition. Returns (records, scores)."""
    jobs = build_jobs(
        preflight.candidate_names,
        preflight.cases,
        arguments.reps,
        arguments.seed,
    )
    priming_jobs, remaining_jobs = split_cache_priming_jobs(jobs)
    _record_job_execution(preflight, jobs, priming_jobs)

    print(f"Running {len(jobs)} case runs ({len(preflight.cases)} cases)\n")

    def run_one(job):
        return _run_one_job(job, arguments, client, grader_client, preflight)

    results = run_jobs_with_natural_priming(
        priming_jobs,
        remaining_jobs,
        run_one,
        arguments.workers,
    )

    return [record for record, _score in results], [score for _record, score in results]


def _job_name(job) -> str:
    candidate, case, repetition = job
    return f"{case.id}:rep{repetition}:{candidate}"


def _record_job_execution(preflight: EvalPreflight, jobs, priming_jobs) -> None:
    preflight.manifest["execution"]["job_order"] = [_job_name(job) for job in jobs]
    preflight.manifest["execution"]["cache_priming"]["scored_jobs"] = [
        _job_name(job) for _index, job in priming_jobs
    ]


def _run_one_job(job, arguments, client, grader_client, preflight):
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


def build_jobs(candidate_names, cases, repetitions, seed):
    """Build deterministic adjacent candidate pairs in seeded case order."""
    random_generator = random.Random(seed)
    case_repetitions = [
        (case, repetition)
        for case in cases
        for repetition in range(1, repetitions + 1)
    ]
    random_generator.shuffle(case_repetitions)
    jobs = []
    for case, repetition in case_repetitions:
        pair_order = list(candidate_names)
        random_generator.shuffle(pair_order)
        jobs.extend((candidate, case, repetition) for candidate in pair_order)
    return jobs


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


def report(scores, records, result_directory, manifest, baseline=None):
    """Print the gate table and write the full results.

    The written file keeps each run's answer and tool arguments, because a
    failed case is only actionable once you can see what the model actually
    asked for. A reused candidate A is folded in here, never re-measured, and
    every line that depends on it says so.
    """
    baseline = baseline or ReusedBaseline()
    scores = list(scores) + list(baseline.scores)

    by_candidate = {}
    for score in scores:
        by_candidate.setdefault(score.candidate, []).append(score)

    summaries = {name: summarise(items) for name, items in by_candidate.items()}
    cache_observability = summarise_cache_observability(records)
    tool_choice_analysis = analyse_tool_choice_failures(
        [score.as_dict() for score in scores],
        [record.as_dict() for record in records],
    )

    print("\nRates by candidate")
    for name, summary in sorted(summaries.items()):
        _print_candidate_summary(name, summary)
    print_cache_observability(cache_observability)
    print_tool_choice_analysis(tool_choice_analysis)

    if "B" not in summaries:
        print("\nCandidate B was not run, so the release gates do not apply.")
        result_path = _write_results(
            result_directory,
            manifest,
            summaries,
            [],
            scores,
            records,
            cache_observability=cache_observability,
            tool_choice_analysis=tool_choice_analysis,
        )
        print(f"\nWrote {result_path}")
        return summaries, []

    paired_completion = paired_completion_difference(scores)
    comparisons = {
        "paired_completion": paired_completion,
        "baseline_reused": baseline.available,
        "baseline_provenance": baseline.provenance,
        "provisional": baseline.available,
    }
    gates = evaluate_gates(summaries.get("A"), summaries["B"], paired_completion)
    heading = "Release gates (candidate B)"
    if baseline.available:
        heading = "Provisional gates (candidate B vs reused baseline A)"
    print(f"\n{heading}")
    for gate in gates:
        print(f"  [{'PASS' if gate['passed'] else 'FAIL'}] {gate['name']} — {gate['detail']}")

    for failure in summaries["B"]["security_failures"]:
        print(f"  ! {failure['case']} rep{failure['repetition']}: {'; '.join(failure['failures'])}")

    result_path = _write_results(
        result_directory,
        manifest,
        summaries,
        gates,
        scores,
        records,
        comparisons,
        cache_observability,
        tool_choice_analysis,
    )
    print(f"\nWrote {result_path}")
    return summaries, gates


def _print_candidate_summary(name, summary):
    """Print sample provenance, failures, rates and confidence intervals."""
    print(
        f"  {name}: samples={summary['quality_samples']}/{summary['runs']} "
        f"live={summary['live_samples']} reused={summary['reused_samples']} "
        f"failed={summary['failed_samples']} ungraded={summary['ungraded_samples']} "
        f"security_failures={len(summary['security_failures'])}"
    )
    intervals = summary["confidence_intervals"]
    rubric = summary["rubric_average"]
    print(
        f"     tool_choice={summary['tool_choice_rate']:.1%} "
        f"{_format_interval(intervals['tool_choice_correct'])} "
        f"completion={summary['completion_rate']:.1%} "
        f"{_format_interval(intervals['completed'])} "
        f"honesty={summary['honesty_rate']:.1%} "
        f"{_format_interval(intervals['honest'])} "
        f"rubric={'n/a' if rubric is None else f'{rubric:.1%}'} "
        f"{_format_interval(intervals['rubric_average'])}"
    )


def _format_interval(interval):
    if not interval:
        return "[95% CI n/a]"
    return f"[95% CI {interval['low']:.1%}-{interval['high']:.1%}]"


def _write_results(
    result_directory,
    manifest,
    summaries,
    gates,
    scores,
    records,
    comparisons=None,
    cache_observability=None,
    tool_choice_analysis=None,
):
    """Write summaries, gates, scores, and full run transcripts."""
    payload = {
        "manifest": manifest,
        "summaries": summaries,
        "gates": gates,
        "comparisons": comparisons or {},
        "cache_observability": cache_observability or {},
        "tool_choice_analysis": tool_choice_analysis or {},
        "scores": [score.as_dict() for score in scores],
        "runs": [record.as_dict() for record in records],
    }
    return write_eval_result(result_directory, payload)


def main(argv=None):
    """Entry point. Returns a process exit code."""
    arguments = parse_arguments(argv)
    provider, model = resolve_model_selection(arguments.provider, arguments.model)
    preflight = prepare_preflight(arguments, provider, model)
    preflight.manifest["execution"]["profile"] = arguments.profile
    print(f"Provider: {provider}  Model: {model}")
    print_preflight(preflight)

    baseline = load_reused_baseline(
        arguments.profile,
        arguments.result_dir,
        preflight.manifest,
    )
    preflight.manifest["execution"]["reused_baseline"] = {
        "used": baseline.available,
        "provenance": baseline.provenance,
        "unavailable_reason": baseline.unavailable_reason,
    }
    for line in describe_profile(arguments.profile, baseline):
        print(line)

    if arguments.dry_run:
        return 0

    api_key = resolve_api_key(provider)
    budget = EvalCostBudget(preflight.manifest["execution"]["max_cost_usd"])
    raw_client = build_client(
        provider,
        api_key,
        model,
        preflight.reasoning_effort,
        arguments.request_timeout_seconds,
    )
    grader_model = arguments.grader_model or model
    candidate_pricing = capture_pricing(provider, model)
    grader_pricing = (
        candidate_pricing
        if grader_model == model
        else capture_pricing(provider, grader_model)
    )
    preflight.manifest["pricing_snapshots"] = {
        "candidate": candidate_pricing.as_dict() if candidate_pricing else None,
        "grader": grader_pricing.as_dict() if grader_pricing else None,
    }
    needs_grader_client = (
        grader_model != model or preflight.grader_effort != preflight.reasoning_effort
    )
    raw_grader_client = (
        build_client(
            provider,
            api_key,
            grader_model,
            preflight.grader_effort,
            arguments.request_timeout_seconds,
        )
        if needs_grader_client
        else raw_client
    )
    preflight.manifest["request_option_snapshots"] = {
        "candidate": raw_client.request_options_snapshot(preflight.request_options),
        "grader": raw_grader_client.request_options_snapshot(preflight.request_options),
    }
    client = BudgetedEvalClient(
        raw_client,
        budget,
        candidate_pricing,
        preflight.request_options,
    )
    grader_client = (
        BudgetedEvalClient(
            raw_grader_client,
            budget,
            grader_pricing,
            preflight.request_options,
        )
        if needs_grader_client
        else client
    )

    records, scores = run_matrix(arguments, client, grader_client, preflight)
    budget_result = budget.snapshot()
    preflight.manifest["execution"]["budget_result"] = budget_result
    print(
        "Budget: "
        f"reported=${budget_result['provider_reported_cost_usd']} "
        f"cap=${budget_result['configured_cap_usd']} "
        f"cost_coverage={budget_result['responses_with_reported_cost']}/"
        f"{budget_result['responses_received']} "
        f"logical_requests={budget_result['requests_started']} "
        f"provider_attempts={budget_result['provider_attempts']}"
    )
    _summaries, gates = report(
        scores,
        records,
        arguments.result_dir,
        preflight.manifest,
        baseline,
    )

    return 0 if gates and all(gate["passed"] for gate in gates) else 1


if __name__ == "__main__":
    sys.exit(main())
