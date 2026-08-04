"""Offline tests for eval preflight, bounds, and provenance."""

import argparse
import json

import pytest

from tests.evals.preflight import prepare_preflight
from tests.evals.run_evals import build_client, main, parse_arguments


def _arguments(*extra: str) -> argparse.Namespace:
    return parse_arguments(
        [
            "--provider",
            "openrouter",
            "--model",
            "z-ai/glm-5.2",
            "--candidates",
            "B",
            "--cases",
            "T02",
            *extra,
        ]
    )


def test_paid_run_requires_explicit_cost_limit():
    with pytest.raises(SystemExit, match="--max-cost-usd"):
        prepare_preflight(_arguments(), "openrouter", "z-ai/glm-5.2")


@pytest.mark.parametrize("cost_limit", ["0", "-1", "nan", "inf", "invalid"])
def test_cost_limit_must_be_positive_and_finite(cost_limit):
    with pytest.raises(SystemExit, match="positive finite"):
        prepare_preflight(
            _arguments("--max-cost-usd", cost_limit),
            "openrouter",
            "z-ai/glm-5.2",
        )


def test_manifest_contains_provenance_without_credentials():
    preflight = prepare_preflight(
        _arguments("--dry-run"),
        "openrouter",
        "z-ai/glm-5.2",
    )

    encoded = json.dumps(preflight.manifest)
    assert preflight.manifest["schema_version"] == 1
    assert len(preflight.manifest["artifact_digest"]) == 64
    assert preflight.manifest["execution"]["case_runs"] == 3
    assert preflight.manifest["execution"]["logical_request_limit"] == 21
    assert preflight.manifest["selection"]["reasoning_effort"] == "high"
    assert "api_key" not in encoded.lower()
    assert "OPENROUTER_API_KEY" not in encoded


def test_manifest_digest_changes_with_candidate_prompt(monkeypatch):
    first = prepare_preflight(_arguments("--dry-run"), "openrouter", "z-ai/glm-5.2")
    monkeypatch.setattr("tests.evals.preflight.get_candidate", lambda name: (name, "changed"))
    second = prepare_preflight(_arguments("--dry-run"), "openrouter", "z-ai/glm-5.2")

    assert first.manifest["artifact_digest"] != second.manifest["artifact_digest"]


def test_dry_run_never_reads_credentials_or_builds_a_client(monkeypatch, capsys):
    monkeypatch.setattr(
        "tests.evals.run_evals.resolve_api_key",
        lambda _provider: pytest.fail("credential should not be read"),
    )
    monkeypatch.setattr(
        "tests.evals.run_evals.build_client",
        lambda *_args: pytest.fail("client should not be built"),
    )

    exit_code = main(
        [
            "--dry-run",
            "--provider",
            "openrouter",
            "--model",
            "z-ai/glm-5.2",
            "--candidates",
            "B",
            "--cases",
            "T02",
        ]
    )

    assert exit_code == 0
    assert "Preflight:" in capsys.readouterr().out


def test_timeout_and_concurrency_are_bounded():
    for options in (
        ("--workers", "0"),
        ("--workers", "33"),
        ("--request-timeout-seconds", "0"),
        ("--request-timeout-seconds", "601"),
        ("--max-iterations", "51"),
    ):
        with pytest.raises(SystemExit):
            prepare_preflight(_arguments("--dry-run", *options), "openrouter", "z-ai/glm-5.2")


def test_unknown_provider_fails_before_client_creation():
    with pytest.raises(SystemExit, match="Unsupported provider"):
        prepare_preflight(_arguments("--dry-run"), "untrusted", "model")


def test_explicit_efforts_are_recorded_for_candidate_and_grader():
    preflight = prepare_preflight(
        _arguments(
            "--dry-run",
            "--effort",
            "xhigh",
            "--grader-model",
            "z-ai/glm-5.2",
            "--grader-effort",
            "high",
        ),
        "openrouter",
        "z-ai/glm-5.2",
    )

    assert preflight.reasoning_effort == "xhigh"
    assert preflight.grader_effort == "high"
    assert preflight.manifest["selection"]["grader_effort"] == "high"


def test_unsupported_effort_fails_preflight():
    with pytest.raises(SystemExit, match="accepts reasoning efforts"):
        prepare_preflight(
            _arguments("--dry-run", "--effort", "low"),
            "openrouter",
            "z-ai/glm-5.2",
        )


def test_build_client_receives_resolved_effort_and_timeout(monkeypatch):
    captured = {}

    def create_client(provider, api_key, model, reasoning_effort=None, timeout=None):
        captured.update(
            provider=provider,
            api_key=api_key,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout=timeout,
        )
        return "client"

    monkeypatch.setattr("radsim.api_client.create_client", create_client)

    client = build_client("openrouter", "test-key-not-real", "z-ai/glm-5.2", "high", 30.0)

    assert client == "client"
    assert captured == {
        "provider": "openrouter",
        "api_key": "test-key-not-real",
        "model": "z-ai/glm-5.2",
        "reasoning_effort": "high",
        "timeout": 30.0,
    }
