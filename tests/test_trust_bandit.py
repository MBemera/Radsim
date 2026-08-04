"""Tests for learned confirmation trust."""

import json
import logging
import stat
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import radsim.trust_bandit as trust_bandit_module
from radsim.safety import confirm_write
from radsim.trust_bandit import (
    TrustBandit,
    build_action_signature,
    is_high_impact_action,
)
from radsim.trust_bandit_integration import (
    consume_decision_id,
    should_auto_confirm_action,
)


class FixedRandom:
    """Predictable random source for Thompson sampling tests."""

    def __init__(self, value):
        self.value = value

    def betavariate(self, alpha, beta):
        return self.value


class MutableClock:
    """Controllable clock for decay tests."""

    def __init__(self, value):
        self.value = value

    def now(self):
        return self.value


class FakeBandit:
    """Small fake for confirmation integration tests."""

    def __init__(self, auto_confirm):
        self.auto_confirm = auto_confirm
        self.records = []

    def should_auto_confirm(self, tool_name, tool_input):
        if self.auto_confirm:
            return True, "trusted:0.99"
        return False, "cold_start"

    def record_decision(
        self,
        tool_name,
        tool_input,
        *,
        accepted,
        source,
        learn,
    ):
        self.records.append((tool_name, tool_input, accepted, source, learn))
        return "a" * 32


def make_bandit(tmp_path, random_value=1.0, now_fn=None):
    """Create an isolated test bandit."""
    return TrustBandit(
        storage_path=tmp_path / "trust.json",
        random_source=FixedRandom(random_value),
        now_fn=now_fn,
    )


def test_tier_two_tools_never_auto_confirm(tmp_path):
    bandit = make_bandit(tmp_path)
    tool_input = {"file_path": "old.py"}

    for _ in range(20):
        recorded = bandit.record_outcome("delete_file", tool_input, accepted=True)

    auto_confirm, reason = bandit.should_auto_confirm("delete_file", tool_input)

    assert recorded is False
    assert auto_confirm is False
    assert reason == "tier_two_never_auto"
    assert bandit.get_stats() == []


def test_cold_start_requires_minimum_observations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bandit = make_bandit(tmp_path)
    tool_input = {"file_path": "src/example.py"}

    for _ in range(4):
        bandit.record_outcome("write_file", tool_input, accepted=True)

    auto_confirm, reason = bandit.should_auto_confirm("write_file", tool_input)

    assert auto_confirm is False
    assert reason == "cold_start"


def test_trust_builds_after_clean_accepts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bandit = make_bandit(tmp_path)
    tool_input = {"file_path": "src/example.py"}

    for _ in range(5):
        bandit.record_outcome("write_file", tool_input, accepted=True)

    auto_confirm, reason = bandit.should_auto_confirm("write_file", tool_input)

    assert auto_confirm is True
    assert reason.startswith("trusted:")


