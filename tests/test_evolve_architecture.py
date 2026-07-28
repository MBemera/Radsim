"""Regression tests for unified evolve controls and canonical learning."""

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from radsim.agent_config import DEFAULT_CONFIG, AgentConfigManager
from radsim.agent_conversation import AgentConversationMixin
from radsim.background import BackgroundJobManager, JobStatus
from radsim.commands import CommandRegistry
from radsim.learning import (
    LearningEvent,
    LearningStore,
    PreferenceLearner,
    ProposalEngine,
    TaskOutcome,
    TaskOutcomeTracker,
    rank_learning_events,
    verified_success_events,
)
from radsim.trust_bandit import TrustBandit, classify_tool_tier


@pytest.fixture
def evolve_runtime(tmp_path, monkeypatch):
    import radsim.agent_config as agent_config
    import radsim.learning.proposals as proposals

    manager = AgentConfigManager(config_dir=tmp_path / "config")
    engine = ProposalEngine(storage_dir=tmp_path / "learning")
    monkeypatch.setattr(agent_config, "_agent_config_manager", manager)
    monkeypatch.setattr(proposals, "_proposal_engine", engine)
    registry = CommandRegistry()
    agent = SimpleNamespace(command_registry=registry)
    return registry, agent, manager, engine


@pytest.mark.parametrize(
    ("command", "key", "expected"),
    [
        ("/evolve on", "self_improvement.enabled", True),
        ("/evolve off", "self_improvement.enabled", False),
        ("/evolve auto on", "self_improvement.auto_propose", True),
        ("/evolve auto off", "self_improvement.auto_propose", False),
        ("/evolve learning on", "learning.enabled", True),
        ("/evolve learning off", "learning.enabled", False),
    ],
)
def test_evolve_toggle_contract_persists(
    evolve_runtime,
    command,
    key,
    expected,
):
    registry, agent, manager, _engine = evolve_runtime

    assert registry.handle_input(command, agent) is True

    assert manager.get(key) is expected
    recreated = AgentConfigManager(config_dir=manager.config_dir)
    assert recreated.get(key) is expected


def test_evolve_on_never_enables_self_extension(evolve_runtime):
    registry, agent, manager, _engine = evolve_runtime

    registry.handle_input("/evolve on", agent)

    assert manager.get("self_improvement.enabled") is True
    assert manager.get("tools.self_extension") is False


def test_evolve_off_retains_data_auto_preference_and_extensions(
    evolve_runtime,
    tmp_path,
):
    registry, agent, manager, engine = evolve_runtime
    marker = tmp_path / "learning" / "retained.marker"
    marker.write_text("keep")
    manager.set("self_improvement.enabled", True)
    manager.set("self_improvement.auto_propose", False)
    manager.set("tools.self_extension", True)

    registry.handle_input("/evolve off", agent)

    assert manager.get("self_improvement.enabled") is False
    assert manager.get("self_improvement.auto_propose") is False
    assert manager.get("tools.self_extension") is True
    assert marker.read_text() == "keep"
    assert engine.get_pending_proposals() == []


def test_evolve_extensions_requires_typed_confirmation(
    evolve_runtime,
    monkeypatch,
):
    registry, agent, manager, _engine = evolve_runtime
    monkeypatch.setattr("radsim.menu.safe_input", lambda prompt: "no")

    registry.handle_input("/evolve extensions on", agent)
    assert manager.get("tools.self_extension") is False

    monkeypatch.setattr("radsim.menu.safe_input", lambda prompt: "enable")
    registry.handle_input("/evolve extensions on", agent)
    assert manager.get("tools.self_extension") is True

    registry.handle_input("/evolve extensions off", agent)
    assert manager.get("tools.self_extension") is False


