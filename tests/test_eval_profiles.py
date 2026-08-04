"""Offline contracts for the release and commit eval profiles."""

from datetime import UTC, datetime, timedelta

import pytest

from tests.evals.profiles import (
    COMMIT_PROFILE,
    MAX_BASELINE_AGE_DAYS,
    PROFILE_REPETITIONS,
    RELEASE_PROFILE,
    ReusedBaseline,
    apply_profile,
    describe_profile,
    load_reused_baseline,
)
from tests.evals.results import write_eval_result
from tests.evals.run_evals import DEFAULT_CANDIDATES, DEFAULT_REPETITIONS, parse_arguments

REFERENCE_TIME = datetime(2026, 8, 4, tzinfo=UTC)


def build_manifest(created_at=None, artifact_digest="a" * 64):
    """Build a manifest that satisfies every reuse compatibility field."""
    return {
        "schema_version": 1,
        "created_at": (created_at or REFERENCE_TIME).isoformat(),
        "artifact_digest": artifact_digest,
        "artifacts": {
            "prompt_digests": {"A": "b" * 64, "B": "c" * 64},
            "case_set_digest": "d" * 64,
            "tool_schema_digest": "e" * 64,
            "harness_digest": "f" * 64,
        },
        "repository": {"commit": "9" * 40, "branch": "test", "dirty": False},
        "selection": {
            "provider": "openrouter",
            "model": "model/test",
            "grader_model": "model/test",
            "candidates": ["A", "B"],
            "reasoning_effort": "high",
            "grader_effort": "high",
        },
        "execution": {"max_iterations": 7, "seed": 20260804},
    }


def store_baseline(directory, manifest, candidates=("A", "B")):
    """Write one stored result containing samples for the given candidates."""
    scores = [
        {
            "case_id": "S01",
            "group": "safety",
            "candidate": candidate,
            "repetition": 1,
            "completed": True,
            "sample_source": "live",
        }
        for candidate in candidates
    ]
    write_eval_result(directory, {"manifest": manifest, "scores": scores, "runs": []})


class TestProfileShape:
    def test_release_fixes_both_candidates_and_three_reps(self):
        arguments = parse_arguments(["--profile", "release", "--max-cost-usd", "2.0"])

        assert arguments.candidates == "A,B"
        assert arguments.reps == PROFILE_REPETITIONS

    def test_commit_runs_candidate_b_only(self):
        arguments = parse_arguments(["--profile", "commit"])

        assert arguments.candidates == "B"
        assert arguments.reps == PROFILE_REPETITIONS

    def test_no_profile_leaves_the_defaults_alone(self):
        arguments = parse_arguments([])

        assert arguments.profile is None
        assert arguments.candidates == DEFAULT_CANDIDATES
        assert arguments.reps == DEFAULT_REPETITIONS

    @pytest.mark.parametrize(
        "argv",
        [
            ["--profile", "commit", "--candidates", "A"],
            ["--profile", "release", "--max-cost-usd", "2.0", "--candidates", "B"],
            ["--profile", "commit", "--reps", "1"],
        ],
    )
    def test_editing_a_profile_is_refused(self, argv):
        with pytest.raises(SystemExit, match="fixes --"):
            parse_arguments(argv)

    def test_unknown_profile_is_refused(self):
        arguments = parse_arguments([])
        arguments.profile = "whatever"

        with pytest.raises(SystemExit, match="Unknown profile"):
            apply_profile(arguments, DEFAULT_CANDIDATES, DEFAULT_REPETITIONS)


class TestReleaseProfileRefusals:
    def test_release_requires_an_explicit_cost_cap(self):
        with pytest.raises(SystemExit, match="requires an explicit --max-cost-usd"):
            parse_arguments(["--profile", "release"])

    def test_release_requires_the_cap_even_on_a_dry_run(self):
        with pytest.raises(SystemExit, match="requires an explicit --max-cost-usd"):
            parse_arguments(["--profile", "release", "--dry-run"])

    def test_release_never_reuses_a_stored_baseline(self, tmp_path):
        manifest = build_manifest()
        store_baseline(tmp_path / "results", manifest)

        baseline = load_reused_baseline(
            RELEASE_PROFILE,
            str(tmp_path / "results"),
            manifest,
            now=REFERENCE_TIME,
        )

        assert baseline.available is False
        assert baseline.unavailable_reason == "profile does not reuse baselines"


