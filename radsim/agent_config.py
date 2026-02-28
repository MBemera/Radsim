"""Agent Configuration Manager.

Manages user-controllable agent settings stored in ~/.radsim/agent_config.json.
Provides dotted-path access, tool enablement checks, and security level presets.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Default configuration applied on first run
DEFAULT_CONFIG = {
    "version": 1,
    "security_level": "balanced",
    "tools": {
        "shell_access": True,
        "file_deletion": True,
        "web_fetch": True,
        "git_write": True,
        "browser": True,
        "docker": True,
        "database": True,
        "deploy": False,
    },
    "learning": {
        "enabled": True,
        "error_analysis": True,
        "preference_learning": True,
        "reflection": True,
        "tool_optimization": True,
        "few_shot_assembly": True,
        "active_learning": True,
    },
    "subagents": {
        "stream_output": True,
    },
    "self_improvement": {
        "enabled": False,
        "auto_propose": True,
        "max_pending_proposals": 10,
    },
    "shell_commands": {
        "mode": "blocklist",
        "whitelist": [],
        "blocklist": [],
        "custom_destructive": [],
    },
}

# Maps tool names to config keys in "tools" section
TOOL_CONFIG_MAP = {
    "run_shell_command": "shell_access",
    "delete_file": "file_deletion",
    "web_fetch": "web_fetch",
    "git_commit": "git_write",
    "git_checkout": "git_write",
    "git_stash": "git_write",
    "git_add": "git_write",
    "browser_navigate": "browser",
    "browser_click": "browser",
    "browser_screenshot": "browser",
    "browser_read": "browser",
    "browser_type": "browser",
    "browser_close": "browser",
    "run_docker": "docker",
    "database_query": "database",
    "deploy": "deploy",
}

# Security level presets
SECURITY_PRESETS = {
    "restrictive": {
        "tools": {
            "shell_access": True,
            "file_deletion": False,
            "web_fetch": False,
            "git_write": False,
            "browser": False,
            "docker": False,
            "database": False,
            "deploy": False,
        },
        "shell_commands": {
            "mode": "whitelist",
            "whitelist": [
                "ls", "cat", "head", "tail", "wc", "find", "grep",
                "pwd", "echo", "date", "which", "whoami", "uname",
                "git status", "git log", "git diff", "git branch",
                "python --version", "node --version", "npm --version",
                "pip list", "pip show",
            ],
            "blocklist": [],
            "custom_destructive": [],
        },
    },
    "balanced": {
        "tools": {
            "shell_access": True,
            "file_deletion": True,
            "web_fetch": True,
            "git_write": True,
            "browser": True,
            "docker": True,
            "database": True,
            "deploy": False,
        },
        "shell_commands": {
            "mode": "blocklist",
            "whitelist": [],
            "blocklist": [
                "rm -rf /", "rm -rf /*", "mkfs", "dd if=",
                ":(){ :|:& };:", "chmod -R 777 /",
                "wget -O- | sh", "curl | sh",
            ],
            "custom_destructive": [],
        },
    },
    "permissive": {
        "tools": {
            "shell_access": True,
            "file_deletion": True,
            "web_fetch": True,
            "git_write": True,
            "browser": True,
            "docker": True,
            "database": True,
            "deploy": True,
        },
        "shell_commands": {
            "mode": "blocklist",
            "whitelist": [],
            "blocklist": [
                "rm -rf /", "rm -rf /*", "mkfs",
                ":(){ :|:& };:",
            ],
            "custom_destructive": [],
        },
    },
}


class AgentConfigManager:
    """Manages agent configuration with persistent storage.

    Config is stored at ~/.radsim/agent_config.json and loaded on startup.
    Changes are written to disk immediately.
    """

    def __init__(self, config_dir: Path = None):
        self.config_dir = config_dir or Path.home() / ".radsim"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "agent_config.json"
        self._config = {}
        self._load()

    def _load(self):
        """Load config from disk, applying defaults for missing keys."""
        if self.config_file.exists():
            try:
                self._config = json.loads(self.config_file.read_text())
            except (OSError, json.JSONDecodeError):
                logger.warning("Corrupted agent config, resetting to defaults")
                self._config = {}

        # Merge defaults for any missing keys
        self._config = self._merge_defaults(DEFAULT_CONFIG, self._config)
        self._save()

    def _merge_defaults(self, defaults, current):
        """Recursively merge defaults into current config (keeps existing values)."""
        merged = dict(defaults)
        for key, value in current.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = self._merge_defaults(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _save(self):
        """Write current config to disk."""
        try:
            self.config_file.write_text(
                json.dumps(self._config, indent=2) + "\n"
            )
        except OSError as error:
            logger.error("Failed to save agent config: %s", error)

    def get(self, key_path: str, default=None):
        """Get a config value using dotted path notation.

        Args:
            key_path: Dotted path like "tools.shell_access"
            default: Value returned if key doesn't exist

        Returns:
            The config value, or default if not found
        """
        keys = key_path.split(".")
        current = self._config
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    def set(self, key_path: str, value):
        """Set a config value using dotted path notation.

        Args:
            key_path: Dotted path like "tools.shell_access"
            value: The value to set

        Returns:
            True if set successfully, False otherwise
        """
        keys = key_path.split(".")
        current = self._config

        # Navigate to parent
        for key in keys[:-1]:
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]

        # Set the value
        current[keys[-1]] = value
        self._save()
        return True

    def is_tool_enabled(self, tool_name: str) -> bool:
        """Check if a tool is enabled in the current config.

        Args:
            tool_name: The tool name (e.g., "run_shell_command")

        Returns:
            True if tool is enabled (or not in the config map)
        """
        config_key = TOOL_CONFIG_MAP.get(tool_name)
        if config_key is None:
            return True  # Tools not in the map are always allowed

        return self.get(f"tools.{config_key}", True)

    def is_learning_module_enabled(self, module_name: str) -> bool:
        """Check if a learning module is enabled.

        Args:
            module_name: Module name (e.g., "error_analysis", "reflection")

        Returns:
            True if learning is enabled AND the specific module is enabled
        """
        if not self.get("learning.enabled", True):
            return False
        return self.get(f"learning.{module_name}", True)

    def set_security_level(self, level: str) -> dict:
        """Apply a security preset.

        Args:
            level: One of "restrictive", "balanced", "permissive"

        Returns:
            Dict with success status and applied settings
        """
        if level not in SECURITY_PRESETS:
            return {
                "success": False,
                "error": f"Invalid level: {level}",
                "valid_levels": list(SECURITY_PRESETS.keys()),
            }

        preset = SECURITY_PRESETS[level]

        # Apply tool settings
        for key, value in preset["tools"].items():
            self.set(f"tools.{key}", value)

        # Apply shell command settings
        for key, value in preset["shell_commands"].items():
            self.set(f"shell_commands.{key}", value)

        # Store the level name
        self.set("security_level", level)

        return {
            "success": True,
            "level": level,
            "tools": preset["tools"],
            "shell_mode": preset["shell_commands"]["mode"],
        }

    def get_full_config(self) -> dict:
        """Return the full config dictionary (read-only copy)."""
        return dict(self._config)

    def get_config_display(self) -> str:
        """Format config for terminal display."""
        config = self._config
        lines = []
        lines.append("")
        lines.append("  === AGENT SETTINGS ===")
        lines.append("")
        lines.append(f"  Security Level: {config.get('security_level', 'balanced').upper()}")
        lines.append("")

        # Tools section
        lines.append("  Tools:")
        tools = config.get("tools", {})
        for key, enabled in sorted(tools.items()):
            status = "ON " if enabled else "OFF"
            indicator = "+" if enabled else "-"
            lines.append(f"    [{indicator}] {key:<16} {status}")

        lines.append("")

        # Learning section
        lines.append("  Learning:")
        learning = config.get("learning", {})
        for key, enabled in sorted(learning.items()):
            status = "ON " if enabled else "OFF"
            indicator = "+" if enabled else "-"
            lines.append(f"    [{indicator}] {key:<20} {status}")

        lines.append("")

        # Self-improvement section
        lines.append("  Self-Improvement:")
        si = config.get("self_improvement", {})
        for key, value in sorted(si.items()):
            if isinstance(value, bool):
                status = "ON " if value else "OFF"
                indicator = "+" if value else "-"
                lines.append(f"    [{indicator}] {key:<20} {status}")
            else:
                lines.append(f"    {key:<24} {value}")

        lines.append("")

        # Shell commands section
        lines.append("  Shell Commands:")
        shell = config.get("shell_commands", {})
        lines.append(f"    Mode: {shell.get('mode', 'blocklist')}")
        whitelist = shell.get("whitelist", [])
        if whitelist:
            lines.append(f"    Whitelist: {len(whitelist)} commands")
        blocklist = shell.get("blocklist", [])
        if blocklist:
            lines.append(f"    Blocklist: {len(blocklist)} patterns")

        lines.append("")
        lines.append("  Toggle: /settings <path> <value>")
        lines.append("  Preset: /settings security_level <restrictive|balanced|permissive>")
        lines.append("")

        return "\n".join(lines)


# Singleton instance
_agent_config_manager: AgentConfigManager | None = None


def get_agent_config_manager() -> AgentConfigManager:
    """Get or create the global AgentConfigManager instance."""
    global _agent_config_manager
    if _agent_config_manager is None:
        _agent_config_manager = AgentConfigManager()
    return _agent_config_manager
