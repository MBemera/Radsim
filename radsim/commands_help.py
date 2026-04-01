"""Natural language help detection for slash-command help topics."""

from .output import _resolve_help_topic

_HELP_PATTERNS = [
    ("how do i use ", 0),
    ("how do you use ", 0),
    ("how to use ", 0),
    ("how does ", 0),
    ("what does ", 0),
    ("what is ", 0),
    ("what's ", 0),
    ("help with ", 0),
    ("help me with ", 0),
    ("i need help with ", 0),
    ("tell me about ", 0),
    ("explain ", 0),
    ("how do i ", 0),
    ("how to ", 0),
]

_TRAILING_NOISE = {
    "work",
    "do",
    "works",
    "does",
    "mean",
    "command",
    "mode",
    "feature",
    "function",
    "tool",
    "in",
    "radsim",
    "?",
}


def detect_help_intent(user_input):
    """Detect if user input is a natural language help query."""
    if not user_input:
        return None

    text = user_input.strip().lower()
    if text.startswith("/") or len(text) > 80:
        return None

    for prefix, _ in _HELP_PATTERNS:
        if not text.startswith(prefix):
            continue

        remainder = text[len(prefix) :].strip()
        if not remainder:
            continue

        remainder = remainder.rstrip("?.!")
        words = remainder.split()

        while words and words[-1] in _TRAILING_NOISE:
            words.pop()

        if not words:
            continue

        candidate = words[0].lstrip("/")
        resolved = _resolve_help_topic(candidate)
        if resolved:
            return resolved

        full_candidate = " ".join(words).lstrip("/")
        resolved = _resolve_help_topic(full_candidate)
        if resolved:
            return resolved

    return None
