"""Offline tests for the live-eval provider-spend guard."""

import pytest

from radsim.pricing import ModelPricing
from radsim.request_options import RequestOptions
from tests.evals.budget import BudgetedEvalClient, EvalBudgetExceeded, EvalCostBudget


class StubClient:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = 0
        self.call_kwargs = []

    def chat(self, **kwargs):
        self.calls += 1
        self.call_kwargs.append(kwargs)
        if self.error:
            raise self.error
        return self.responses.pop(0)


def _response(cost):
    return {"content": [], "usage": {"reported_cost_usd": cost}}


def test_cost_cap_stops_the_next_request():
    budget = EvalCostBudget("0.01")
    raw_client = StubClient([_response(0.006), _response(0.004)])
    client = BudgetedEvalClient(raw_client, budget)

    client.chat()
    client.chat()

    with pytest.raises(EvalBudgetExceeded, match="cost cap reached"):
        client.chat()
    assert raw_client.calls == 2
    assert budget.snapshot()["provider_reported_cost_usd"] == "0.010"


def test_missing_cost_fails_closed_before_more_provider_io():
    budget = EvalCostBudget("1")
    raw_client = StubClient([{"content": [], "usage": {}}, _response(0.1)])
    client = BudgetedEvalClient(raw_client, budget)

    client.chat()

    with pytest.raises(EvalBudgetExceeded, match="omitted valid cost data"):
        client.chat()
    assert raw_client.calls == 1
    assert budget.snapshot()["cost_accounting_complete"] is False


def test_distinct_clients_share_one_budget():
    budget = EvalCostBudget("0.01")
    candidate = BudgetedEvalClient(StubClient([_response(0.01)]), budget)
    grader_raw = StubClient([_response(0.001)])
    grader = BudgetedEvalClient(grader_raw, budget)

    candidate.chat()

    with pytest.raises(EvalBudgetExceeded):
        grader.chat()
    assert grader_raw.calls == 0


def test_provider_error_blocks_later_requests():
    budget = EvalCostBudget("1")
    raw_client = StubClient(error=RuntimeError("provider failed"))
    client = BudgetedEvalClient(raw_client, budget)

    with pytest.raises(RuntimeError, match="provider failed"):
        client.chat()
    with pytest.raises(EvalBudgetExceeded, match="failed without cost data"):
        client.chat()
    assert raw_client.calls == 1


def test_budget_snapshot_counts_provider_retry_attempts():
    budget = EvalCostBudget("1")
    response = _response(0.1)
    response["usage"]["retry_attempts"] = 2
    client = BudgetedEvalClient(StubClient([response]), budget)

    client.chat()

    snapshot = budget.snapshot()
    assert snapshot["requests_started"] == 1
    assert snapshot["provider_attempts"] == 3


def test_eval_response_uses_one_immutable_pricing_snapshot_for_estimate():
    budget = EvalCostBudget("1")
    pricing = ModelPricing(
        provider="openrouter",
        billing_mode="routing",
        model="vendor/model",
        input_per_million_usd="1",
        output_per_million_usd="2",
        source="catalogue-cache",
        fetched_at="2026-08-04T00:00:00Z",
    )
    response = _response(0.1)
    response["usage"].update({"input_tokens": 1_000, "output_tokens": 500})
    client = BudgetedEvalClient(StubClient([response]), budget, pricing)

    result = client.chat()

    assert result["usage"]["estimated_cost_usd"] == pytest.approx(0.002)
    assert result["usage"]["pricing_source"] == "catalogue-cache"


def test_eval_client_pins_request_options_for_every_call():
    budget = EvalCostBudget("1")
    raw_client = StubClient([_response(0.1)])
    options = RequestOptions(temperature=0.0, top_p=1.0, seed=42)
    client = BudgetedEvalClient(raw_client, budget, request_options=options)

    client.chat()

    assert raw_client.calls == 1
    assert raw_client.call_kwargs == [{"request_options": options}]


def test_eval_client_rejects_request_option_drift_before_provider_io():
    budget = EvalCostBudget("1")
    raw_client = StubClient([_response(0.1)])
    options = RequestOptions(temperature=0.0, top_p=1.0, seed=42)
    client = BudgetedEvalClient(raw_client, budget, request_options=options)

    with pytest.raises(ValueError, match="cannot change"):
        client.chat(request_options=RequestOptions(seed=43))

    assert raw_client.calls == 0
    assert budget.snapshot()["requests_started"] == 0


@pytest.mark.parametrize("cost", [None, -1, float("inf"), "invalid", True])
def test_invalid_cost_values_fail_closed(cost):
    budget = EvalCostBudget("1")
    client = BudgetedEvalClient(StubClient([_response(cost)]), budget)

    client.chat()

    assert budget.snapshot()["blocked_reason"] is not None
