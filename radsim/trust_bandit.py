"""Contextual trust bandit for safe confirmation shortcuts."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .persistence import atomic_write_json

logger = logging.getLogger(__name__)

STORAGE_VERSION = 2
MINIMUM_OBSERVATIONS = 5
DECAY_HALF_LIFE_DAYS = 30
AUTO_CONFIRM_THRESHOLD = 0.60
MINIMUM_MEAN_TRUST = 0.80
DECISION_TTL_DAYS = 30
MAX_STORAGE_BYTES = 1_000_000
MAX_ARMS = 1_000
MAX_DECISIONS = 1_000
MAX_POSTERIOR_VALUE = 1_000_000
MAX_TEXT_LENGTH = 512
DECISION_SOURCES = {"user_prompt", "learned_auto", "explicit_auto"}
SENSITIVE_FILE_NAMES = {
    ".env",
    ".git-credentials",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
    "secrets.json",
}
SENSITIVE_PATH_PARTS = {".git", ".ssh", "credentials", "secrets"}
SENSITIVE_FILE_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}

TIER_ONE_TOOLS = {
    "write_file",
    "replace_in_file",
    "create_directory",
    "git_add",
    "run_tests",
    "lint_code",
    "format_code",
    "type_check",
}

ALWAYS_CONFIRM_TOOLS = {
    "add_tool",
    "activate_extension",
    "apply_generated_code",
    "install_extension",
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
    "save_context",
    "save_memory",
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
        alpha = _strict_number(data.get("alpha"))
        beta = _strict_number(data.get("beta"))
        observations = _strict_count(data.get("observations"))
        arm = cls(
            tool_name=_strict_text(data.get("tool_name")),
            signature=_strict_text(data.get("signature")),
            alpha=alpha,
            beta=beta,
            observations=observations,
            last_updated=_strict_text(data.get("last_updated")),
        )
        if not _is_valid_arm(arm):
            raise ValueError("invalid trust arm")
        return arm


@dataclass
class TrustDecision:
    """Bounded audit record linking one authorization decision to one arm."""

    decision_id: str
    tool_name: str
    signature: str
    source: str
    accepted: bool
    created_at: str
    reverted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "tool_name": self.tool_name,
            "signature": self.signature,
            "source": self.source,
            "accepted": self.accepted,
            "created_at": self.created_at,
            "reverted": self.reverted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrustDecision:
        decision = cls(
            decision_id=_strict_text(data.get("decision_id")),
            tool_name=_strict_text(data.get("tool_name")),
            signature=_strict_text(data.get("signature")),
            source=_strict_text(data.get("source")),
            accepted=data.get("accepted"),
            created_at=_strict_text(data.get("created_at")),
            reverted=data.get("reverted", False),
        )
        if not _is_valid_decision(decision):
            raise ValueError("invalid trust decision")
        return decision


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
        self.arms, self.decisions = self._load_state()

    def should_auto_confirm(self, tool_name: str, tool_input: dict[str, Any]) -> tuple[bool, str]:
        """Return whether this action can skip the prompt."""
        tier = classify_tool_tier(tool_name)
        if tier == "always_confirm":
            return False, "generated_code_always_confirm"
        if tier == "tier_two":
            return False, "tier_two_never_auto"
        if tier == "unknown":
            return False, "unknown_tool"
        if is_high_impact_action(tool_name, tool_input):
            return False, "high_impact_never_auto"

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
        if not isinstance(accepted, bool):
            return False
        if classify_tool_tier(tool_name) != "tier_one":
            return False
        signature = build_action_signature(tool_name, tool_input)
        if is_high_impact_action(tool_name, tool_input):
            return False
        self._record_outcome_without_save(tool_name, signature, accepted)
        self._save_state()
        return True

    def _record_outcome_without_save(
        self,
        tool_name: str,
        signature: str,
        accepted: bool,
    ) -> bool:
        if classify_tool_tier(tool_name) != "tier_one":
            return False
        arm = self._get_arm(tool_name, signature)
        self._apply_decay(arm)
        if accepted:
            arm.alpha += 1.0
        else:
            arm.beta += 1.0
        arm.observations += 1
        arm.last_updated = _format_time(self.now_fn())
        return True

    def record_decision(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        *,
        accepted: bool,
        source: str,
        learn: bool,
    ) -> str:
        """Record an auditable decision, learning only from a user response."""
        if not isinstance(accepted, bool) or not isinstance(learn, bool):
            raise ValueError("decision flags must be booleans")
        if source not in DECISION_SOURCES or not _is_bounded_text(tool_name):
            raise ValueError("decision source and tool must be recognized")
        if not isinstance(tool_input, dict):
            raise ValueError("tool input must be a dictionary")
        signature = build_action_signature(tool_name, tool_input)
        if learn and not is_high_impact_action(tool_name, tool_input):
            self._record_outcome_without_save(tool_name, signature, accepted)
        decision = TrustDecision(
            decision_id=uuid.uuid4().hex,
            tool_name=tool_name,
            signature=signature,
            source=source,
            accepted=accepted,
            created_at=_format_time(self.now_fn()),
        )
        self.decisions[decision.decision_id] = decision
        logger.info(
            "Trust decision id=%s tool=%s source=%s accepted=%s",
            decision.decision_id,
            tool_name,
            source,
            accepted,
        )
        self._save_state()
        return decision.decision_id

    def record_revert(self, decision_id: str) -> bool:
        """Apply negative evidence only for one fresh, matched decision ID."""
        decision = self.decisions.get(decision_id)
        if not self._can_record_revert(decision):
            return False
        arm = self.arms.get(_arm_key(decision.tool_name, decision.signature))
        if arm is None:
            return False
        self._apply_decay(arm)
        arm.beta += 1.0
        arm.observations += 1
        arm.last_updated = _format_time(self.now_fn())
        decision.reverted = True
        self._save_state()
        return True

    def _can_record_revert(self, decision: TrustDecision | None) -> bool:
        if decision is None or decision.reverted or not decision.accepted:
            return False
        if classify_tool_tier(decision.tool_name) != "tier_one":
            return False
        age = _normalize_time(self.now_fn()) - _parse_time(decision.created_at)
        return timedelta(0) <= age <= timedelta(days=DECISION_TTL_DAYS)

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
            self.decisions = {}
            self._save_state()
            return

        keys_to_delete = []
        for key, arm in self.arms.items():
            tool_matches = tool_name is None or arm.tool_name == tool_name
            signature_matches = signature is None or arm.signature == signature
            if tool_matches and signature_matches:
                keys_to_delete.append(key)

        for key in keys_to_delete:
            del self.arms[key]
        self.decisions = {
            key: decision
            for key, decision in self.decisions.items()
            if not _decision_matches(decision, tool_name, signature)
        }
        self._save_state()

    def _get_arm(self, tool_name: str, signature: str) -> TrustArm:
        key = _arm_key(tool_name, signature)
        if key not in self.arms:
            self.arms[key] = TrustArm(
                tool_name=tool_name,
                signature=signature,
                last_updated=_format_time(self.now_fn()),
            )
            self._trim_state()
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

    def _load_state(self) -> tuple[dict[str, TrustArm], dict[str, TrustDecision]]:
        payload = self._read_state_payload()
        if payload is None:
            return {}, {}
        try:
            arms = _load_arms(payload.get("arms"))
            decisions = _load_decisions(payload.get("decisions"))
        except (TypeError, ValueError, OverflowError):
            return {}, {}
        return arms, decisions

    def _read_state_payload(self) -> dict[str, Any] | None:
        try:
            stat = self.storage_path.stat()
            if (
                self.storage_path.is_symlink()
                or not self.storage_path.is_file()
                or stat.st_size > MAX_STORAGE_BYTES
            ):
                return None
            data = json.loads(self.storage_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict) or data.get("version") != STORAGE_VERSION:
            return None
        return data

    def _save_state(self) -> None:
        self._trim_state()
        data = {
            "version": STORAGE_VERSION,
            "arms": {key: arm.to_dict() for key, arm in self.arms.items()},
            "decisions": {
                key: decision.to_dict() for key, decision in self.decisions.items()
            },
        }
        atomic_write_json(self.storage_path, data, secure=True)

    def _trim_state(self) -> None:
        self.arms = _keep_newest(self.arms, MAX_ARMS, lambda arm: arm.last_updated)
        self.decisions = _keep_newest(
            self.decisions,
            MAX_DECISIONS,
            lambda decision: decision.created_at,
        )


def classify_tool_tier(tool_name: str) -> str:
    """Classify a tool as tier_one, tier_two, always_confirm, or unknown."""
    if tool_name in ALWAYS_CONFIRM_TOOLS:
        return "always_confirm"
    if tool_name.startswith("browser_"):
        return "tier_two"
    if tool_name in TIER_TWO_TOOLS:
        return "tier_two"
    if tool_name in TIER_ONE_TOOLS:
        return "tier_one"
    return "unknown"


def is_high_impact_action(tool_name: str, tool_input: dict[str, Any]) -> bool:
    """Fail learned approval closed for sensitive Tier 1 action variants."""
    if not isinstance(tool_input, dict):
        return True
    if tool_name == "run_tests" and tool_input.get("test_command"):
        return True
    if tool_name == "git_add":
        paths = tool_input.get("file_paths", [])
        return bool(tool_input.get("all_files")) or _contains_sensitive_path(paths)
    if tool_name in {"write_file", "replace_in_file", "format_code", "lint_code"}:
        return _contains_sensitive_path([tool_input.get("file_path")])
    return False


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
    return f"paths:{_hash_value(patterns)}" if patterns else "none"


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
        return _bounded_path_pattern(f"path:{parent}/*{suffix}")
    return _bounded_path_pattern(f"path:{parent}/*")


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


def _load_arms(value: Any) -> dict[str, TrustArm]:
    if not isinstance(value, dict) or len(value) > MAX_ARMS:
        raise ValueError("invalid trust arm collection")
    arms = {}
    for key, arm_data in value.items():
        if not isinstance(key, str) or not isinstance(arm_data, dict):
            raise ValueError("invalid trust arm entry")
        arm = TrustArm.from_dict(arm_data)
        if key != _arm_key(arm.tool_name, arm.signature):
            raise ValueError("trust arm key mismatch")
        arms[key] = arm
    return arms


def _load_decisions(value: Any) -> dict[str, TrustDecision]:
    if not isinstance(value, dict) or len(value) > MAX_DECISIONS:
        raise ValueError("invalid trust decision collection")
    decisions = {}
    for key, decision_data in value.items():
        if not isinstance(key, str) or not isinstance(decision_data, dict):
            raise ValueError("invalid trust decision entry")
        decision = TrustDecision.from_dict(decision_data)
        if key != decision.decision_id:
            raise ValueError("trust decision key mismatch")
        decisions[key] = decision
    return decisions


def _is_valid_arm(arm: TrustArm) -> bool:
    if classify_tool_tier(arm.tool_name) != "tier_one":
        return False
    if not _is_bounded_text(arm.signature):
        return False
    if not _is_posterior_value(arm.alpha) or not _is_posterior_value(arm.beta):
        return False
    if not _is_bounded_count(arm.observations):
        return False
    return _is_valid_timestamp(arm.last_updated)


def _is_valid_decision(decision: TrustDecision) -> bool:
    if len(decision.decision_id) != 32 or not _is_hex(decision.decision_id):
        return False
    if not _is_bounded_text(decision.tool_name):
        return False
    if not _is_bounded_text(decision.signature):
        return False
    if decision.source not in DECISION_SOURCES:
        return False
    if not isinstance(decision.accepted, bool) or not isinstance(decision.reverted, bool):
        return False
    return _is_valid_timestamp(decision.created_at)


def _is_valid_timestamp(value: str) -> bool:
    if not _is_bounded_text(value):
        return False
    try:
        parsed = _parse_time(value)
    except (TypeError, ValueError):
        return False
    return parsed <= _current_time() + timedelta(minutes=5)


def _is_posterior_value(value: float) -> bool:
    return math.isfinite(value) and 1 <= value <= MAX_POSTERIOR_VALUE


def _is_bounded_count(value: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= MAX_POSTERIOR_VALUE
    )


def _is_bounded_text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_TEXT_LENGTH


def _is_hex(value: str) -> bool:
    return all(character in "0123456789abcdef" for character in value)


def _contains_sensitive_path(values: Any) -> bool:
    if not isinstance(values, list) or not values:
        return True
    found_path = False
    for value in values:
        if not isinstance(value, (str, Path)) or not str(value).strip():
            return True
        found_path = True
        path = Path(str(value))
        if _path_is_sensitive(path):
            return True
    return not found_path


def _path_is_sensitive(path: Path) -> bool:
    resolved_path = path if path.is_absolute() else Path.cwd() / path
    try:
        resolved_path = resolved_path.resolve()
        resolved_path.relative_to(Path.cwd().resolve())
    except (OSError, RuntimeError, ValueError):
        return True
    for candidate in (path, resolved_path):
        lowered_parts = {part.lower() for part in candidate.parts}
        if candidate.name.lower() in SENSITIVE_FILE_NAMES:
            return True
        if candidate.suffix.lower() in SENSITIVE_FILE_SUFFIXES:
            return True
        if lowered_parts & SENSITIVE_PATH_PARTS:
            return True
        if {".github", "workflows"} <= lowered_parts:
            return True
    return False


def _keep_newest(values: dict, limit: int, timestamp_fn) -> dict:
    if len(values) <= limit:
        return values
    newest = sorted(values.items(), key=lambda item: timestamp_fn(item[1]))[-limit:]
    return dict(newest)


def _decision_matches(
    decision: TrustDecision,
    tool_name: str | None,
    signature: str | None,
) -> bool:
    tool_matches = tool_name is None or decision.tool_name == tool_name
    signature_matches = signature is None or decision.signature == signature
    return tool_matches and signature_matches


def _strict_number(value: Any) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("expected numeric value")
    return float(value)


def _strict_count(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("expected integer count")
    return value


def _strict_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("expected text value")
    return value


def _bounded_path_pattern(value: str) -> str:
    if len(value) <= 256:
        return value
    suffix = Path(value).suffix.lower() or "no_ext"
    return f"path_hash:{_hash_value(value)}:{suffix}"