def test_evolve_status_history_and_stats_work_while_disabled(
    evolve_runtime,
    capsys,
):
    registry, agent, manager, _engine = evolve_runtime
    manager.set("self_improvement.enabled", False)

    for command in ("/evolve status", "/evolve history", "/evolve stats"):
        assert registry.handle_input(command, agent) is True

    output = capsys.readouterr().out
    assert "EVOLVE STATUS" in output
    assert "Proposal engine:" in output
    assert "IMPROVEMENT HISTORY" in output
    assert "SELF-IMPROVEMENT STATS" in output


def test_evolve_analyze_and_review_are_blocked_by_master_switch(
    evolve_runtime,
    capsys,
):
    registry, agent, manager, _engine = evolve_runtime
    manager.set("self_improvement.enabled", False)

    registry.handle_input("/evolve analyze", agent)
    registry.handle_input("/evolve review", agent)

    output = capsys.readouterr().out
    assert output.count("Proposal engine is OFF") == 2


def test_evolve_settings_updates_existing_keys_only(
    evolve_runtime,
    monkeypatch,
):
    registry, agent, manager, _engine = evolve_runtime

    def choose_states(title, items, footer_lines=()):
        states = {item["key"]: bool(item["value"]) for item in items}
        states["learning.error_analysis"] = False
        states["self_improvement.enabled"] = True
        return states

    monkeypatch.setattr("radsim.menu.toggle_menu", choose_states)
    registry.handle_input("/evolve settings", agent)

    assert manager.get("learning.error_analysis") is False
    assert manager.get("self_improvement.enabled") is True
    assert manager.get("evolve.enabled") is None


def test_evolve_menu_shows_current_toggle_states(
    evolve_runtime,
    monkeypatch,
):
    registry, agent, manager, _engine = evolve_runtime
    manager.set("self_improvement.enabled", True)
    manager.set("self_improvement.auto_propose", False)
    captured = {}

    def capture_menu(title, options):
        captured["title"] = title
        captured["labels"] = [label for _key, label in options]
        return "exit"

    monkeypatch.setattr("radsim.menu.interactive_menu", capture_menu)
    registry.handle_input("/evolve", agent)

    assert captured["title"] == "EVOLVE"
    assert "Proposal engine [ON]" in captured["labels"]
    assert "Automatic proposals [OFF]" in captured["labels"]
    assert len(captured["labels"]) == 11


def test_defaults_keep_proposals_and_extensions_disabled():
    assert DEFAULT_CONFIG["self_improvement"]["enabled"] is False
    assert DEFAULT_CONFIG["tools"]["self_extension"] is False
    assert "evolve" not in DEFAULT_CONFIG


def test_retired_active_learning_key_is_removed_from_old_config(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "agent_config.json").write_text(
        json.dumps({"learning": {"active_learning": False}})
    )

    manager = AgentConfigManager(config_dir=config_dir)

    assert "active_learning" not in manager.get("learning")


@pytest.mark.parametrize(
    ("configure", "expected"),
    [
        (lambda tracker: None, TaskOutcome.UNKNOWN),
        (
            lambda tracker: tracker.record_tool("write_file", True),
            TaskOutcome.SUCCESSFUL,
        ),
        (
            lambda tracker: tracker.record_tool("write_file", False, error="disk full"),
            TaskOutcome.FAILED,
        ),
        (
            lambda tracker: (
                tracker.record_tool("write_file", True),
                tracker.record_tool("run_tests", False, error="tests failed"),
            ),
            TaskOutcome.PARTIALLY_SUCCESSFUL,
        ),
        (lambda tracker: tracker.mark_cancelled(), TaskOutcome.CANCELLED),
        (
            lambda tracker: setattr(tracker, "user_rejected", True),
            TaskOutcome.USER_REJECTED,
        ),
        (lambda tracker: tracker.mark_reverted(), TaskOutcome.REVERTED),
    ],
)
def test_task_outcome_states_are_evidence_based(configure, expected):
    tracker = TaskOutcomeTracker("Implement feature")
    configure(tracker)

    assert tracker.resolve() is expected


