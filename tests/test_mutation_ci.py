"""Tests for mutation CI target selection and score enforcement."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "mutation_ci.py"
    spec = importlib.util.spec_from_file_location("mutation_ci", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_changed_targets_selects_only_tier_one_files(monkeypatch):
    module = _module()

    class Completed:
        stdout = "radsim/context_budget.py\nREADME.md\nradsim/tool_schema.py\n"

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Completed())

    assert module.changed_targets("base", "head") == [
        "radsim.context_budget.*",
        "radsim.tool_schema.*",
    ]


def test_changed_targets_uses_smoke_target_when_no_critical_file_changed(monkeypatch):
    module = _module()

    class Completed:
        stdout = "README.md\n"

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Completed())

    assert module.changed_targets("base", "head") == ["radsim.performance.*"]


def test_mutation_score_counts_unsafe_outcomes_as_failures():
    module = _module()

    score, killed, considered = module.mutation_score(
        {
            "killed": 8,
            "survived": 1,
            "no_tests": 1,
            "suspicious": 0,
            "timeout": 0,
            "segfault": 0,
            "skipped": 20,
        }
    )

    assert score == 0.8
    assert killed == 8
    assert considered == 10


def test_check_stats_enforces_minimum(tmp_path):
    module = _module()
    path = tmp_path / "stats.json"
    path.write_text(json.dumps({"killed": 8, "survived": 2}), encoding="utf-8")

    assert module.check_stats(path, 0.8) == 0
    assert module.check_stats(path, 0.81) == 1


def test_check_stats_enforces_archived_baseline(tmp_path):
    module = _module()
    current_path = tmp_path / "current.json"
    baseline_path = tmp_path / "baseline.json"
    current_path.write_text(json.dumps({"killed": 7, "survived": 3}), encoding="utf-8")
    baseline_path.write_text(
        json.dumps({"stats": {"killed": 8, "survived": 2}}),
        encoding="utf-8",
    )

    assert module.check_stats(current_path, 0.0, baseline_path) == 1

    current_path.write_text(json.dumps({"killed": 9, "survived": 1}), encoding="utf-8")
    assert module.check_stats(current_path, 0.0, baseline_path) == 0