def test_rejections_erode_trust(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bandit = make_bandit(tmp_path)
    tool_input = {"file_path": "src/example.py"}

    for _ in range(5):
        bandit.record_outcome("write_file", tool_input, accepted=True)
    for _ in range(5):
        bandit.record_outcome("write_file", tool_input, accepted=False)

    auto_confirm, reason = bandit.should_auto_confirm("write_file", tool_input)

    assert auto_confirm is False
    assert reason == "below_trust_threshold"


def test_trust_isolated_by_action_signature(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bandit = make_bandit(tmp_path)
    src_input = {"file_path": "src/example.py"}
    tests_input = {"file_path": "tests/test_example.py"}

    for _ in range(5):
        bandit.record_outcome("write_file", src_input, accepted=True)
        bandit.record_outcome("write_file", tests_input, accepted=False)

    src_auto, _ = bandit.should_auto_confirm("write_file", src_input)
    tests_auto, tests_reason = bandit.should_auto_confirm("write_file", tests_input)

    assert build_action_signature("write_file", src_input) != build_action_signature(
        "write_file",
        tests_input,
    )
    assert src_auto is True
    assert tests_auto is False
    assert tests_reason == "below_trust_threshold"


def test_trust_persists_to_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    storage_path = tmp_path / "trust.json"
    bandit = TrustBandit(storage_path=storage_path, random_source=FixedRandom(1.0))
    tool_input = {"file_path": "src/example.py"}

    bandit.record_outcome("write_file", tool_input, accepted=True)
    reloaded = TrustBandit(storage_path=storage_path, random_source=FixedRandom(1.0))

    stats = reloaded.get_stats()

    assert len(stats) == 1
    assert stats[0]["tool"] == "write_file"
    assert stats[0]["observations"] == 1


def test_corrupt_json_recovers_with_empty_stats(tmp_path):
    storage_path = tmp_path / "trust.json"
    storage_path.write_text("not json")

    bandit = TrustBandit(storage_path=storage_path, random_source=FixedRandom(1.0))

    assert bandit.get_stats() == []


def test_reset_clears_tool_trust(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bandit = make_bandit(tmp_path)

    bandit.record_outcome("write_file", {"file_path": "src/a.py"}, accepted=True)
    bandit.record_outcome("run_tests", {"test_path": "tests"}, accepted=True)
    bandit.reset(tool_name="write_file")

    stats = bandit.get_stats()

    assert len(stats) == 1
    assert stats[0]["tool"] == "run_tests"


def test_time_decay_revalidates_old_trust(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clock = MutableClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    bandit = make_bandit(tmp_path, now_fn=clock.now)
    tool_input = {"file_path": "src/example.py"}

    for _ in range(10):
        bandit.record_outcome("write_file", tool_input, accepted=True)

    initial_auto_confirm, _ = bandit.should_auto_confirm("write_file", tool_input)
    clock.value = clock.value + timedelta(days=90)
    decayed_auto_confirm, reason = bandit.should_auto_confirm("write_file", tool_input)

    assert initial_auto_confirm is True
    assert decayed_auto_confirm is False
    assert reason == "cold_start"


def test_confirm_write_uses_trusted_bandit_without_prompt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake_bandit = FakeBandit(auto_confirm=True)
    config = SimpleNamespace(auto_confirm=False, trust_mode="medium")

    monkeypatch.setattr(
        "radsim.trust_bandit_integration.get_trust_bandit",
        lambda: fake_bandit,
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: (_ for _ in ()).throw(AssertionError("prompt should not run")),
    )

    confirmed = confirm_write("src/example.py", "print('hi')\n", config=config)

    assert confirmed is True
    assert fake_bandit.records == [
        (
            "write_file",
            {"file_path": "src/example.py"},
            True,
            "learned_auto",
            False,
        ),
    ]


def test_confirm_write_records_user_rejection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake_bandit = FakeBandit(auto_confirm=False)
    config = SimpleNamespace(auto_confirm=False, trust_mode="medium")

    monkeypatch.setattr(
        "radsim.trust_bandit_integration.get_trust_bandit",
        lambda: fake_bandit,
    )
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "n")

    confirmed = confirm_write("src/example.py", "print('hi')\n", config=config)

    assert confirmed is False
    assert fake_bandit.records == [
        (
            "write_file",
            {"file_path": "src/example.py"},
            False,
            "user_prompt",
            True,
        ),
    ]


def test_repeated_auto_confirms_do_not_reinforce_the_originating_arm(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    bandit = make_bandit(tmp_path)
    tool_input = {"file_path": "src/example.py"}
    for _ in range(5):
        bandit.record_outcome("write_file", tool_input, accepted=True)
    arm = next(iter(bandit.arms.values()))
    initial_alpha = arm.alpha
    monkeypatch.setattr(
        "radsim.trust_bandit_integration.get_trust_bandit",
        lambda: bandit,
    )

    for _ in range(10):
        assert should_auto_confirm_action(
            "write_file",
            tool_input,
            config=SimpleNamespace(trust_mode="medium"),
        )[0] is True

    assert arm.alpha == initial_alpha
    assert len(bandit.decisions) == 10


def test_matched_revert_penalizes_only_the_originating_arm(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bandit = make_bandit(tmp_path)
    source_input = {"file_path": "src/example.py"}
    test_input = {"file_path": "tests/test_example.py"}
    for _ in range(5):
        bandit.record_outcome("write_file", source_input, accepted=True)
        bandit.record_outcome("write_file", test_input, accepted=True)
    source_arm = bandit.arms[_arm_key_for("write_file", source_input)]
    test_arm = bandit.arms[_arm_key_for("write_file", test_input)]
    decision_id = bandit.record_decision(
        "write_file",
        source_input,
        accepted=True,
        source="learned_auto",
        learn=False,
    )
    original_source_trust = source_arm.mean_trust()
    original_test_trust = test_arm.mean_trust()

    assert bandit.record_revert(decision_id) is True

    assert source_arm.mean_trust() < original_source_trust
    assert test_arm.mean_trust() == original_test_trust
    assert bandit.record_revert(decision_id) is False
    assert bandit.record_revert("f" * 32) is False


def test_stale_decision_id_cannot_change_trust(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clock = MutableClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    bandit = make_bandit(tmp_path, now_fn=clock.now)
    tool_input = {"file_path": "src/example.py"}
    bandit.record_outcome("write_file", tool_input, accepted=True)
    decision_id = bandit.record_decision(
        "write_file",
        tool_input,
        accepted=True,
        source="user_prompt",
        learn=True,
    )
    clock.value += timedelta(days=31)

    assert bandit.record_revert(decision_id) is False


@pytest.mark.parametrize(
    ("tool_name", "tool_input"),
    [
        ("delete_file", {"file_path": "src/a.py"}),
        ("write_file", {"file_path": ".env"}),
        ("write_file", {"file_path": ".github/workflows/release.yml"}),
        ("run_shell_command", {"command": "chmod 777 app.py"}),
        ("run_shell_command", {"command": "npm publish"}),
        ("send_telegram", {"message": "hello"}),
        ("install_system_tool", {"tool_name": "example"}),
        ("deploy", {"platform": "example"}),
        ("save_context", {"filename": "context.json"}),
        ("save_memory", {"key": "preference", "value": "example"}),
    ],
)
def test_high_impact_classes_never_gain_learned_approval(
    tmp_path, tool_name, tool_input
):
    bandit = make_bandit(tmp_path)

    for _ in range(20):
        bandit.record_outcome(tool_name, tool_input, accepted=True)

    assert bandit.should_auto_confirm(tool_name, tool_input)[0] is False
    assert bandit.get_stats() == []


def test_sensitive_tier_one_variant_is_high_impact():
    assert is_high_impact_action("write_file", {"file_path": ".env"}) is True
    assert is_high_impact_action("write_file", {"file_path": "src/app.py"}) is False


def test_symlinked_secret_and_external_write_fail_closed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("SECRET=value")
    (tmp_path / "config.txt").symlink_to(tmp_path / ".env")

    assert is_high_impact_action(
        "write_file", {"file_path": "config.txt"}
    ) is True
    assert is_high_impact_action(
        "write_file", {"file_path": tmp_path.parent / "outside.py"}
    ) is True


def test_non_boolean_outcome_cannot_change_trust(tmp_path):
    bandit = make_bandit(tmp_path)

    assert bandit.record_outcome(
        "write_file", {"file_path": "src/a.py"}, accepted="yes"
    ) is False
    assert bandit.get_stats() == []


def test_nonfinite_persisted_state_is_rejected_as_a_unit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bandit = make_bandit(tmp_path)
    bandit.record_outcome("write_file", {"file_path": "src/a.py"}, accepted=True)
    payload = json.loads(bandit.storage_path.read_text())
    next(iter(payload["arms"].values()))["alpha"] = float("nan")
    bandit.storage_path.write_text(json.dumps(payload))

    reloaded = make_bandit(tmp_path)

    assert reloaded.get_stats() == []
    assert reloaded.decisions == {}


def test_oversized_or_symlinked_store_is_rejected(tmp_path, monkeypatch):
    oversized_path = tmp_path / "oversized.json"
    oversized_path.write_text("x" * 100)
    monkeypatch.setattr(trust_bandit_module, "MAX_STORAGE_BYTES", 50)
    assert TrustBandit(storage_path=oversized_path).get_stats() == []

    target = tmp_path / "target.json"
    target.write_text("{}")
    symlink_path = tmp_path / "linked.json"
    symlink_path.symlink_to(target)
    assert TrustBandit(storage_path=symlink_path).get_stats() == []


def test_decision_ledger_is_bounded_and_owner_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(trust_bandit_module, "MAX_DECISIONS", 2)
    bandit = make_bandit(tmp_path)
    tool_input = {"file_path": "src/a.py"}

    for _ in range(3):
        bandit.record_decision(
            "write_file",
            tool_input,
            accepted=True,
            source="user_prompt",
            learn=True,
        )

    assert len(bandit.decisions) == 2
    assert stat.S_IMODE(bandit.storage_path.stat().st_mode) == 0o600


def test_decision_audit_log_never_contains_tool_arguments(tmp_path, caplog):
    bandit = make_bandit(tmp_path)
    secret_marker = "never-log-this-secret"

    with caplog.at_level(logging.INFO, logger="radsim.trust_bandit"):
        bandit.record_decision(
            "write_file",
            {"file_path": "src/a.py", "content": secret_marker},
            accepted=True,
            source="user_prompt",
            learn=True,
        )

    assert secret_marker not in caplog.text
    assert "tool=write_file" in caplog.text


def test_mismatched_receipt_is_consumed_without_reuse(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake_bandit = FakeBandit(auto_confirm=True)
    monkeypatch.setattr(
        "radsim.trust_bandit_integration.get_trust_bandit",
        lambda: fake_bandit,
    )
    source_input = {"file_path": "src/a.py"}
    assert should_auto_confirm_action(
        "write_file", source_input, SimpleNamespace(trust_mode="medium")
    )[0] is True

    assert consume_decision_id("write_file", {"file_path": "tests/a.py"}) is None
    assert consume_decision_id("write_file", source_input) is None


def _arm_key_for(tool_name, tool_input):
    signature = build_action_signature(tool_name, tool_input)
    return trust_bandit_module._arm_key(tool_name, signature)
