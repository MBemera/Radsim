"""Validated, explicit model sampling options."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

REQUEST_OPTION_NAMES = frozenset({"temperature", "top_p", "seed"})
MAX_SAMPLING_SEED = 2**32 - 1


@dataclass(frozen=True)
class RequestOptions:
    """Optional sampling controls for one model request."""

    temperature: float | None = None
    top_p: float | None = None
    seed: int | None = None

    def __post_init__(self) -> None:
        _validate_float("temperature", self.temperature, 0.0, 2.0)
        _validate_float("top_p", self.top_p, 0.0, 1.0)
        _validate_seed(self.seed)

    def for_supported(self, supported_parameters: Iterable[str]) -> dict[str, Any]:
        """Return only explicitly set fields supported by the selected model."""
        supported = frozenset(supported_parameters) & REQUEST_OPTION_NAMES
        values = self.as_dict()
        return {
            name: value
            for name, value in values.items()
            if value is not None and name in supported
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "seed": self.seed,
        }


def _validate_float(name: str, value: float | None, minimum: float, maximum: float) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")


def _validate_seed(value: int | None) -> None:
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("seed must be an integer")
    if not 0 <= value <= MAX_SAMPLING_SEED:
        raise ValueError(f"seed must be between 0 and {MAX_SAMPLING_SEED}")
