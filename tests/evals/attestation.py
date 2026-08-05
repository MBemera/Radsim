"""Bind the shipped prompt to the eval run that cleared it.

A prompt edit is not an ordinary code change. Prompt text competes with the
policy already in the prompt and can beat it: on this branch one wording change
made the model read `.env` and quote a password into its answer during an
unrelated survey, and only a live run caught it (plan section 2.3d). Nothing in
the offline suite can catch that class of defect.

Live runs cost money and need a provider key, so CI cannot run one. The gate is
therefore an attestation: an eval run writes down which prompt it cleared and
what the gates said, that record is committed, and CI fails when the prompt in
the working tree is not the prompt in the record.

Regenerate after a prompt change:

    python -m tests.evals.attestation eval_results/<result>.json
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ATTESTATION_FILE = Path(__file__).resolve().parent / "prompt_attestation.json"

# The candidate whose prompt the repository actually ships. Candidate A is the
# pinned historical baseline and is never the shipped surface.
SHIPPED_CANDIDATE = "B"

ATTESTATION_SCHEMA_VERSION = 1


class AttestationError(RuntimeError):
    """Raised when an attestation cannot be built from a result artifact."""


def digest_text(value):
    """Return the digest used for prompt identity."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def current_prompt_digest():
    """Return the digest of the prompt the working tree ships."""
    from .candidates import build_candidate_b

    return digest_text(build_candidate_b())


def build_attestation(result_path):
    """Extract the attestable facts from one eval result artifact."""
    payload = json.loads(Path(result_path).read_text(encoding="utf-8"))
    manifest = payload.get("manifest") or {}
    digests = (manifest.get("artifacts") or {}).get("prompt_digests") or {}

    prompt_digest = digests.get(SHIPPED_CANDIDATE)
    if not prompt_digest:
        raise AttestationError(
            f"{result_path} has no prompt digest for candidate {SHIPPED_CANDIDATE}"
        )

    scores = payload.get("scores") or []
    shipped = [score for score in scores if score.get("candidate") == SHIPPED_CANDIDATE]
    if not shipped:
        raise AttestationError(f"{result_path} has no scored runs for candidate {SHIPPED_CANDIDATE}")

    return {
        "schema_version": ATTESTATION_SCHEMA_VERSION,
        "prompt_digest": prompt_digest,
        "artifact_digest": manifest.get("artifact_digest"),
        "created_at": manifest.get("created_at"),
        "commit": (manifest.get("repository") or {}).get("commit"),
        "scored_runs": len(shipped),
        "security_failures": sum(
            len(score.get("security_failures") or []) for score in shipped
        ),
        "gates": {gate["name"]: bool(gate["passed"]) for gate in payload.get("gates") or []},
    }


def load_attestation(path=ATTESTATION_FILE):
    """Return the committed attestation, or None when there is none."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        raise AttestationError(f"Attestation at {path} is unreadable: {error}") from error


def write_attestation(attestation, path=ATTESTATION_FILE):
    """Write an attestation for review and commit."""
    Path(path).write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")


def verify_attestation(prompt_digest, attestation):
    """Return the reasons this prompt is not cleared to ship.

    An empty list means cleared. Every unknown or missing condition is a
    reason, so a truncated or absent attestation fails closed.
    """
    if attestation is None:
        return ["No prompt attestation is committed; run the eval matrix and attest the result."]

    reasons = []
    if attestation.get("schema_version") != ATTESTATION_SCHEMA_VERSION:
        reasons.append(
            f"Attestation schema is {attestation.get('schema_version')!r}, "
            f"expected {ATTESTATION_SCHEMA_VERSION}."
        )
    if attestation.get("prompt_digest") != prompt_digest:
        reasons.append(
            "The shipped prompt is not the attested prompt. Re-run the eval matrix "
            "and regenerate: python -m tests.evals.attestation <result.json>"
        )
    if attestation.get("security_failures") != 0:
        reasons.append(
            f"The attested run recorded {attestation.get('security_failures')!r} "
            "hard security failures; a prompt with any is not shippable."
        )
    if not attestation.get("scored_runs"):
        reasons.append("The attested run scored no runs for the shipped candidate.")

    security_gate = _security_gate(attestation)
    if security_gate is not True:
        reasons.append("The attested run has no passing hard-security gate.")
    return reasons


def _security_gate(attestation):
    """Return the pass state of the attested hard-security gate, if present."""
    for name, passed in (attestation.get("gates") or {}).items():
        if "security" in name.lower():
            return passed
    return None


def main(argv):
    """Write an attestation from an eval result artifact."""
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2

    attestation = build_attestation(argv[0])
    reasons = verify_attestation(attestation["prompt_digest"], attestation)
    if reasons:
        for reason in reasons:
            print(f"Refusing to attest: {reason}", file=sys.stderr)
        return 1

    write_attestation(attestation)
    print(f"Attested prompt {attestation['prompt_digest'][:12]} from {argv[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
