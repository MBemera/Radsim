"""Tests for learned confirmation trust."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from radsim.safety import confirm_write
from radsim.trust_bandit import TrustBandit, build_action_signature


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

    def record_outcome(self, tool_name, tool_input, accepted):
        self.records.append((tool_name, tool_input, accepted))
        return True


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
        ("write_file", {"file_path": "src/example.py"}, True),
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
        ("write_file", {"file_path": "src/example.py"}, False),
    ]
