"""Agent Configuration Manager.

Manages user-controllable agent settings stored in ~/.radsim/agent_config.json.
Provides dotted-path access, tool enablement checks, and security level presets.
"""

import copy
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
        # Self-extension permits reviewed local Python extensions and the
        # legacy add_tool path. Off by default and always a deliberate opt-in.
        "self_extension": False,
    },
    "learning": {
        "enabled": True,
        "error_analysis": True,
        "preference_learning": True,
        "reflection": True,
        "tool_optimization": True,
        "few_shot_assembly": True,
    },
    # Subagent settings are deliberately separate from the primary provider
    # and model (~/.radsim/.env). Nothing here feeds back into the primary
    # selection, and /switch, /free and /clear leave these keys untouched.
    # null means the user has not chosen a subagent model yet.
    "subagents": {
        "selected_provider": None,
        "selected_model": None,
        "stream_output": True,
        "max_parallel": 3,
        "max_iterations": 10,
    },
    "self_improvement": {
        "enabled": False,
        "auto_propose": True,
        "auto_propose_threshold": 10,
        "max_pending_proposals": 10,
    },
    "shell_commands": {
        "mode": "blocklist",
        "whitelist": [],
        "blocklist": [],
        "custom_destructive": [],
    },
    "confirmations": {
        "shell_commands": True,
        "file_deletion": True,
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
    "add_tool": "self_extension",
    "remove_tool": "self_extension",
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
            "self_extension": False,
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
        "confirmations": {
            "shell_commands": True,
            "file_deletion": True,
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
            "self_extension": False,
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
        "confirmations": {
            "shell_commands": True,
            "file_deletion": True,
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
            "self_extension": False,
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
        "confirmations": {
            "shell_commands": True,
            "file_deletion": True,
        },
    },
    # "off" disables destructive-command confirmation prompts entirely.
    # Catastrophic commands (rm -rf /, mkfs, raw disk writes) stay blocked:
    # CommandPolicy checks ALWAYS_BLOCKED before any mode logic, so an empty
    # blocklist cannot re-enable them.
    "off": {
        "tools": {
            "shell_access": True,
            "file_deletion": True,
            "web_fetch": True,
            "git_write": True,
            "browser": True,
            "docker": True,
            "database": True,
            "deploy": True,
            "self_extension": False,
        },
        "shell_commands": {
            "mode": "blocklist",
            "whitelist": [],
            "blocklist": [],
            "custom_destructive": [],
        },
        "confirmations": {
            "shell_commands": False,
            "file_deletion": False,
        },
    },
}

# Numeric shortcuts so users can pick a preset with 1-4 instead of typing.
SECURITY_LEVEL_NUMBERS = {
    "1": "restrictive",
    "2": "balanced",
    "3": "permissive",
    "4": "off",
}

# Individual security switches shown in the /settings customize menu.
# Each is a (config key, display label) pair; all persist like any setting.
SECURITY_SWITCHES = (
    ("tools.shell_access", "Shell command tool"),
    ("tools.file_deletion", "File deletion tool"),
    ("tools.web_fetch", "Web fetch tool"),
    ("tools.git_write", "Git write operations"),
    ("tools.browser", "Browser control"),
    ("tools.docker", "Docker tool"),
    ("tools.database", "Database queries"),
    ("tools.deploy", "Deploy tool"),
    ("tools.self_extension", "Self-extension and add_tool"),
    ("confirmations.shell_commands", "Confirm shell commands"),
    ("confirmations.file_deletion", "Confirm file deletion"),
)

SECURITY_OFF_WARNING_LINES = (
    "WARNING: Security level OFF disables confirmation prompts for",
    "destructive shell commands (rm, git push, sudo, file deletion).",
    "Catastrophic commands (rm -rf /, mkfs, raw disk writes) remain",
    "blocked and cannot be enabled at any level.",
)


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
        learning = self._config.get("learning")
        if isinstance(learning, dict):
            learning.pop("active_learning", None)
        self._save()

    def _merge_defaults(self, defaults, current):
        """Recursively merge defaults into current config (keeps existing values).

        The defaults are deep-copied: a shallow copy would share the nested
        dicts of the module-global DEFAULT_CONFIG, so a later set()/security
        preset would mutate DEFAULT_CONFIG in place and make every future
        manager inherit that (e.g. a restrictive whitelist) — an
        order-dependent state leak across the process.
        """
        merged = copy.deepcopy(defaults)
        for key, value in current.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = self._merge_defaults(merged[key], value)
            else:
                merged[key] = copy.deepcopy(value)
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
        if key_path == "tools.self_extension" and value is False:
            try:
                from .extension_loader import _extension_loader

                if _extension_loader is not None:
                    for extension_id in list(_extension_loader.loaded):
                        _extension_loader.unload(extension_id)
            except Exception:
                logger.warning("Could not unload extensions after disabling them", exc_info=True)
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

    def confirmation_enabled(self, kind: str) -> bool:
        """Return True unless the user disabled this confirmation switch.

        Args:
            kind: "shell_commands" or "file_deletion"
        """
        return bool(self.get(f"confirmations.{kind}", True))

    def destructive_confirmation_enabled(self) -> bool:
        """Return True only while every confirmation prompt is still enabled."""
        return self.confirmation_enabled("shell_commands") and self.confirmation_enabled(
            "file_deletion"
        )

    def get_security_switches(self) -> list:
        """Return the customize-menu switches with their current values."""
        return [
            {"key": key, "label": label, "value": bool(self.get(key, True))}
            for key, label in SECURITY_SWITCHES
        ]

    def apply_security_switches(self, states: dict) -> list:
        """Persist toggle states from the customize menu.

        Only known switches are applied; unknown keys are ignored so the
        config cannot be polluted. Any change marks the level "custom".

        Returns:
            List of config keys whose value actually changed.
        """
        changed = []
        for key, _ in SECURITY_SWITCHES:
            if key not in states:
                continue
            new_value = bool(states[key])
            if new_value != bool(self.get(key, True)):
                self.set(key, new_value)
                changed.append(key)
        if changed:
            self.set("security_level", "custom")
        return changed

    def set_security_level(self, level: str) -> dict:
        """Apply a security preset.

        Args:
            level: "restrictive", "balanced", "permissive", "off",
                or the numeric shortcut "1"-"4".

        Returns:
            Dict with success status and applied settings
        """
        level = SECURITY_LEVEL_NUMBERS.get(str(level).strip(), level)
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

        # Apply confirmation settings
        for key, value in preset["confirmations"].items():
            self.set(f"confirmations.{key}", value)

        # Store the level name
        self.set("security_level", level)

        return {
            "success": True,
            "level": level,
            "tools": preset["tools"],
            "shell_mode": preset["shell_commands"]["mode"],
            "confirmations": preset["confirmations"],
        }

    def get_subagent_selection(self) -> tuple:
        """Return the persisted (provider, model) pair for subagents.

        Returns (None, None) when the user has not chosen one, or when the
        stored pair no longer exists in the catalogue. Callers must treat
        both cases as "ask the user" — never as "pick something".
        """
        from .config import is_supported_provider_model

        provider = self.get("subagents.selected_provider")
        model = self.get("subagents.selected_model")
        if not provider or not model:
            return None, None

        supported, reason = is_supported_provider_model(provider, model)
        if not supported:
            logger.warning("Stored subagent selection is no longer valid: %s", reason)
            return None, None

        return provider, model

    def set_subagent_selection(self, provider: str, model: str) -> dict:
        """Persist a validated subagent provider and model pair.

        The pair is validated against the catalogue before it is written, so
        an invalid selection fails closed instead of being stored and
        surfacing later as a confusing runtime error.
        """
        from .config import is_supported_provider_model

        supported, reason = is_supported_provider_model(provider, model)
        if not supported:
            return {"success": False, "error": reason}

        self.set("subagents.selected_provider", provider)
        self.set("subagents.selected_model", model)
        return {"success": True, "provider": provider, "model": model}

    def clear_subagent_selection(self) -> None:
        """Forget the persisted subagent pair so the next delegation asks again."""
        self.set("subagents.selected_provider", None)
        self.set("subagents.selected_model", None)

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
        security_level = config.get("security_level", "balanced")
        lines.append(f"  Security Level: {security_level.upper()}")
        if not self.destructive_confirmation_enabled():
            lines.append("  [!] Some commands run WITHOUT confirmation.")
            lines.append("  [!] Catastrophic commands (rm -rf /, mkfs) stay blocked.")
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

        # Confirmations section
        lines.append("  Confirmations:")
        confirmations = config.get("confirmations", {})
        for key, enabled in sorted(confirmations.items()):
            status = "ON " if enabled else "OFF"
            indicator = "+" if enabled else "-"
            lines.append(f"    [{indicator}] {key:<20} {status}")

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
        lines.append("  Preset: /settings security_level <1-4 | restrictive|balanced|permissive|off>")
        lines.append("  Switches: /settings security (interactive customize menu)")
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
