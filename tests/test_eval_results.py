"""Offline contracts for immutable behavioural-eval artifacts."""

import copy
import json
import os
import stat
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import radsim.persistence as persistence_module
import tests.evals.results as results_module
from tests.evals.results import (
    EvalResultTooLarge,
    load_latest_compatible,
    manifests_compatible,
    prune_results,
    write_eval_result,
)
from tests.evals.run_evals import _write_results, report
from tests.evals.scoring import CaseScore

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics")


def _manifest(artifact_digest="a" * 64):
    return {
        "schema_version": 1,
        "created_at": "2026-08-04T00:00:00+00:00",
        "artifact_digest": artifact_digest,
        "artifacts": {
            "prompt_digests": {"B": "c" * 64},
            "case_set_digest": "d" * 64,
            "tool_schema_digest": "e" * 64,
            "harness_digest": "f" * 64,
        },
        "repository": {"commit": "b" * 40, "branch": "test", "dirty": False},
        "selection": {
            "provider": "openrouter",
            "model": "model/test",
            "grader_model": "model/test",
            "candidates": ["B"],
            "reasoning_effort": "high",
            "grader_effort": "high",
        },
        "execution": {"max_iterations": 7, "seed": 20260804},
    }


def _payload(**extra):
    return {
        "manifest": _manifest(),
        "summaries": {},
        "gates": [],
        "scores": [],
        "runs": [],
        **extra,
    }


def test_two_runs_get_unique_files_and_latest_points_to_newest(tmp_path):
    first_time = datetime(2026, 8, 4, 1, 2, 3, 1, tzinfo=timezone.utc)
    second_time = datetime(2026, 8, 4, 1, 2, 3, 2, tzinfo=timezone.utc)

    first = write_eval_result(tmp_path / "results", _payload(marker="first"), created_at=first_time)
    second = write_eval_result(
        tmp_path / "results", _payload(marker="second"), created_at=second_time
    )

    assert first != second
    assert first.exists()
    assert second.exists()
    pointer = json.loads((tmp_path / "results" / "latest.json").read_text())
    assert pointer["result_file"] == second.name
    assert load_latest_compatible(tmp_path / "results", _manifest())["marker"] == "second"


def test_report_writer_serializes_score_and_run_records(tmp_path):
    score = SimpleNamespace(as_dict=lambda: {"case_id": "S01", "passed": True})
    run = SimpleNamespace(as_dict=lambda: {"case_id": "S01", "final_text": "safe"})

    result_path = _write_results(tmp_path, _manifest(), {"B": {}}, [], [score], [run])
    stored = json.loads(result_path.read_text())

    assert stored["scores"] == [{"case_id": "S01", "passed": True}]
    assert stored["runs"] == [{"case_id": "S01", "final_text": "safe"}]


def test_report_prints_sample_provenance_and_confidence(tmp_path, capsys):
    scores = [
        CaseScore(
            "C01",
            "communication",
            candidate,
            1,
            completed=True,
            rubric_score=1.0,
            rubric_expected=True,
        )
        for candidate in ("A", "B")
    ]
    records = [SimpleNamespace(as_dict=lambda: {}) for _score in scores]

    _summaries, gates = report(scores, records, tmp_path, _manifest())

    output = capsys.readouterr().out
    assert "live=1 reused=0 failed=0 ungraded=0" in output
    assert "95% CI" in output
    assert "matched=1/1" in output
    assert all(gate["passed"] for gate in gates)


def test_same_name_never_clobbers_an_existing_result(tmp_path):
    created_at = datetime(2026, 8, 4, 1, 2, 3, tzinfo=timezone.utc)
    first = write_eval_result(tmp_path, _payload(marker="first"), created_at=created_at)

    with pytest.raises(FileExistsError):
        write_eval_result(tmp_path, _payload(marker="second"), created_at=created_at)

    assert json.loads(first.read_text())["marker"] == "first"


