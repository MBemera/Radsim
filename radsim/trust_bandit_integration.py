"""Confirmation helpers that connect RadSim prompts to the trust bandit."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from .output import print_info
from .trust_bandit import build_action_signature, get_trust_bandit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DecisionReceipt:
    """In-process link between a confirmation and its undo checkpoint."""

    decision_id: str
    tool_name: str
    signature: str


_latest_decision: ContextVar[DecisionReceipt | None] = ContextVar(
    "latest_trust_decision",
    default=None,
)


def confirm_with_bandit(
    tool_name: str,
    tool_input: dict[str, Any],
    message: str,
    config=None,
) -> bool:
    """Confirm an action, using trust data only when it is safe to do so."""
    if not is_trust_enabled(config):
        return _prompt_user(message, config)

    try:
        bandit = get_trust_bandit()
        auto_confirm, reason = bandit.should_auto_confirm(tool_name, tool_input)
        if auto_confirm:
            print_info(f"Auto: {tool_name} ({reason})")
            decision_id = bandit.record_decision(
                tool_name,
                tool_input,
                accepted=True,
                source="learned_auto",
                learn=False,
            )
            _remember_decision(decision_id, tool_name, tool_input)
            return True
    except Exception:
        logger.debug("Trust bandit check failed", exc_info=True)
        return _prompt_user(message, config)

    confirmed = _prompt_user(message, config)
    record_user_decision(tool_name, tool_input, accepted=confirmed, config=config)
    return confirmed


def should_auto_confirm_action(
    tool_name: str,
    tool_input: dict[str, Any],
    config=None,
) -> tuple[bool, str]:
    """Return a bandit auto-confirm decision without prompting the user."""
    if not is_trust_enabled(config):
        return False, "trust_disabled"

    try:
        bandit = get_trust_bandit()
        auto_confirm, reason = bandit.should_auto_confirm(tool_name, tool_input)
        if auto_confirm:
            decision_id = bandit.record_decision(
                tool_name,
                tool_input,
                accepted=True,
                source="learned_auto",
                learn=False,
            )
            _remember_decision(decision_id, tool_name, tool_input)
        return auto_confirm, reason
    except Exception:
        logger.debug("Trust bandit check failed", exc_info=True)
        return False, "trust_unavailable"


def record_user_decision(
    tool_name: str,
    tool_input: dict[str, Any],
    accepted: bool,
    config=None,
) -> str | None:
    """Record a user decision when trust learning is enabled."""
    if not is_trust_enabled(config):
        return None

    try:
        decision_id = get_trust_bandit().record_decision(
            tool_name,
            tool_input,
            accepted=accepted,
            source="user_prompt",
            learn=True,
        )
        _remember_decision(decision_id, tool_name, tool_input)
        return decision_id
    except Exception:
        logger.debug("Trust bandit outcome recording failed", exc_info=True)
        return None


def consume_decision_id(tool_name: str, tool_input: dict[str, Any]) -> str | None:
    """Consume only the decision produced for this exact action signature."""
    receipt = _latest_decision.get()
    _latest_decision.set(None)
    if receipt is None or receipt.tool_name != tool_name:
        return None
    if receipt.signature != build_action_signature(tool_name, tool_input):
        return None
    return receipt.decision_id


def record_matched_revert(decision_id: str | None, config=None) -> bool:
    """Record one undo only when its persisted decision ID is valid and fresh."""
    if not decision_id or not is_trust_enabled(config):
        return False
    try:
        return get_trust_bandit().record_revert(decision_id)
    except Exception:
        logger.debug("Trust bandit revert recording failed", exc_info=True)
        return False


def record_execution_decision(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    accepted: bool,
    config=None,
) -> str | None:
    """Audit a policy decision that did not pass through learned trust."""
    if not is_trust_enabled(config):
        return None
    source = "explicit_auto" if getattr(config, "auto_confirm", False) else "user_prompt"
    try:
        return get_trust_bandit().record_decision(
            tool_name,
            tool_input,
            accepted=accepted,
            source=source,
            learn=False,
        )
    except Exception:
        logger.debug("Trust execution decision recording failed", exc_info=True)
        return None


def is_trust_enabled(config=None) -> bool:
    """Return whether learned trust is enabled for this session."""
    return getattr(config, "trust_mode", "medium") != "low"


def _prompt_user(message: str, config=None) -> bool:
    from .safety import confirm_action

    return confirm_action(message, config=config)


def _remember_decision(
    decision_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
) -> None:
    _latest_decision.set(
        DecisionReceipt(
            decision_id=decision_id,
            tool_name=tool_name,
            signature=build_action_signature(tool_name, tool_input),
        )
    )
