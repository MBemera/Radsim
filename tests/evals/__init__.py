"""Behavioural eval matrix for the RadSim system prompt.

Unit tests prove the runtime fails closed. These evals measure something the
runtime cannot: whether the model behaves well when the prompt is the only
thing standing between it and a bad action.

Run them with ``python -m tests.evals.run_evals`` from the repository root.
They make live model calls and are never collected by pytest.
"""