def test_model_text_alone_is_not_success_evidence():
    tracker = TaskOutcomeTracker("Answer a question")

    event = tracker.build_event(result="Everything is complete.")

    assert event.outcome == TaskOutcome.UNKNOWN.value
    assert "result" not in event.metadata


def test_exception_can_never_be_recorded_as_success():
    tracker = TaskOutcomeTracker("Failing task")
    tracker.record_tool("read_file", True)

    event = tracker.build_event(error=RuntimeError("crash"))

    assert event.outcome == TaskOutcome.FAILED.value
    assert event.error_type == "RuntimeError"


def test_turn_recording_uses_unknown_instead_of_hardcoded_success(
    tmp_path,
    monkeypatch,
):
    import radsim.agent_config as agent_config
    import radsim.learning as learning

    manager = AgentConfigManager(config_dir=tmp_path / "config")
    manager.set("self_improvement.enabled", False)
    store = LearningStore(tmp_path / "learning", migrate_legacy=False)
    optimizer = SimpleNamespace(reset_current_chain=lambda: None)
    monkeypatch.setattr(agent_config, "_agent_config_manager", manager)
    monkeypatch.setattr(learning, "get_learning_store", lambda: store)
    monkeypatch.setattr(learning, "get_tool_optimizer", lambda: optimizer)
    agent = SimpleNamespace(
        _task_outcome_tracker=TaskOutcomeTracker("Text-only response"),
        usage_stats={"input_tokens": 5, "output_tokens": 3},
    )

    AgentConversationMixin._record_learning_outcome(
        agent,
        result="Done",
        error=None,
        duration_ms=10,
        usage_before={"input_tokens": 0, "output_tokens": 0},
    )

    assert store.latest_task().outcome == TaskOutcome.UNKNOWN.value


def test_learning_store_is_idempotent_bounded_and_redacted(tmp_path):
    store = LearningStore(tmp_path, max_events=3, migrate_legacy=False)
    event = LearningEvent.create(
        event_id="same-event",
        event_type="task_completion",
        outcome=TaskOutcome.SUCCESSFUL,
        summary="token=super-secret-value",
        error_message="Bearer abcdefghijklmnop",
        metadata={"password": "hidden", "note": "api_key=do-not-store"},
    )

    assert store.append(event) is True
    assert store.append(event) is False
    persisted = json.dumps(store.query(limit=1)[0].__dict__)
    assert "super-secret-value" not in persisted
    assert "do-not-store" not in persisted
    assert "abcdefghijklmnop" not in persisted
    for index in range(5):
        store.append(
            LearningEvent.create(
                event_type="tool_execution",
                outcome=TaskOutcome.SUCCESSFUL,
                summary=f"event {index}",
            )
        )

    assert store.count() == 3
    retained = store.query(limit=3)
    serialized = json.dumps([event.__dict__ for event in retained])
    assert "super-secret-value" not in serialized
    assert "do-not-store" not in serialized
    assert "abcdefghijklmnop" not in serialized


