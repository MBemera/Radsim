"""Shared terminal capability and ANSI-color helpers."""

import sys


def supports_color():
    """Check if the current stdout stream supports colors."""
    if not hasattr(sys.stdout, "isatty"):
        return False
    if not sys.stdout.isatty():
        return False
    return True


def colorize_ansi(text, color_name, palette, supports_color_fn=None):
    """Apply an ANSI color from a palette when the terminal supports it."""
    color_supports = supports_color_fn or supports_color
    if not color_supports():
        return text
    return f"{palette.get(color_name, '')}{text}{palette['reset']}"
