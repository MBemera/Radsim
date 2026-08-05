"""Contracts for explicit, model-aware conversation context budgets."""

import pytest

from radsim.context_budget import ContextBudget


def test_large_model_uses_conservative_configured_input_cap():
    budget = ContextBudget(model_context_tokens=1_048_576)

    assert budget.provider_input_tokens == 1_032_576
    assert budget.effective_input_tokens == 80_000
    assert budget.prune_target_tokens == 70_000


def test_small_model_reserves_output_before_accepting_input():
    budget = ContextBudget(
        model_context_tokens=20_000,
        configured_input_tokens=80_000,
        output_reserve_tokens=16_000,
        recovery_tokens=10_000,
    )

    assert budget.provider_input_tokens == 4_000
    assert budget.effective_input_tokens == 4_000
    assert budget.prune_target_tokens == 3_000


def test_zero_configured_cap_uses_provider_input_limit():
    budget = ContextBudget(
        model_context_tokens=100_000,
        configured_input_tokens=0,
        output_reserve_tokens=10_000,
    )

    assert budget.effective_input_tokens == 90_000


def test_remaining_session_budget_is_a_hard_context_cap():
    budget = ContextBudget(
        model_context_tokens=1_000_000,
        remaining_session_input_tokens=5_000,
    )

    assert budget.effective_input_tokens == 5_000
    assert budget.prune_target_tokens == 3_750


def test_output_reserve_larger_than_context_fails_closed_to_zero_input():
    budget = ContextBudget(model_context_tokens=1_000, output_reserve_tokens=2_000)

    assert budget.provider_input_tokens == 0
    assert budget.effective_input_tokens == 0
    assert budget.prune_target_tokens == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_context_tokens", 0),
        ("model_context_tokens", True),
        ("configured_input_tokens", -1),
        ("output_reserve_tokens", 0),
        ("recovery_tokens", -1),
        ("remaining_session_input_tokens", -1),
    ],
)
def test_invalid_budget_values_are_rejected(field, value):
    values = {"model_context_tokens": 100_000, field: value}

    with pytest.raises(ValueError):
        ContextBudget(**values)
