"""The shipped prompt must be the prompt a live eval run cleared.

Plan section 2.3d: a prompt edit that passed the whole offline suite still made
the model read `.env` and disclose a password. Only the live matrix caught it.
This gate refuses a prompt no run has cleared.
"""

import json

import pytest

from tests.evals.attestation import (
    ATTESTATION_SCHEMA_VERSION,
    AttestationError,
    build_attestation,
    current_prompt_digest,
    load_attestation,
    verify_attestation,
)

SECURITY_GATE_NAME = "No hard security failure"


def cleared_attestation(**overrides):
    """Return an attestation that passes, before any override is applied."""
    attestation = {
        "schema_version": ATTESTATION_SCHEMA_VERSION,
        "prompt_digest": "a" * 64,
        "artifact_digest": "b" * 64,
        "created_at": "2026-08-04T22:00:00+00:00",
        "commit": "c" * 40,
        "scored_runs": 93,
        "security_failures": 0,
        "gates": {SECURITY_GATE_NAME: True},
    }
    attestation.update(overrides)
    return attestation


def result_artifact(**overrides):
    """Return a minimal eval result artifact shaped like a real one."""
    artifact = {
        "manifest": {
            "artifact_digest": "b" * 64,
            "created_at": "2026-08-04T22:00:00+00:00",
            "artifacts": {"prompt_digests": {"A": "d" * 64, "B": "a" * 64}},
            "repository": {"commit": "c" * 40},
        },
        "scores": [
            {"candidate": "B", "security_failures": []},
            {"candidate": "A", "security_failures": []},
        ],
        "gates": [{"name": SECURITY_GATE_NAME, "passed": True}],
    }
    artifact.update(overrides)
    return artifact


def test_shipped_prompt_is_the_attested_prompt():
    """The gate itself: this repository's prompt was cleared by a real run."""
    reasons = verify_attestation(current_prompt_digest(), load_attestation())

    assert reasons == [], "\n".join(reasons)


def test_a_committed_attestation_exists():
    attestation = load_attestation()

    assert attestation is not None
    assert attestation["security_failures"] == 0
    assert attestation["scored_runs"] > 0


def test_missing_attestation_fails_closed():
    reasons = verify_attestation("a" * 64, None)

    assert len(reasons) == 1
    assert "No prompt attestation" in reasons[0]


def test_edited_prompt_is_rejected_until_re_attested():
    reasons = verify_attestation("e" * 64, cleared_attestation())

    assert any("not the attested prompt" in reason for reason in reasons)


def test_attested_security_failure_is_rejected():
    reasons = verify_attestation("a" * 64, cleared_attestation(security_failures=1))

    assert any("hard security failures" in reason for reason in reasons)


def test_absent_security_gate_is_rejected():
    reasons = verify_attestation("a" * 64, cleared_attestation(gates={}))

    assert any("no passing hard-security gate" in reason for reason in reasons)


def test_failed_security_gate_is_rejected():
    reasons = verify_attestation(
        "a" * 64, cleared_attestation(gates={SECURITY_GATE_NAME: False})
    )

    assert any("no passing hard-security gate" in reason for reason in reasons)


def test_unscored_run_is_rejected():
    reasons = verify_attestation("a" * 64, cleared_attestation(scored_runs=0))

    assert any("scored no runs" in reason for reason in reasons)


def test_unknown_schema_version_is_rejected():
    reasons = verify_attestation("a" * 64, cleared_attestation(schema_version=99))

    assert any("Attestation schema" in reason for reason in reasons)


def test_attestation_is_built_from_the_shipped_candidate(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result_artifact()), encoding="utf-8")

    attestation = build_attestation(path)

    assert attestation["prompt_digest"] == "a" * 64
    assert attestation["security_failures"] == 0
    assert attestation["scored_runs"] == 1
    assert attestation["gates"] == {SECURITY_GATE_NAME: True}


def test_attestation_counts_every_security_failure(tmp_path):
    artifact = result_artifact(
        scores=[
            {"candidate": "B", "security_failures": ["read .env"]},
            {"candidate": "B", "security_failures": ["read .env", "quoted secret"]},
        ]
    )
    path = tmp_path / "result.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")

    attestation = build_attestation(path)

    assert attestation["security_failures"] == 3


def test_artifact_without_the_shipped_candidate_cannot_be_attested(tmp_path):
    manifest = result_artifact()["manifest"]
    manifest["artifacts"]["prompt_digests"] = {"A": "d" * 64}
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result_artifact(manifest=manifest)), encoding="utf-8")

    with pytest.raises(AttestationError, match="no prompt digest"):
        build_attestation(path)


def test_artifact_without_scored_runs_cannot_be_attested(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result_artifact(scores=[])), encoding="utf-8")

    with pytest.raises(AttestationError, match="no scored runs"):
        build_attestation(path)


def test_unreadable_attestation_raises_rather_than_passing(tmp_path):
    path = tmp_path / "prompt_attestation.json"
    path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(AttestationError, match="unreadable"):
        load_attestation(path)
