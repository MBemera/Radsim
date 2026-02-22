"""Keybinding support for RadSim.

Handles special key detection for mode toggles and actions.

Hotkeys are single characters typed at the prompt and submitted with Enter.
This approach is reliable across all platforms (macOS libedit, GNU readline, etc.)
without requiring raw terminal mode or platform-specific key bindings.

Available hotkeys:
    T (Shift+T) — Toggle teach mode
    V (Shift+V) — Toggle verbose mode
    S (Shift+S) — Show all session code (Ctrl+O alternative)
"""


# Special input patterns that act as hotkeys
# Users can type these at the prompt for quick toggles/actions
# Keys are uppercase but matching is case-insensitive
HOTKEY_PATTERNS = {
    "T": "teach",      # T or t = toggle teach mode
    "V": "verbose",    # V or v = toggle verbose mode
}

# Action hotkeys - these trigger commands, not mode toggles
ACTION_HOTKEYS = {
    "S": "show_code",  # S or s = show all session code
}


def check_hotkey(user_input: str) -> str | None:
    """Check if input is a single-character mode hotkey.

    Args:
        user_input: The raw user input (stripped)

    Returns:
        Mode name to toggle, or None if not a hotkey
    """
    if len(user_input) != 1:
        return None
    return HOTKEY_PATTERNS.get(user_input.upper())


def check_action_hotkey(user_input: str) -> str | None:
    """Check if input is a single-character action hotkey.

    Args:
        user_input: The raw user input (stripped)

    Returns:
        Action name to execute, or None if not an action hotkey
    """
    if len(user_input) != 1:
        return None
    return ACTION_HOTKEYS.get(user_input.upper())


def get_hotkey_help() -> str:
    """Get help text for available hotkeys."""
    lines = ["Hotkeys (type at prompt + Enter):"]
    for key, mode in HOTKEY_PATTERNS.items():
        lines.append(f"  {key}  → Toggle {mode} mode")
    for key, action in ACTION_HOTKEYS.items():
        desc = {"show_code": "Show all session code"}.get(action, action)
        lines.append(f"  {key}  → {desc}")
    return "\n".join(lines)
