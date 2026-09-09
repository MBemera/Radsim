"""Provider prompt caching for RadSim's stable request prefix.

Anthropic renders a request as tools, then system, then messages, and caches by
exact prefix match. RadSim's system prompt is already layered stable-first:
:func:`radsim.prompts.get_static_prompt` returns the repository-controlled
policy that opens every request, and runtime layers (modes, skills, custom text,
project memory) follow it.

Marking the end of that static policy caches the routed tool schemas and the
policy together. Marking the last conversation block caches the turn's history,
which is re-sent on every tool round.

Caching changes cost and latency only. It never changes the prompt text, the
tool set, or any permission decision.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

CACHING_ENV_VAR = "RADSIM_PROMPT_CACHING"
EPHEMERAL_CACHE_CONTROL = {"type": "ephemeral"}
DEFAULT_MINIMUM_CACHEABLE_TOKENS = 1_024

_FALSY_VALUES = {"0", "false", "no", "off"}

# Provider minimum cacheable prefix, longest-lived families first. A shorter
# prefix is silently not cached, so RadSim skips the breakpoint and says why.
_MODEL_MINIMUM_CACHEABLE_TOKENS = (
    ("claude-opus-4-5", 4_096),
    ("claude-opus-4-6", 4_096),
    ("claude-haiku-4-5", 4_096),
    ("claude-opus-4-7", 2_048),
    ("claude-3-5-haiku", 2_048),
    ("claude-opus-5", 512),
    ("claude-fable-5", 512),
    ("claude-mythos-5", 512),
)

_CACHEABLE_MODEL_MARKERS = ("claude", "anthropic/")


@dataclass(frozen=True)
class SystemCachePlan:
    """The system blocks to send plus the evidence for the decision."""

    blocks: list[dict[str, Any]] | None
    prefix_tokens: int
    minimum_tokens: int
    skipped_reason: str

    @property
    def is_cached(self) -> bool:
        """Return whether a cache breakpoint was placed."""
        return self.blocks is not None


def caching_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether prompt caching is switched on for this process."""
    source = os.environ if environ is None else environ
    return source.get(CACHING_ENV_VAR, "").strip().lower() not in _FALSY_VALUES


def model_supports_caching(model: str) -> bool:
    """Return whether explicit cache breakpoints are valid for this model."""
    lowered = (model or "").lower()
    return any(marker in lowered for marker in _CACHEABLE_MODEL_MARKERS)


def minimum_cacheable_tokens(model: str) -> int:
    """Return the provider's minimum cacheable prefix for this model."""
    lowered = (model or "").lower()
    for marker, minimum in _MODEL_MINIMUM_CACHEABLE_TOKENS:
        if marker in lowered:
            return minimum
    return DEFAULT_MINIMUM_CACHEABLE_TOKENS


def estimate_tokens(text: str) -> int:
    """Estimate tokens using RadSim's existing four-characters-per-token rule."""
    return (len(text) + 3) // 4 if text else 0


def plan_system_cache(
    system_prompt: str,
    *,
    model: str,
    tool_schema_tokens: int = 0,
    environ: Mapping[str, str] | None = None,
) -> SystemCachePlan:
    """Decide where the system cache breakpoint goes for one request."""
    minimum = minimum_cacheable_tokens(model)
    stable_prefix = _stable_prefix(system_prompt)
    prefix_tokens = tool_schema_tokens + estimate_tokens(stable_prefix)

    reason = _skip_reason(system_prompt, model, prefix_tokens, minimum, environ)
    if reason:
        return SystemCachePlan(None, prefix_tokens, minimum, reason)

    return SystemCachePlan(
        _system_blocks(stable_prefix, system_prompt[len(stable_prefix) :]),
        prefix_tokens,
        minimum,
        "",
    )


def mark_conversation_breakpoint(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return messages with the final content block marked cacheable.

    Only block-list content is marked. A plain-string message is left alone
    rather than reshaped, so message structure the provider validates against
    tool-use pairing is never rewritten to win a cache entry.
    """
    if not messages:
        return messages

    last_message = messages[-1]
    content = last_message.get("content") if isinstance(last_message, dict) else None
    if not isinstance(content, list) or not content:
        return messages
    if not all(isinstance(block, dict) for block in content):
        return messages

    marked_content = list(content[:-1]) + [
        {**content[-1], "cache_control": EPHEMERAL_CACHE_CONTROL}
    ]
    return list(messages[:-1]) + [{**last_message, "content": marked_content}]


def _skip_reason(
    system_prompt: str,
    model: str,
    prefix_tokens: int,
    minimum: int,
    environ: Mapping[str, str] | None,
) -> str:
    """Return why caching was skipped, or an empty string when it applies."""
    if not caching_enabled(environ):
        return "disabled"
    if not system_prompt:
        return "no_system_prompt"
    if not model_supports_caching(model):
        return "unsupported_model"
    if prefix_tokens < minimum:
        return "below_minimum"
    return ""


def _system_blocks(stable_prefix: str, remainder: str) -> list[dict[str, Any]]:
    """Return the cached stable block plus any uncached runtime remainder."""
    blocks = [
        {
            "type": "text",
            "text": stable_prefix,
            "cache_control": EPHEMERAL_CACHE_CONTROL,
        }
    ]
    if remainder:
        blocks.append({"type": "text", "text": remainder})
    return blocks


def _stable_prefix(system_prompt: str) -> str:
    """Return the repository-controlled policy that opens the system prompt.

    Falls back to the whole prompt when the static layers are unavailable or no
    longer lead the composed prompt: caching the whole prompt stays correct, it
    just loses its resilience to runtime layers changing.
    """
    try:
        from .prompts import get_static_prompt

        static_prompt = get_static_prompt()
    except Exception:
        return system_prompt

    if static_prompt and system_prompt.startswith(static_prompt):
        return static_prompt
    return system_prompt
