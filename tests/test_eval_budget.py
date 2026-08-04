"""Offline tests for the live-eval provider-spend guard."""

import pytest

from tests.evals.budget import BudgetedEvalClient, EvalBudgetExceeded, EvalCostBudget


class StubClient:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = 0

    def chat(self, **_kwargs):
        self.calls += 1
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


@pytest.mark.parametrize("cost", [None, -1, float("inf"), "invalid", True])
def test_invalid_cost_values_fail_closed(cost):
    budget = EvalCostBudget("1")
    client = BudgetedEvalClient(StubClient([_response(cost)]), budget)

    client.chat()

    assert budget.snapshot()["blocked_reason"] is not None
