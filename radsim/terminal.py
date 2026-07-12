"""Shared terminal capability and ANSI-color helpers."""

import sys
import unicodedata


def is_unsafe_terminal_character(character):
    """Return whether one character can alter terminal layout or text direction."""
    codepoint = ord(character)
    if codepoint < 32 or 127 <= codepoint <= 159:
        return True
    return unicodedata.category(character) in {"Cf", "Zl", "Zp"}


def _escaped_codepoint(character):
    """Return an explicit ASCII representation of one control codepoint."""
    codepoint = ord(character)
    if codepoint <= 0xFF:
        return f"\\x{codepoint:02x}"
    if codepoint <= 0xFFFF:
        return f"\\u{codepoint:04x}"
    return f"\\U{codepoint:08x}"


def escape_terminal_controls(value, preserve_layout=False):
    """Render untrusted text without allowing terminal control sequences."""
    text = str(value)
    escaped = []
    for character in text:
        if preserve_layout and character == "\n":
            escaped.append(character)
        elif is_unsafe_terminal_character(character):
            escaped.append(_escaped_codepoint(character))
        else:
            escaped.append(character)
    return "".join(escaped)


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