def test_legacy_migration_is_idempotent_and_backed_up(tmp_path):
    legacy = [
        {
            "task_description": "Fix parser",
            "approach_taken": "Run tests",
            "result": "passed",
            "success": True,
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
    ]
    (tmp_path / "reflections.json").write_text(json.dumps(legacy))

    first = LearningStore(tmp_path)
    first_count = first.count()
    second = LearningStore(tmp_path)

    assert first_count == 1
    assert second.count() == first_count
    assert (tmp_path / "legacy_backup_v1" / "reflections.json").is_file()
    assert second.migration_info()["inserted_events"] == 1


def test_corrupt_legacy_record_does_not_block_migration(tmp_path):
    (tmp_path / "reflections.json").write_text(
        json.dumps(
            [
                {
                    "task_description": "Malformed duration",
                    "success": True,
                    "duration_seconds": {"invalid": True},
                },
                {
                    "task_description": "Valid task",
                    "success": True,
                    "duration_seconds": 2,
                },
            ]
        )
    )

    store = LearningStore(tmp_path)

    assert store.count(event_types={"task_completion"}) == 2
    assert [event.duration_ms for event in store.query(limit=2)] == [0, 2_000]


def test_feedback_uses_canonical_store_without_second_event_file(tmp_path):
    learner = PreferenceLearner(storage_dir=tmp_path)

    learner.record_feedback("good", "A useful response")

    assert learner.store.count(event_types={"feedback"}) == 1
    assert not (tmp_path / "feedback.json").exists()
    assert (tmp_path / "preferences.json").is_file()


def test_extension_proposal_stays_staged_until_explicit_approval(
    evolve_runtime,
):
    _registry, _agent, manager, engine = evolve_runtime
    manager.set("tools.self_extension", True)
    evidence = LearningEvent.create(
        event_type="task_completion",
        outcome=TaskOutcome.SUCCESSFUL,
        summary="Verified repeated workflow",
    )
    engine.store.append(evidence)
    staged = engine.stage_extension_proposal(
        manifest={
            "id": "proposal-extension",
            "name": "Proposal Extension",
            "version": "1.0.0",
            "entrypoint": "extension.py",
            "permissions": ["commands.register"],
        },
        source="def setup(api):\n    pass\n",
        tests="assert True\n",
        explanation="A reviewed test proposal",
        evidence_event_ids=[evidence.event_id],
    )

    assert staged["success"] is True
    proposal = staged["proposal"]
    staging_dir = engine.staging_root / proposal["proposal_id"]
    assert staging_dir.is_dir()
    denied = engine.approve_proposal(proposal["proposal_id"])
    assert denied == {
        "success": False,
        "error": "Generated extension activation requires explicit approval",
    }
    assert staging_dir.is_dir()

    assert engine.reject_proposal(proposal["proposal_id"])["success"] is True
    assert not staging_dir.exists()


def test_extension_proposal_requires_enabled_capability_and_verified_evidence(
    evolve_runtime,
):
    _registry, _agent, manager, engine = evolve_runtime
    manifest = {
        "id": "blocked-proposal",
        "name": "Blocked Proposal",
        "version": "1.0.0",
        "entrypoint": "extension.py",
        "permissions": [],
    }
    arguments = {
        "manifest": manifest,
        "source": "def setup(api):\n    pass\n",
        "tests": "",
        "explanation": "Should stay blocked",
        "evidence_event_ids": ["missing"],
    }

    assert engine.stage_extension_proposal(**arguments)["error"] == (
        "Self-extension is disabled"
    )
    manager.set("tools.self_extension", True)
    assert engine.stage_extension_proposal(**arguments)["error"] == (
        "Verified task evidence is required"
    )


def test_skipping_extension_proposal_removes_staged_code(evolve_runtime):
    _registry, _agent, manager, engine = evolve_runtime
    manager.set("tools.self_extension", True)
    evidence = LearningEvent.create(
        event_type="task_completion",
        outcome=TaskOutcome.SUCCESSFUL,
        summary="Verified workflow",
    )
    engine.store.append(evidence)
    staged = engine.stage_extension_proposal(
        manifest={
            "id": "skipped-proposal",
            "name": "Skipped Proposal",
            "version": "1.0.0",
            "entrypoint": "extension.py",
            "permissions": [],
        },
        source="def setup(api):\n    pass\n",
        tests="",
        explanation="Skip this proposal",
        evidence_event_ids=[evidence.event_id],
    )
    staging_dir = Path(staged["staging_dir"])

    assert engine.skip_proposal(staged["proposal"]["proposal_id"])["success"] is True
    assert not staging_dir.exists()


def test_generated_extension_files_are_bounded(evolve_runtime):
    _registry, _agent, manager, engine = evolve_runtime
    manager.set("tools.self_extension", True)
    evidence = LearningEvent.create(
        event_type="task_completion",
        outcome=TaskOutcome.SUCCESSFUL,
        summary="Verified workflow",
    )
    engine.store.append(evidence)

    result = engine.stage_extension_proposal(
        manifest={
            "id": "oversized-proposal",
            "name": "Oversized Proposal",
            "version": "1.0.0",
            "entrypoint": "extension.py",
            "permissions": [],
        },
        source="x" * (512 * 1024 + 1),
        tests="",
        explanation="Too large",
        evidence_event_ids=[evidence.event_id],
    )

    assert result == {
        "success": False,
        "error": "Generated extension source is too large",
    }


def test_retrieval_prefers_verified_success_and_rejects_low_confidence():
    now = datetime.now(timezone.utc)
    successful = LearningEvent.create(
        event_type="task_completion",
        outcome=TaskOutcome.SUCCESSFUL,
        summary="Fix authentication token parser",
        created_at=(now - timedelta(days=2)).isoformat(),
    )
    failed = LearningEvent.create(
        event_type="task_completion",
        outcome=TaskOutcome.FAILED,
        summary="Fix authentication token parser exactly",
        created_at=now.isoformat(),
    )

    ranked = rank_learning_events(
        "fix authentication token parser",
        [failed, successful],
    )

    assert ranked[0].event.event_id == successful.event_id
    assert set(ranked[0].explanation) == {
        "text",
        "outcome",
        "recency",
        "user_decision",
        "task_category",
        "tool_or_error",
        "revert_history",
    }
    assert rank_learning_events("unrelated database migration", [successful]) == []


def test_reverted_tasks_are_not_returned_as_success_guidance(tmp_path):
    store = LearningStore(tmp_path, migrate_legacy=False)
    successful = LearningEvent.create(
        task_id="reverted-task",
        event_type="task_completion",
        outcome=TaskOutcome.SUCCESSFUL,
        summary="Refactor parser",
    )
    store.append(successful)
    store.append(
        LearningEvent.create(
            task_id="reverted-task",
            event_type="task_revert",
            outcome=TaskOutcome.REVERTED,
            summary="User reverted parser refactor",
        )
    )

    assert verified_success_events(
        store,
        event_types={"task_completion"},
    ) == []


def test_local_retrieval_stays_bounded_and_fast():
    events = [
        LearningEvent.create(
            event_type="task_completion",
            outcome=TaskOutcome.SUCCESSFUL,
            summary=f"Fix parser case {index}",
        )
        for index in range(1_000)
    ]
    started = time.perf_counter()

    ranked = rank_learning_events("fix parser case 20", events, limit=5)

    assert len(ranked) == 5
    assert time.perf_counter() - started < 1.0


def test_background_cancellation_token_stops_work():
    manager = BackgroundJobManager()
    started = threading.Event()
    stopped = threading.Event()

    def cooperative_run(cancel_event):
        started.set()
        while not cancel_event.wait(0.01):
            pass
        stopped.set()

    job = manager.start_job("cooperative", cooperative_run)
    assert started.wait(1)

    assert manager.cancel_job(job.job_id) is True
    job._thread.join(timeout=1)

    assert stopped.is_set()
    assert job.status is JobStatus.CANCELLED


@pytest.mark.parametrize(
    "tool_name",
    ["add_tool", "activate_extension", "apply_generated_code", "install_extension"],
)
def test_generated_code_actions_are_always_confirm(tool_name, tmp_path):
    bandit = TrustBandit(storage_path=tmp_path / "trust.json")

    assert classify_tool_tier(tool_name) == "always_confirm"
    assert bandit.record_outcome(tool_name, {}, accepted=True) is False
    assert bandit.should_auto_confirm(tool_name, {}) == (
        False,
        "generated_code_always_confirm",
    )
