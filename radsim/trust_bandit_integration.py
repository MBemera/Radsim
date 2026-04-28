"""Confirmation helpers that connect RadSim prompts to the trust bandit."""

from __future__ import annotations

import logging
from typing import Any

from .output import print_info
from .trust_bandit import get_trust_bandit

logger = logging.getLogger(__name__)


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
            bandit.record_outcome(tool_name, tool_input, accepted=True)
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
        return get_trust_bandit().should_auto_confirm(tool_name, tool_input)
    except Exception:
        logger.debug("Trust bandit check failed", exc_info=True)
        return False, "trust_unavailable"


def record_user_decision(
    tool_name: str,
    tool_input: dict[str, Any],
    accepted: bool,
    config=None,
) -> bool:
    """Record a user decision when trust learning is enabled."""
    if not is_trust_enabled(config):
        return False

    try:
        return get_trust_bandit().record_outcome(tool_name, tool_input, accepted=accepted)
    except Exception:
        logger.debug("Trust bandit outcome recording failed", exc_info=True)
        return False


def is_trust_enabled(config=None) -> bool:
    """Return whether learned trust is enabled for this session."""
    return getattr(config, "trust_mode", "medium") != "low"


def _prompt_user(message: str, config=None) -> bool:
    from .safety import confirm_action

    return confirm_action(message, config=config)
