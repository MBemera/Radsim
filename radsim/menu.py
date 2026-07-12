"""Interactive menu utilities for RadSim commands.

Provides numbered menu display and safe input handling so that
every command can be cleanly exited with 'q' or Ctrl+C.
"""


def _flush_stdin():
    """Flush any buffered stdin characters to prevent stale input.

    Reads at the file-descriptor level so nothing is left behind in
    Python-level buffers where input() could never see it.
    """
    import os
    import select
    import sys

    try:
        fd = sys.stdin.fileno()
        while select.select([fd], [], [], 0)[0]:
            if not os.read(fd, 4096):
                break
    except Exception:
        pass


def safe_input(prompt="  Select: "):
    """Prompt for user input with clean cancel handling.

    Pauses the Escape listener first — menus can appear while the agent
    is processing (e.g. the sub-agent model picker), and the listener
    would otherwise consume the user's keystrokes and lock the prompt.
    Then flushes stdin to discard stale keystrokes from streaming
    output or background job notifications.

    Args:
        prompt: The input prompt string

    Returns:
        str: User's input (stripped), or None if cancelled (Ctrl+C / EOF / 'q')
    """
    from .escape_listener import pause_escape_listener, resume_escape_listener

    pause_escape_listener()
    try:
        _flush_stdin()
        value = input(prompt).strip()
        if value.lower() in ("q", "quit", "exit", "back"):
            return None
        return value
    except (KeyboardInterrupt, EOFError):
        print()
        return None
    finally:
        resume_escape_listener()


def interactive_menu(title, options, prompt="  Select: ", max_retries=3):
    """Display a numbered menu and return the user's choice.

    Retries on invalid input (up to max_retries) before giving up.

    Args:
        title: Menu title (displayed in header)
        options: List of (key, label) tuples. Key is returned on selection.
        prompt: Input prompt string
        max_retries: Number of retries on invalid input before returning None

    Returns:
        str: The key of the selected option, or None if cancelled.

    Example:
        choice = interactive_menu("COMPLEXITY", [
            ("overview", "Score overview"),
            ("budget", "Set budget"),
            ("report", "Full report"),
        ])
    """
    print()
    print(f"  ═══ {title} ═══")
    print()

    for i, (_, label) in enumerate(options, 1):
        print(f"  [{i}] {label}")

    print("  [q] Back")
    print()

    for attempt in range(max_retries):
        selection = safe_input(prompt)
        if selection is None:
            return None

        # Accept number
        try:
            index = int(selection) - 1
            if 0 <= index < len(options):
                return options[index][0]
        except ValueError:
            pass

        # Accept key name directly
        for key, _ in options:
            if selection.lower() == key.lower():
                return key

        remaining = max_retries - attempt - 1
        if remaining > 0:
            print(f"  Invalid choice: {selection} — enter 1-{len(options)} or q to cancel")
        else:
            print(f"  Invalid choice: {selection}")

    return None


def toggle_menu(title, items, footer_lines=()):
    """Display an on/off switch list and let the user toggle entries.

    With a real terminal: up/down arrows move, left/right or space toggles,
    Enter saves, q or Esc cancels. Without one (pipes, Windows consoles
    lacking termios): falls back to a numbered toggle loop.

    Args:
        title: Menu title.
        items: List of {"key", "label", "value"} dicts (value is bool).
        footer_lines: Extra lines shown under the switch list.

    Returns:
        dict of key -> bool with the final states, or None if cancelled.
    """
    states = {item["key"]: bool(item["value"]) for item in items}
    order = [(item["key"], item["label"]) for item in items]

    if not _stdin_supports_raw_keys():
        return _toggle_menu_numbered(title, order, states, footer_lines)
    return _toggle_menu_arrows(title, order, states, footer_lines)


