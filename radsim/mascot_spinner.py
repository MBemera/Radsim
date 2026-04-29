"""Mascot spinner for RadSim — a small bobbing/blinking bot rendered as
a Rich spinner. Replaces the default 'dots' spinner used in ui.py.
"""

from rich.spinner import SPINNERS

MASCOT_NAME = "mascot"

# Bobbing bot with a blink and a lightning trail. Eyes ^_^ -> -_- on frame 2.
MASCOT_FRAMES = [
    "(^_^)>   ",
    "(-_-)>   ",
    "(^_^)>~  ",
    "(^_^)>~~ ",
]

MASCOT_INTERVAL_MS = 120

# Static fallback for terminals that disable animation. Same width as frames
# so the surrounding layout doesn't shift.
MASCOT_STATIC = "(^_^)>   "


def register_mascot_spinner():
    """Register the mascot spinner with Rich. Idempotent."""
    SPINNERS[MASCOT_NAME] = {
        "interval": MASCOT_INTERVAL_MS,
        "frames": MASCOT_FRAMES,
    }
