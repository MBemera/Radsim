"""Slash command registry and handlers."""

import re

from .commands_core import CoreCommandHandlersMixin
from .commands_help import detect_help_intent  # noqa: F401 - re-exported for compatibility
from .commands_learning import LearningCommandHandlersMixin
from .commands_metadata import COMMAND_HINTS, DEFAULT_COMMAND_SPECS, TELEGRAM_SAFE_COMMANDS
from .commands_workflow import WorkflowCommandHandlersMixin
from .output import print_error


class CommandRegistry(
    CoreCommandHandlersMixin,
    LearningCommandHandlersMixin,
    WorkflowCommandHandlersMixin,
):
    """Registry for slash commands."""

    TELEGRAM_SAFE_COMMANDS = TELEGRAM_SAFE_COMMANDS

    def __init__(self):
        self.commands = {}
        self._register_defaults()

    def register(
        self,
        names,
        handler,
        description="",
        category="custom",
        accepts_args=False,
        *,
        owner="custom",
    ):
        """Register commands in the existing registry with ownership metadata."""
        if isinstance(names, str):
            names = [names]

        normalized_names = []
        for name in names:
            name = name.lower()
            if not name.startswith("/"):
                name = "/" + name
            normalized_names.append(name)

        conflicts = [name for name in normalized_names if name in self.commands]
        if conflicts:
            raise ValueError(f"Command already registered: {', '.join(sorted(conflicts))}")

        primary_name = normalized_names[0]
        for name in normalized_names:
            self.commands[name] = {
                "handler": handler,
                "description": description,
                "primary": primary_name,
                "category": category,
                "accepts_args": accepts_args,
                "owner": owner,
            }
        return tuple(normalized_names)

    def can_register(self, names, *, replacing_owner=None):
        """Return a deterministic conflict message, ignoring one reload owner."""
        if isinstance(names, str):
            names = [names]
        conflicts = []
        for name in names:
            normalized = name.lower()
            if not normalized.startswith("/"):
                normalized = "/" + normalized
            current = self.commands.get(normalized)
            if current and current.get("owner") != replacing_owner:
                conflicts.append(normalized)
        if conflicts:
            return False, f"Command already registered: {', '.join(sorted(conflicts))}"
        return True, None

    def unregister_owner(self, owner):
        """Remove only commands registered by an extension owner."""
        if not owner or owner == "builtin":
            return []
        removed = [
            name
            for name, info in self.commands.items()
            if info.get("owner") == owner
        ]
        for name in removed:
            del self.commands[name]
        return sorted(removed)

    def is_telegram_safe(self, command):
        """Check if a command is safe to run from Telegram."""
        return command in self.TELEGRAM_SAFE_COMMANDS

    def get_telegram_command_list(self):
        """Get list of commands safe for Telegram with descriptions."""
        safe_commands = []
        for command, description in self.TELEGRAM_SAFE_COMMANDS.items():
            safe_commands.append(
                {
                    "command": command.lstrip("/"),
                    "description": description[:64],
                }
            )
        return sorted(safe_commands, key=lambda item: item["command"])

    def handle_input(self, user_input, agent):
        """Check if input is a command and execute it."""
        parts = user_input.strip().split()
        if not parts:
            return False

        command_name = parts[0].lower()

        if command_name in self.commands:
            return self._execute(command_name, agent, parts[1:])

        background_match = re.match(r"^/(bg|background)(\d+)$", command_name)
        if background_match:
            return self._execute("/background", agent, [background_match.group(2)] + parts[1:])

        if command_name in ["exit", "quit"]:
            return self._execute("/exit", agent, parts[1:])

        return False

    def _execute(self, command_name, agent, args):
        """Execute the command handler."""
        command_info = self.commands[command_name]
        handler = command_info["handler"]
        try:
            if command_info["accepts_args"]:
                result = handler(agent, args)
            else:
                result = handler(agent)
            return result is not False
        except (KeyboardInterrupt, EOFError):
            print()
            print("  Cancelled.")
            return True
        except Exception as error:
            print_error(f"Command error: {error}")
            return True

    def _register_defaults(self):
        """Register default RadSim commands."""
        for spec in DEFAULT_COMMAND_SPECS:
            self.register(
                spec["names"],
                getattr(self, spec["handler_name"]),
                spec["description"],
                category=spec["category"],
                accepts_args=spec["accepts_args"],
                owner="builtin",
            )

    def get_relevant_commands(self, context):
        """Get commands relevant to a context for hints."""
        return COMMAND_HINTS.get(context, [])
