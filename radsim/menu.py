"""Interactive menu utilities for RadSim commands.

Provides numbered menu display and safe input handling so that
every command can be cleanly exited with 'q' or Ctrl+C.
"""


def safe_input(prompt="  Select: "):
    """Prompt for user input with clean cancel handling.

    Args:
        prompt: The input prompt string

    Returns:
        str: User's input (stripped), or None if cancelled (Ctrl+C / EOF / 'q')
    """
    try:
        value = input(prompt).strip()
        if value.lower() in ("q", "quit", "exit", "back"):
            return None
        return value
    except (KeyboardInterrupt, EOFError):
        print()
        return None


def interactive_menu(title, options, prompt="  Select: "):
    """Display a numbered menu and return the user's choice.

    Args:
        title: Menu title (displayed in header)
        options: List of (key, label) tuples. Key is returned on selection.
        prompt: Input prompt string

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

    print(f"  Invalid choice: {selection}")
    return None


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
