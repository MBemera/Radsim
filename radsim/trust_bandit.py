"""Contextual trust bandit for safe confirmation shortcuts."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STORAGE_VERSION = 1
MINIMUM_OBSERVATIONS = 5
DECAY_HALF_LIFE_DAYS = 30
AUTO_CONFIRM_THRESHOLD = 0.60
MINIMUM_MEAN_TRUST = 0.80

TIER_ONE_TOOLS = {
    "write_file",
    "replace_in_file",
    "create_directory",
    "git_add",
    "run_tests",
    "lint_code",
    "format_code",
    "type_check",
    "save_context",
}

TIER_TWO_TOOLS = {
    "add_dependency",
    "apply_patch",
    "batch_replace",
    "database_query",
    "delete_file",
    "deploy",
    "git_checkout",
    "git_commit",
    "git_stash",
    "install_system_tool",
    "multi_edit",
    "remove_dependency",
    "rename_file",
    "run_docker",
    "run_shell_command",
    "schedule_task",
    "send_telegram",
    "web_fetch",
}

_trust_bandit = None


@dataclass
class TrustArm:
    """Beta posterior for one tool/signature pair."""

    tool_name: str
    signature: str
    alpha: float = 1.0
    beta: float = 1.0
    observations: int = 0
    last_updated: str = ""

    def mean_trust(self) -> float:
        """Return the posterior mean."""
        return self.alpha / (self.alpha + self.beta)

    def effective_observations(self) -> float:
        """Return observations after decay, excluding the Beta prior."""
        return max(0.0, self.alpha + self.beta - 2.0)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this arm to JSON-safe data."""
        return {
            "tool_name": self.tool_name,
            "signature": self.signature,
            "alpha": self.alpha,
            "beta": self.beta,
            "observations": self.observations,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrustArm:
        """Build an arm from persisted data."""
        return cls(
            tool_name=str(data.get("tool_name", "")),
            signature=str(data.get("signature", "")),
            alpha=float(data.get("alpha", 1.0)),
            beta=float(data.get("beta", 1.0)),
            observations=int(data.get("observations", 0)),
            last_updated=str(data.get("last_updated", "")),
        )


class TrustBandit:
    """Learn which safe confirmation prompts can be skipped."""

    def __init__(
        self,
        storage_path: Path | None = None,
        random_source: random.Random | None = None,
        now_fn=None,
    ):
        self.storage_path = storage_path or _default_storage_path()
        self.random_source = random_source or random.Random()
        self.now_fn = now_fn or _current_time
        self.minimum_observations = MINIMUM_OBSERVATIONS
        self.decay_half_life_days = DECAY_HALF_LIFE_DAYS
        self.auto_confirm_threshold = AUTO_CONFIRM_THRESHOLD
        self.minimum_mean_trust = MINIMUM_MEAN_TRUST
        self.arms = self._load_arms()

    def should_auto_confirm(self, tool_name: str, tool_input: dict[str, Any]) -> tuple[bool, str]:
        """Return whether this action can skip the prompt."""
        tier = classify_tool_tier(tool_name)
        if tier == "tier_two":
            return False, "tier_two_never_auto"
        if tier == "unknown":
            return False, "unknown_tool"

        signature = build_action_signature(tool_name, tool_input)
        arm = self._get_arm(tool_name, signature)
        self._apply_decay(arm)
        if arm.effective_observations() < self.minimum_observations:
            return False, "cold_start"

        sampled_trust = self.random_source.betavariate(arm.alpha, arm.beta)
        if arm.mean_trust() < self.minimum_mean_trust:
            return False, "below_trust_threshold"
        if sampled_trust < self.auto_confirm_threshold:
            return False, "exploring"
        return True, f"trusted:{arm.mean_trust():.2f}"

    def record_outcome(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        accepted: bool,
    ) -> bool:
        """Record a user accept/reject outcome for a safe Tier 1 action."""
        if classify_tool_tier(tool_name) != "tier_one":
            return False

        signature = build_action_signature(tool_name, tool_input)
        arm = self._get_arm(tool_name, signature)
        self._apply_decay(arm)
        if accepted:
            arm.alpha += 1.0
        else:
            arm.beta += 1.0
        arm.observations += 1
        arm.last_updated = _format_time(self.now_fn())
        self._save_arms()
        return True

    def get_stats(self) -> list[dict[str, Any]]:
        """Return current trust stats for display."""
        stats = []
        for arm in self.arms.values():
            self._apply_decay(arm)
            stats.append(
                {
                    "tool": arm.tool_name,
                    "signature": arm.signature,
                    "trust": arm.mean_trust(),
                    "observations": arm.observations,
                    "effective_observations": arm.effective_observations(),
                }
            )
        return sorted(stats, key=lambda item: (item["tool"], item["signature"]))

    def reset(self, tool_name: str | None = None, signature: str | None = None) -> None:
        """Clear all trust, trust for one tool, or trust for one exact signature."""
        if tool_name is None and signature is None:
            self.arms = {}
            self._save_arms()
            return

        keys_to_delete = []
        for key, arm in self.arms.items():
            tool_matches = tool_name is None or arm.tool_name == tool_name
            signature_matches = signature is None or arm.signature == signature
            if tool_matches and signature_matches:
                keys_to_delete.append(key)

        for key in keys_to_delete:
            del self.arms[key]
        self._save_arms()

    def _get_arm(self, tool_name: str, signature: str) -> TrustArm:
        key = _arm_key(tool_name, signature)
        if key not in self.arms:
            self.arms[key] = TrustArm(
                tool_name=tool_name,
                signature=signature,
                last_updated=_format_time(self.now_fn()),
            )
        return self.arms[key]

    def _apply_decay(self, arm: TrustArm) -> None:
        if not arm.last_updated:
            return

        current_time = _normalize_time(self.now_fn())
        last_updated = _parse_time(arm.last_updated)
        elapsed_days = (current_time - last_updated).total_seconds() / 86400
        if elapsed_days <= 1 / 86400:
            return

        factor = 0.5 ** (elapsed_days / self.decay_half_life_days)
        arm.alpha = 1.0 + ((arm.alpha - 1.0) * factor)
        arm.beta = 1.0 + ((arm.beta - 1.0) * factor)
        arm.last_updated = _format_time(current_time)

    def _load_arms(self) -> dict[str, TrustArm]:
        if not self.storage_path.exists():
            return {}

        try:
            data = json.loads(self.storage_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

        if data.get("version") != STORAGE_VERSION:
            return {}
        arms_data = data.get("arms", {})
        if not isinstance(arms_data, dict):
            return {}

        return {
            str(key): TrustArm.from_dict(value)
            for key, value in arms_data.items()
            if isinstance(value, dict)
        }

    def _save_arms(self) -> None:
        data = {
            "version": STORAGE_VERSION,
            "arms": {key: arm.to_dict() for key, arm in self.arms.items()},
        }
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(data, indent=2, sort_keys=True))


def classify_tool_tier(tool_name: str) -> str:
    """Classify a tool as tier_one, tier_two, or unknown."""
    if tool_name.startswith("browser_"):
        return "tier_two"
    if tool_name in TIER_TWO_TOOLS:
        return "tier_two"
    if tool_name in TIER_ONE_TOOLS:
        return "tier_one"
    return "unknown"


def build_action_signature(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Build a stable, non-secret signature for a tool action."""
    project_signature = _project_signature()

    if tool_name in {"write_file", "replace_in_file", "format_code", "type_check", "lint_code"}:
        file_path = tool_input.get("file_path") or "project"
        return f"{project_signature}|{_path_pattern(file_path)}"

    if tool_name == "create_directory":
        return f"{project_signature}|directory:{_path_pattern(tool_input.get('directory_path', ''))}"

    if tool_name == "git_add":
        return f"{project_signature}|git_add:{_git_add_signature(tool_input)}"

    if tool_name == "run_tests":
        return f"{project_signature}|tests:{_test_signature(tool_input)}"

    if tool_name == "save_context":
        return f"{project_signature}|context:{_path_pattern(tool_input.get('filename', ''))}"

    return f"{project_signature}|input:{_hash_value(tool_input)}"


def get_trust_bandit() -> TrustBandit:
    """Return the process-wide trust bandit."""
    global _trust_bandit
    if _trust_bandit is None:
        _trust_bandit = TrustBandit()
    return _trust_bandit


def reset_trust_bandit() -> None:
    """Drop the process-wide singleton, mainly for tests."""
    global _trust_bandit
    _trust_bandit = None


def _default_storage_path() -> Path:
    from .config import CONFIG_DIR

    return CONFIG_DIR / "trust_bandit.json"


def _git_add_signature(tool_input: dict[str, Any]) -> str:
    if tool_input.get("all_files"):
        return "all_files"
    file_paths = tool_input.get("file_paths", [])
    if not isinstance(file_paths, list):
        return "unknown"
    patterns = sorted(_path_pattern(path) for path in file_paths)
    return ",".join(patterns) or "none"


def _test_signature(tool_input: dict[str, Any]) -> str:
    test_path = tool_input.get("test_path")
    if test_path:
        return _path_pattern(test_path)
    test_command = tool_input.get("test_command")
    if test_command:
        return f"command:{_hash_value(test_command)}"
    return "auto"


def _path_pattern(file_path: Any) -> str:
    raw_path = str(file_path or "").strip()
    if not raw_path:
        return "path:unknown"

    path = Path(raw_path).expanduser()
    cwd = Path.cwd().resolve()
    absolute_path = path if path.is_absolute() else cwd / path
    absolute_path = absolute_path.resolve()

    try:
        relative_path = absolute_path.relative_to(cwd)
    except ValueError:
        suffix = absolute_path.suffix.lower() or "no_ext"
        return f"external:{_hash_value(str(absolute_path))}:{suffix}"

    parent = relative_path.parent.as_posix()
    parent = "." if parent == "." else parent
    suffix = relative_path.suffix.lower()
    if suffix:
        return f"path:{parent}/*{suffix}"
    return f"path:{parent}/*"


def _project_signature() -> str:
    cwd = Path.cwd().resolve()
    return f"project:{cwd.name}:{_hash_value(str(cwd))}"


def _arm_key(tool_name: str, signature: str) -> str:
    return _hash_value({"tool_name": tool_name, "signature": signature})


def _hash_value(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _current_time() -> datetime:
    return datetime.now(timezone.utc)


def _format_time(value: datetime) -> str:
    return _normalize_time(value).isoformat()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return _normalize_time(parsed)


def _normalize_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
