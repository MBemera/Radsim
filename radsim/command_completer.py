"""Inline dropdown completer for slash commands.

When the user types `/` at the prompt, prompt_toolkit displays every
registered command (primaries and aliases) sorted alphabetically, and
filters as additional characters are typed — similar to the Codex and
Claude Code CLI experiences.
"""

from prompt_toolkit.completion import Completer, Completion


class SlashCommandCompleter(Completer):
    """Completer that surfaces every registered slash command.

    Activates only when the buffer begins with `/`, so free text and
    single-character hotkeys (T, V, S) are unaffected.
    """

    def __init__(self, registry):
        entries = []
        for name, info in registry.commands.items():
            description = info.get("description", "")
            primary = info.get("primary", name)
            meta = description if name == primary else f"{description} → {primary}"
            entries.append((name, meta))
        entries.sort(key=lambda pair: pair[0])
        self._entries = entries

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for name, meta in self._entries:
            if name.startswith(text):
                yield Completion(
                    text=name,
                    start_position=-len(text),
                    display=name,
                    display_meta=meta,
                )


def build_completer(registry):
    """Build a SlashCommandCompleter from a CommandRegistry."""
    return SlashCommandCompleter(registry)
