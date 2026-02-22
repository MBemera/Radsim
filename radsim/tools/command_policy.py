"""Command Policy Engine.

Enforces whitelist/blocklist rules on shell commands based on
the current security level from AgentConfigManager.
"""

import logging
import shlex

logger = logging.getLogger(__name__)

# Commands blocked at ALL security levels — catastrophic system damage
ALWAYS_BLOCKED_COMMANDS = {
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "rm -rf ~/*",
    "mkfs",
    "mkfs.ext4",
    "mkfs.xfs",
    "dd if=/dev/zero",
    "dd if=/dev/random",
    ":(){ :|:& };:",     # Fork bomb
    "chmod -R 777 /",
    "chown -R",
    "> /dev/sda",
    "mv / /dev/null",
}

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

    def is_command_allowed(self, command: str) -> tuple[bool, str]:
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
        else:
            return self._check_blocklist(command, config["blocklist"], config["custom_destructive"])

    def _check_always_blocked(self, command: str) -> tuple[bool, str]:
        """Check against always-blocked commands and patterns.

        Returns:
            Tuple of (is_blocked, reason). is_blocked=True means command is forbidden.
        """
        normalized = command.strip().lower()

        # Exact match
        if normalized in {cmd.lower() for cmd in ALWAYS_BLOCKED_COMMANDS}:
            return True, f"BLOCKED: '{command}' is a catastrophic command blocked at all security levels"

        # Pattern match
        for pattern in ALWAYS_BLOCKED_PATTERNS:
            if pattern.lower() in normalized:
                return True, f"BLOCKED: Command matches catastrophic pattern '{pattern}'"

        return False, None

    def _check_whitelist(self, command: str, whitelist: list) -> tuple[bool, str]:
        """In whitelist mode, only explicitly allowed commands can run.

        Matches against command prefix (e.g., "git status" matches "git status --short").
        """
        if not whitelist:
            return False, "Whitelist mode active but no commands are whitelisted. Use /settings to configure."

        normalized = command.strip()

        for allowed in whitelist:
            # Prefix match: "ls" matches "ls -la", "git status" matches "git status --short"
            if normalized == allowed or normalized.startswith(allowed + " "):
                return True, None

        # Extract base command for friendlier error
        try:
            parts = shlex.split(command)
            base_cmd = parts[0] if parts else command
        except ValueError:
            base_cmd = command.split()[0] if command.split() else command

        return False, (
            f"BLOCKED: '{base_cmd}' is not in the whitelist. "
            f"Security level is 'restrictive'. "
            f"Use '/settings security_level balanced' to allow more commands."
        )

    def _check_blocklist(self, command: str, blocklist: list, custom_destructive: list) -> tuple[bool, str]:
        """In blocklist mode, commands matching blocked patterns are rejected."""
        normalized = command.strip().lower()

        # Check standard blocklist
        for pattern in blocklist:
            if pattern.lower() in normalized:
                return False, f"BLOCKED: Command matches blocked pattern '{pattern}'"

        # Check custom destructive commands
        for pattern in custom_destructive:
            if pattern.lower() in normalized:
                return False, f"BLOCKED: Command matches custom destructive pattern '{pattern}'"

        return True, None


# Singleton instance
_command_policy: CommandPolicy | None = None


def get_command_policy() -> CommandPolicy:
    """Get or create the global CommandPolicy instance."""
    global _command_policy
    if _command_policy is None:
        _command_policy = CommandPolicy()
    return _command_policy
