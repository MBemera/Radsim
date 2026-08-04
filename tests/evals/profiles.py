"""Two documented eval profiles: full release evidence, and a routine signal.

`release` runs both candidates live and produces evidence a version can ship on.
`commit` runs only the current prompt and reuses candidate A from a stored,
digest-compatible result. That is cheaper but weaker, so every path that reuses
data labels the comparison provisional and prints where the baseline came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .results import load_latest_compatible

RELEASE_PROFILE = "release"
COMMIT_PROFILE = "commit"
PROFILE_NAMES = (RELEASE_PROFILE, COMMIT_PROFILE)

PROFILE_CANDIDATES = {
    RELEASE_PROFILE: "A,B",
    COMMIT_PROFILE: "B",
}
PROFILE_REPETITIONS = 3
MAX_BASELINE_AGE_DAYS = 14


@dataclass
class ReusedBaseline:
    """Candidate A samples loaded from a stored compatible result."""

    scores: list[Any] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        """Whether reusable baseline samples were actually found."""
        return bool(self.scores)


def apply_profile(arguments: Any, default_candidates: str, default_repetitions: int) -> None:
    """Fix candidates and repetitions for the selected profile.

    An explicit `--candidates` or `--reps` alongside a profile is rejected
    rather than silently overridden: a profile whose shape can be edited is
    not a profile, and a reader of the manifest could not tell which won.
    """
    profile = getattr(arguments, "profile", None)
    if profile is None:
        return
    if profile not in PROFILE_NAMES:
        raise SystemExit(f"Unknown profile '{profile}'. Expected one of {PROFILE_NAMES}.")

    if arguments.candidates != default_candidates:
        raise SystemExit(
            f"--profile {profile} fixes --candidates to "
            f"'{PROFILE_CANDIDATES[profile]}'. Drop one of the two flags."
        )
    if arguments.reps != default_repetitions:
        raise SystemExit(
            f"--profile {profile} fixes --reps to {PROFILE_REPETITIONS}. "
            "Drop one of the two flags."
        )

    if profile == RELEASE_PROFILE and getattr(arguments, "max_cost_usd", None) is None:
        raise SystemExit(
            "--profile release requires an explicit --max-cost-usd, including on "
            "a dry run: the dry run exists to validate the shape of the paid run."
        )

    arguments.candidates = PROFILE_CANDIDATES[profile]
    arguments.reps = PROFILE_REPETITIONS


def load_reused_baseline(
    profile: str | None,
    result_directory: str,
    current_manifest: dict[str, Any],
    *,
    now: datetime | None = None,
) -> ReusedBaseline:
    """Load candidate A from stored results, or explain why it cannot be used.

    `release` never reuses: release evidence must be measured, not recalled.
    """
    if profile != COMMIT_PROFILE:
        return ReusedBaseline(unavailable_reason="profile does not reuse baselines")

    stored = load_latest_compatible(result_directory, current_manifest)
    if stored is None:
        return ReusedBaseline(unavailable_reason="no digest-compatible stored result")

    manifest = stored.get("manifest", {})
    age_days = _result_age_days(manifest, now)
    if age_days is None:
        return ReusedBaseline(unavailable_reason="stored result has no usable timestamp")
    if age_days > MAX_BASELINE_AGE_DAYS:
        return ReusedBaseline(
            unavailable_reason=(
                f"stored baseline is {age_days:.1f} days old "
                f"(maximum {MAX_BASELINE_AGE_DAYS})"
            )
        )

    scores = _baseline_scores(stored)
    if not scores:
        return ReusedBaseline(unavailable_reason="stored result has no candidate A samples")

    return ReusedBaseline(
        scores=scores,
        provenance={
            "artifact_digest": manifest.get("artifact_digest"),
            "created_at": manifest.get("created_at"),
            "age_days": round(age_days, 2),
            "max_age_days": MAX_BASELINE_AGE_DAYS,
            "commit": manifest.get("repository", {}).get("commit"),
            "sample_count": len(scores),
        },
    )


def _result_age_days(manifest: dict[str, Any], now: datetime | None) -> float | None:
    """Return the stored result's age in days, or None if it cannot be read."""
    created_at = manifest.get("created_at")
    if not isinstance(created_at, str):
        return None
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    reference = now or datetime.now(tz=UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return max(0.0, (reference - created).total_seconds() / 86_400)


def _baseline_scores(stored: dict[str, Any]) -> list[Any]:
    """Rebuild candidate A scores from a stored result, marked as reused."""
    from .scoring import CaseScore

    allowed_fields = set(CaseScore.__dataclass_fields__)
    scores = []
    for raw_score in stored.get("scores", []):
        if not isinstance(raw_score, dict) or raw_score.get("candidate") != "A":
            continue
        values = {key: value for key, value in raw_score.items() if key in allowed_fields}
        values["sample_source"] = "reused"
        try:
            scores.append(CaseScore(**values))
        except TypeError:
            return []
    return scores


def describe_profile(profile: str | None, baseline: ReusedBaseline) -> list[str]:
    """Return the lines that state what this run's evidence is worth."""
    if profile is None:
        return []
    if profile == RELEASE_PROFILE:
        return [
            "Profile: release — both candidates measured live, no reused baseline.",
        ]

    lines = ["Profile: commit — routine signal, NOT release evidence."]
    if not baseline.available:
        lines.append(
            f"  Candidate A baseline unavailable: {baseline.unavailable_reason}. "
            "Gates against A will not be reported."
        )
        return lines

    provenance = baseline.provenance
    lines.append(
        f"  Candidate A reused from digest {str(provenance['artifact_digest'])[:12]} "
        f"at commit {str(provenance['commit'])[:12]}, "
        f"age {provenance['age_days']:.1f}d of {provenance['max_age_days']}d, "
        f"{provenance['sample_count']} samples."
    )
    lines.append("  Comparison is PROVISIONAL: candidate A was not re-measured.")
    return lines
