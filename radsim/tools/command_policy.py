"""Command Policy Engine.

Enforces whitelist/blocklist rules on shell commands based on
the current security level from AgentConfigManager.
"""

import logging

from . import command_analysis
from .constants import ALWAYS_BLOCKED_COMMANDS

logger = logging.getLogger(__name__)

# Patterns checked via substring match (catches variations)
ALWAYS_BLOCKED_PATTERNS = [
    "rm -rf /",
    "mkfs.",
    ":(){ :|:& };:",
    "dd if=/dev/zero of=/dev/",
    "dd if=/dev/random of=/dev/",
    "chmod -R 777 /",
    "> /dev/sda",
    "> /dev/nvme",
]


class CommandPolicy:
    """Enforces command execution policy based on security config.

    Supports two modes:
    - whitelist: Only explicitly allowed commands can run
    - blocklist: All commands allowed except explicitly blocked ones

    Always blocks catastrophic commands regardless of mode.
    """

    def __init__(self, config_manager=None):
        self._config_manager = config_manager

    def _get_config(self):
        """Get the current shell command config."""
        if self._config_manager is None:
            from ..agent_config import get_agent_config_manager
            self._config_manager = get_agent_config_manager()

        return {
            "mode": self._config_manager.get("shell_commands.mode", "blocklist"),
            "whitelist": self._config_manager.get("shell_commands.whitelist", []),
            "blocklist": self._config_manager.get("shell_commands.blocklist", []),
            "custom_destructive": self._config_manager.get("shell_commands.custom_destructive", []),
        }

    def is_command_allowed(self, command: str) -> tuple[bool, str | None]:
        """Check if a command is allowed by current policy.

        Args:
            command: The shell command string to check

        Returns:
            Tuple of (is_allowed, reason).
            reason is None if allowed, explanation string if blocked.
        """
        if not command or not command.strip():
            return False, "Empty command"

        # Always block catastrophic commands regardless of security level
        is_catastrophic, reason = self._check_always_blocked(command)
        if is_catastrophic:
            return False, reason

        config = self._get_config()
        mode = config["mode"]

        if mode == "whitelist":
            return self._check_whitelist(command, config["whitelist"])
        if mode == "blocklist":
            return self._check_blocklist(command, config["blocklist"], config["custom_destructive"])
        return False, f"Invalid shell command policy mode: {mode!r}"

    def _check_always_blocked(self, command: str) -> tuple[bool, str | None]:
        """Check against always-blocked commands and patterns.

        Returns:
            Tuple of (is_blocked, reason). is_blocked=True means command is forbidden.
        """
        if command_analysis.is_catastrophic_command(command):
            return True, "BLOCKED: Command is a catastrophic operation"

        normalized_forms = self._normalized_command_forms(command)

        # Exact match
        blocked_commands = {blocked.lower() for blocked in ALWAYS_BLOCKED_COMMANDS}
        if any(form in blocked_commands for form in normalized_forms):
            return True, f"BLOCKED: '{command}' is a catastrophic command blocked at all security levels"

        # Pattern match
        for pattern in ALWAYS_BLOCKED_PATTERNS:
            if any(pattern.lower() in form for form in normalized_forms):
                return True, f"BLOCKED: Command matches catastrophic pattern '{pattern}'"

        return False, None

    def _check_whitelist(self, command: str, whitelist: list) -> tuple[bool, str | None]:
        """In whitelist mode, only explicitly allowed commands can run.

        Matches against command prefix (e.g., "git status" matches "git status --short").
        """
        if not whitelist:
            return False, "Whitelist mode active but no commands are whitelisted. Use /settings to configure."

        try:
            segments = command_analysis.split_into_segments(command_analysis.tokenize(command))
        except ValueError:
            return False, "BLOCKED: Command could not be parsed for whitelist evaluation"

        allowed_entries = self._parse_policy_entries(whitelist)
        if allowed_entries is None:
            return False, "Whitelist configuration is invalid; blocked for safety"

        for segment in segments:
            if not self._segment_matches_whitelist(segment, allowed_entries):
                base_cmd = command_analysis.effective_command_head(segment) or "command"
                return False, self._whitelist_rejection(base_cmd)

        return True, None

    def _segment_matches_whitelist(self, segment, allowed_entries):
        """Return True when one simple command segment matches an allowed prefix."""
        if command_analysis.has_file_output_redirection(segment):
            return False
        if command_analysis.initial_command_names(segment) & command_analysis.WRAPPER_COMMANDS:
            return False

        normalized = [token.lower() for token in segment]
        return any(normalized[: len(allowed)] == allowed for allowed in allowed_entries)

    @staticmethod
    def _whitelist_rejection(base_cmd):
        """Build the standard restrictive-mode rejection message."""
        return (
            f"BLOCKED: '{base_cmd}' is not in the whitelist. "
            "Security level is 'restrictive'. "
            "Use '/settings security_level balanced' to allow more commands."
        )

    def _parse_policy_entries(self, entries):
        """Parse configured entries into normalized single-segment token lists."""
        if not isinstance(entries, list):
            return None
        parsed = []
        for entry in entries:
            if not isinstance(entry, str) or not entry.strip():
                return None
            try:
                segments = command_analysis.split_into_segments(command_analysis.tokenize(entry))
            except ValueError:
                return None
            if len(segments) != 1:
                return None
            parsed.append([token.lower() for token in segments[0]])
        return parsed

    def _check_blocklist(
        self,
        command: str,
        blocklist: list,
        custom_destructive: list,
    ) -> tuple[bool, str | None]:
        """In blocklist mode, commands matching blocked patterns are rejected."""
        if not isinstance(blocklist, list) or not isinstance(custom_destructive, list):
            return False, "Blocklist configuration is invalid; blocked for safety"

        normalized_forms = self._normalized_command_forms(command)

        # Check standard blocklist
        for pattern in blocklist:
            if not isinstance(pattern, str):
                return False, "Blocklist configuration is invalid; blocked for safety"
            if any(pattern.lower() in form for form in normalized_forms):
                return False, f"BLOCKED: Command matches blocked pattern '{pattern}'"

        # Check custom destructive commands
        for pattern in custom_destructive:
            if not isinstance(pattern, str):
                return False, "Blocklist configuration is invalid; blocked for safety"
            if any(pattern.lower() in form for form in normalized_forms):
                return False, f"BLOCKED: Command matches custom destructive pattern '{pattern}'"

        return True, None

    @staticmethod
    def _normalized_command_forms(command):
        """Return raw and shell-token-normalized lowercase command forms."""
        forms = {command.strip().lower()}
        try:
            segments = command_analysis.split_into_segments(command_analysis.tokenize(command))
        except ValueError:
            return forms
        forms.update(" ".join(token.lower() for token in segment) for segment in segments)
        return forms


# Singleton instance
_command_policy: CommandPolicy | None = None


def get_command_policy() -> CommandPolicy:
    """Get or create the global CommandPolicy instance."""
    global _command_policy
    if _command_policy is None:
        _command_policy = CommandPolicy()
    return _command_policy