class TestCommitProfileReuse:
    def test_compatible_baseline_is_reused_and_marked(self, tmp_path):
        manifest = build_manifest()
        store_baseline(tmp_path / "results", manifest)

        baseline = load_reused_baseline(
            COMMIT_PROFILE,
            str(tmp_path / "results"),
            manifest,
            now=REFERENCE_TIME,
        )

        assert baseline.available is True
        assert [score.candidate for score in baseline.scores] == ["A"]
        assert all(score.sample_source == "reused" for score in baseline.scores)
        assert baseline.provenance["sample_count"] == 1
        assert baseline.provenance["commit"] == "9" * 40
        assert baseline.provenance["max_age_days"] == MAX_BASELINE_AGE_DAYS

    def test_stale_baseline_is_refused_with_its_age(self, tmp_path):
        stored_at = REFERENCE_TIME - timedelta(days=MAX_BASELINE_AGE_DAYS + 1)
        manifest = build_manifest(created_at=stored_at)
        store_baseline(tmp_path / "results", manifest)

        baseline = load_reused_baseline(
            COMMIT_PROFILE,
            str(tmp_path / "results"),
            manifest,
            now=REFERENCE_TIME,
        )

        assert baseline.available is False
        assert "days old" in baseline.unavailable_reason

    def test_incompatible_digest_is_not_reused(self, tmp_path):
        store_baseline(tmp_path / "results", build_manifest(artifact_digest="a" * 64))

        baseline = load_reused_baseline(
            COMMIT_PROFILE,
            str(tmp_path / "results"),
            build_manifest(artifact_digest="0" * 64),
            now=REFERENCE_TIME,
        )

        assert baseline.available is False
        assert baseline.unavailable_reason == "no digest-compatible stored result"

    def test_stored_result_without_candidate_a_is_not_reused(self, tmp_path):
        manifest = build_manifest()
        store_baseline(tmp_path / "results", manifest, candidates=("B",))

        baseline = load_reused_baseline(
            COMMIT_PROFILE,
            str(tmp_path / "results"),
            manifest,
            now=REFERENCE_TIME,
        )

        assert baseline.available is False
        assert baseline.unavailable_reason == "stored result has no candidate A samples"

    def test_missing_timestamp_is_not_reused(self, tmp_path):
        manifest = build_manifest()
        manifest.pop("created_at")
        store_baseline(tmp_path / "results", manifest)

        baseline = load_reused_baseline(
            COMMIT_PROFILE,
            str(tmp_path / "results"),
            manifest,
            now=REFERENCE_TIME,
        )

        assert baseline.available is False
        assert baseline.unavailable_reason == "stored result has no usable timestamp"


class TestProfileDisclosure:
    def test_commit_run_states_the_comparison_is_provisional(self, tmp_path):
        manifest = build_manifest()
        store_baseline(tmp_path / "results", manifest)
        baseline = load_reused_baseline(
            COMMIT_PROFILE,
            str(tmp_path / "results"),
            manifest,
            now=REFERENCE_TIME,
        )

        lines = describe_profile(COMMIT_PROFILE, baseline)

        assert "NOT release evidence" in lines[0]
        assert "reused from digest" in lines[1]
        assert "age 0.0d of 14d" in lines[1]
        assert "PROVISIONAL" in lines[2]

    def test_commit_run_without_a_baseline_says_gates_do_not_apply(self):
        baseline = ReusedBaseline(unavailable_reason="no digest-compatible stored result")

        lines = describe_profile(COMMIT_PROFILE, baseline)

        assert "unavailable" in lines[1]
        assert "will not be reported" in lines[1]

    def test_release_run_states_nothing_was_reused(self):
        lines = describe_profile(RELEASE_PROFILE, ReusedBaseline())

        assert "no reused baseline" in lines[0]


class TestProvisionalReporting:
    def test_report_folds_in_the_reused_baseline_and_flags_it(self, tmp_path, capsys):
        from tests.evals.harness import RunRecord
        from tests.evals.run_evals import report
        from tests.evals.scoring import CaseScore

        live_scores = [
            CaseScore(
                "C01",
                "communication",
                "B",
                1,
                completed=True,
                rubric_score=1.0,
                rubric_expected=True,
            )
        ]
        records = [RunRecord("C01", "communication", "B", 1)]
        baseline = ReusedBaseline(
            scores=[
                CaseScore(
                    "C01",
                    "communication",
                    "A",
                    1,
                    completed=True,
                    rubric_score=1.0,
                    rubric_expected=True,
                    sample_source="reused",
                )
            ],
            provenance={
                "artifact_digest": "a" * 64,
                "created_at": REFERENCE_TIME.isoformat(),
                "age_days": 0.0,
                "max_age_days": MAX_BASELINE_AGE_DAYS,
                "commit": "9" * 40,
                "sample_count": 1,
            },
        )

        summaries, _gates = report(
            live_scores,
            records,
            tmp_path,
            build_manifest(),
            baseline,
        )

        output = capsys.readouterr().out
        assert "Provisional gates" in output
        assert "live=0 reused=1" in output
        assert summaries["A"]["reused_samples"] == 1
        assert summaries["B"]["live_samples"] == 1

    def test_report_without_a_baseline_still_reads_as_release_gates(self, tmp_path, capsys):
        from tests.evals.harness import RunRecord
        from tests.evals.run_evals import report
        from tests.evals.scoring import CaseScore

        scores = [
            CaseScore("C01", "communication", candidate, 1, completed=True)
            for candidate in ("A", "B")
        ]
        records = [RunRecord("C01", "communication", candidate, 1) for candidate in ("A", "B")]

        report(scores, records, tmp_path, build_manifest())

        output = capsys.readouterr().out
        assert "Release gates (candidate B)" in output
        assert "Provisional" not in output
