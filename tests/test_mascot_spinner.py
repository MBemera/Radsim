"""Tests for radsim.mascot_spinner."""

from rich.spinner import SPINNERS

from radsim.mascot_spinner import (
    MASCOT_FRAMES,
    MASCOT_INTERVAL_MS,
    MASCOT_NAME,
    register_mascot_spinner,
)


def test_register_adds_mascot_to_rich():
    register_mascot_spinner()
    assert MASCOT_NAME in SPINNERS
    assert SPINNERS[MASCOT_NAME]["frames"] == MASCOT_FRAMES
    assert SPINNERS[MASCOT_NAME]["interval"] == MASCOT_INTERVAL_MS


def test_register_is_idempotent():
    register_mascot_spinner()
    register_mascot_spinner()
    assert SPINNERS[MASCOT_NAME]["frames"] == MASCOT_FRAMES


def test_frames_have_consistent_width():
    widths = {len(frame) for frame in MASCOT_FRAMES}
    assert len(widths) == 1, f"frame widths drift, layout will jitter: {widths}"


def test_frames_blink_eyes():
    assert any("(-_-)" in frame for frame in MASCOT_FRAMES)
    assert any("(^_^)" in frame for frame in MASCOT_FRAMES)