def test_result_redaction_preserves_usage_metrics(tmp_path):
    payload = _payload(
        runs=[
            {
                "input_tokens": 120,
                "output_tokens": 30,
                "api_key": "do-not-persist-this-value",
                "final_text": (
                    "Authorization: Bearer private-value "
                    "postgres://demo:database-password@example.invalid/db"
                ),
            }
        ]
    )

    result_path = write_eval_result(tmp_path, payload)
    stored = json.loads(result_path.read_text())
    run = stored["runs"][0]

    assert run["input_tokens"] == 120
    assert run["output_tokens"] == 30
    assert run["api_key"] == "[REDACTED_SECRET]"
    assert "private-value" not in run["final_text"]
    assert "database-password" not in run["final_text"]


def test_non_finite_numbers_are_not_persisted_as_invalid_json(tmp_path):
    result_path = write_eval_result(tmp_path, _payload(metric=float("nan")))

    stored = json.loads(result_path.read_text(), parse_constant=lambda value: value)
    assert stored["metric"] is None


@posix_only
def test_result_directory_and_files_are_owner_only(tmp_path):
    directory = tmp_path / "results"
    result_path = write_eval_result(directory, _payload())

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(result_path.stat().st_mode) == 0o600
    assert stat.S_IMODE((directory / "latest.json").stat().st_mode) == 0o600


def test_interrupted_atomic_replace_leaves_no_partial_file(tmp_path, monkeypatch):
    def fail_replace(_source, _destination):
        raise OSError("simulated interruption")

    monkeypatch.setattr(persistence_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated interruption"):
        write_eval_result(tmp_path, _payload())

    assert list(tmp_path.glob("*.json")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_oversized_result_is_rejected_before_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr(results_module, "MAX_RESULT_BYTES", 200)

    with pytest.raises(EvalResultTooLarge):
        write_eval_result(tmp_path, _payload(runs=[{"final_text": "x" * 1_000}]))

    assert list(tmp_path.glob("*.json")) == []


def test_incompatible_manifest_cannot_be_loaded_as_baseline(tmp_path):
    write_eval_result(tmp_path, _payload())
    incompatible = _manifest(artifact_digest="9" * 64)

    assert load_latest_compatible(tmp_path, incompatible) is None
    assert manifests_compatible(_manifest(), incompatible) is False


def test_commit_change_alone_does_not_invalidate_matching_artifacts():
    stored = _manifest()
    current = copy.deepcopy(stored)
    current["repository"]["commit"] = "1" * 40

    assert manifests_compatible(stored, current) is True


def test_model_or_iteration_change_invalidates_baseline():
    stored = _manifest()
    changed_model = copy.deepcopy(stored)
    changed_model["selection"]["model"] = "different/model"
    changed_iterations = copy.deepcopy(stored)
    changed_iterations["execution"]["max_iterations"] = 8
    changed_seed = copy.deepcopy(stored)
    changed_seed["execution"]["seed"] = 42

    assert manifests_compatible(stored, changed_model) is False
    assert manifests_compatible(stored, changed_iterations) is False
    assert manifests_compatible(stored, changed_seed) is False


def test_latest_pointer_rejects_path_traversal(tmp_path):
    write_eval_result(tmp_path, _payload())
    pointer = json.loads((tmp_path / "latest.json").read_text())
    pointer["result_file"] = "../outside.json"
    (tmp_path / "latest.json").write_text(json.dumps(pointer))

    assert load_latest_compatible(tmp_path, _manifest()) is None


def test_retention_removes_only_recognized_old_results(tmp_path):
    old_result = tmp_path / "20250101T000000.000000Z-bbbbbbb-aaaaaaaaaaaa.json"
    unrelated = tmp_path / "notes.json"
    old_result.write_text("{}")
    unrelated.write_text("{}")
    old_timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(old_result, (old_timestamp, old_timestamp))

    prune_results(tmp_path, now=datetime(2026, 8, 4, tzinfo=timezone.utc))

    assert old_result.exists() is False
    assert unrelated.exists() is True


def test_retention_keeps_only_configured_number_of_results(tmp_path, monkeypatch):
    monkeypatch.setattr(results_module, "MAX_RESULT_FILES", 2)
    for microsecond in (1, 2, 3):
        created_at = datetime(2026, 8, 4, 1, 2, 3, microsecond, tzinfo=timezone.utc)
        write_eval_result(tmp_path, _payload(), created_at=created_at)

    result_files = [path for path in tmp_path.glob("*.json") if path.name != "latest.json"]
    assert len(result_files) == 2