def _stdin_supports_raw_keys():
    """True when stdin is an interactive terminal with termios available."""
    import sys

    try:
        import termios  # noqa: F401
        import tty  # noqa: F401
    except ImportError:
        return False
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def _render_toggle_lines(title, order, states, cursor, footer_lines):
    """Build the display lines for the toggle menu."""
    lines = ["", f"  ═══ {title} ═══", ""]
    for index, (key, label) in enumerate(order):
        marker = ">" if index == cursor else " "
        state = "ON " if states[key] else "OFF"
        lines.append(f"  {marker} [{state}] {label}")
    lines.append("")
    lines.append("  ↑/↓ move   ←/→/space toggle   Enter save   q cancel")
    for footer_line in footer_lines:
        lines.append(f"  {footer_line}")
    lines.append("")
    return lines


def _toggle_menu_arrows(title, order, states, footer_lines):
    """Arrow-key driven toggle loop; redraws in place after each key."""
    import sys

    from .escape_listener import pause_escape_listener, resume_escape_listener

    pause_escape_listener()
    try:
        _flush_stdin()
        cursor = 0
        lines = _render_toggle_lines(title, order, states, cursor, footer_lines)
        print("\n".join(lines))

        while True:
            key = _read_menu_key(sys.stdin.fileno())
            if key == "up":
                cursor = (cursor - 1) % len(order)
            elif key == "down":
                cursor = (cursor + 1) % len(order)
            elif key in ("left", "right", "space"):
                item_key = order[cursor][0]
                states[item_key] = not states[item_key]
            elif key == "enter":
                return states
            elif key in ("cancel", "eof"):
                return None

            sys.stdout.write(f"\033[{len(lines)}A")
            lines = _render_toggle_lines(title, order, states, cursor, footer_lines)
            print("\n".join(f"\033[2K{line}" for line in lines))
    except KeyboardInterrupt:
        print()
        return None
    finally:
        resume_escape_listener()


def _read_menu_key(fd):
    """Read one keypress in cbreak mode and name it.

    Returns one of: "up", "down", "left", "right", "space", "enter",
    "cancel", "eof", or "" for keys the menu ignores.
    """
    import os
    import select
    import termios
    import tty

    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        first = os.read(fd, 1)
        if not first:
            return "eof"
        if first == b"\x1b":
            if not select.select([fd], [], [], 0.05)[0]:
                return "cancel"  # bare Escape
            sequence = os.read(fd, 2)
            arrows = {b"[A": "up", b"[B": "down", b"[C": "right", b"[D": "left"}
            return arrows.get(sequence, "")
        if first in (b"\r", b"\n"):
            return "enter"
        if first == b" ":
            return "space"
        if first in (b"q", b"Q", b"\x03"):
            return "cancel"
        return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _toggle_menu_numbered(title, order, states, footer_lines, input_fn=None):
    """Numbered fallback: type an entry number to flip it, Enter to save."""
    read_input = input_fn or safe_input

    while True:
        print()
        print(f"  ═══ {title} ═══")
        print()
        for index, (key, label) in enumerate(order, 1):
            state = "ON " if states[key] else "OFF"
            print(f"  [{index}] [{state}] {label}")
        print()
        print("  Type a number to toggle, Enter to save, q to cancel")
        for footer_line in footer_lines:
            print(f"  {footer_line}")

        selection = read_input("  Toggle: ")
        if selection is None:
            return None
        if selection == "":
            return states

        try:
            index = int(selection) - 1
        except ValueError:
            print(f"  Invalid choice: {selection}")
            continue
        if not 0 <= index < len(order):
            print(f"  Invalid choice: {selection}")
            continue
        item_key = order[index][0]
        states[item_key] = not states[item_key]


def interactive_menu_loop(title, options, handler, prompt="  Select: "):
    """Display a menu in a loop until the user quits.

    Like interactive_menu() but re-displays after each action.

    Args:
        title: Menu title
        options: List of (key, label) tuples
        handler: Callable that receives the selected key. Return False to exit loop.
        prompt: Input prompt string
    """
    while True:
        choice = interactive_menu(title, options, prompt)
        if choice is None:
            return

        result = handler(choice)
        if result is False:
            return
