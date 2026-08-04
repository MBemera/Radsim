"""Explicit model, output, and session bounds for conversation context."""

from __future__ import annotations

from dataclasses import asdict, dataclass

DEFAULT_CONTEXT_INPUT_TOKENS = 80_000
DEFAULT_CONTEXT_OUTPUT_RESERVE_TOKENS = 16_000
DEFAULT_CONTEXT_RECOVERY_TOKENS = 10_000
MAX_CONTEXT_SETTING_TOKENS = 10_000_000


@dataclass(frozen=True)
class ContextBudget:
    """Resolved input limits for one upcoming provider request."""

    model_context_tokens: int
    configured_input_tokens: int = DEFAULT_CONTEXT_INPUT_TOKENS
    output_reserve_tokens: int = DEFAULT_CONTEXT_OUTPUT_RESERVE_TOKENS
    recovery_tokens: int = DEFAULT_CONTEXT_RECOVERY_TOKENS
    remaining_session_input_tokens: int | None = None

    def __post_init__(self) -> None:
        _validate_positive("model_context_tokens", self.model_context_tokens)
        _validate_nonnegative("configured_input_tokens", self.configured_input_tokens)
        _validate_positive("output_reserve_tokens", self.output_reserve_tokens)
        _validate_nonnegative("recovery_tokens", self.recovery_tokens)
        if self.remaining_session_input_tokens is not None:
            _validate_nonnegative(
                "remaining_session_input_tokens",
                self.remaining_session_input_tokens,
            )

    @property
    def provider_input_tokens(self) -> int:
        """Return model context remaining after reserving model output."""
        return max(0, self.model_context_tokens - self.output_reserve_tokens)

    @property
    def effective_input_tokens(self) -> int:
        """Return the narrowest provider, configured, and session input cap."""
        candidates = [self.provider_input_tokens]
        if self.configured_input_tokens:
            candidates.append(self.configured_input_tokens)
        if self.remaining_session_input_tokens is not None:
            candidates.append(self.remaining_session_input_tokens)
        return min(candidates)

    @property
    def prune_target_tokens(self) -> int:
        """Return the post-prune target with explicit recovery headroom."""
        maximum_recovery = self.effective_input_tokens // 4
        recovery = min(self.recovery_tokens, maximum_recovery)
        return self.effective_input_tokens - recovery

    def as_dict(self) -> dict[str, int | None]:
        """Return resolved source values and computed request bounds."""
        return {
            **asdict(self),
            "provider_input_tokens": self.provider_input_tokens,
            "effective_input_tokens": self.effective_input_tokens,
            "prune_target_tokens": self.prune_target_tokens,
        }


def _validate_positive(name: str, value: int) -> None:
    if not _is_bounded_integer(value) or value <= 0:
        raise ValueError(f"{name} must be a positive bounded integer")


def _validate_nonnegative(name: str, value: int) -> None:
    if not _is_bounded_integer(value) or value < 0:
        raise ValueError(f"{name} must be a non-negative bounded integer")


def _is_bounded_integer(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value <= MAX_CONTEXT_SETTING_TOKENS
    )
