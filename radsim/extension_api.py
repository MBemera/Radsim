"""Stable v1 facade over RadSim's existing tool, command, and hook registries."""

from __future__ import annotations

import copy
import json
import re
import threading
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

from .hooks import HookContext, HookType, get_hooks_manager
from .persistence import atomic_write_json
from .tools import (
    EXTENSION_PERMISSION_TIERS,
    can_register_extension_tool,
    register_extension_tool,
    set_extension_tool_active,
    unregister_extension_tools,
    validate_extension_tool_definition,
)

API_VERSION = 1
MAX_STORAGE_KEYS = 100
MAX_STORAGE_BYTES = 64 * 1024
OBSERVE_EVENTS = {
    "post_tool": HookType.POST_TOOL,
    "post_api": HookType.POST_API,
    "post_message": HookType.POST_MESSAGE,
    "on_error": HookType.ON_ERROR,
}
_COMMAND_PATTERN = re.compile(r"^/[a-z][a-z0-9-]{1,63}$")
_EXTENSION_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,62}[a-z0-9]$")


class ExtensionStorage(MutableMapping):
    """Bounded JSON storage namespaced to one validated extension ID."""

    def __init__(self, extension_id: str, root: Path | None = None):
        self.extension_id = extension_id
        self.root = Path(root or Path.home() / ".radsim" / "extension_storage")
        self.path = self.root / f"{extension_id}.json"
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, Any]) -> None:
        if len(data) > MAX_STORAGE_KEYS:
            raise ValueError(f"Extension storage is limited to {MAX_STORAGE_KEYS} keys")
        encoded = json.dumps(data, sort_keys=True, default=str)
        if len(encoded.encode("utf-8")) > MAX_STORAGE_BYTES:
            raise ValueError(f"Extension storage is limited to {MAX_STORAGE_BYTES} bytes")
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, data, secure=True, default=str)

    def __getitem__(self, key):
        with self._lock:
            return self._load()[key]

    def __setitem__(self, key, value):
        if not isinstance(key, str) or not key or len(key) > 80:
            raise ValueError("Extension storage keys must contain 1-80 characters")
        with self._lock:
            data = self._load()
            data[key] = value
            self._save(data)

    def __delitem__(self, key):
        with self._lock:
            data = self._load()
            del data[key]
            self._save(data)

    def __iter__(self):
        with self._lock:
            return iter(dict(self._load()))

    def __len__(self):
        with self._lock:
            return len(self._load())


class ExtensionAPI:
    """Collect and atomically apply registrations owned by one extension."""

    def __init__(
        self,
        extension_id: str,
        permissions,
        command_registry,
        *,
        storage_root: Path | None = None,
    ):
        if not _EXTENSION_ID_PATTERN.fullmatch(str(extension_id)):
            raise ValueError("Invalid extension identity")
        self.extension_id = extension_id
        self.owner = f"extension:{extension_id}"
        self.permissions = frozenset(permissions)
        self.command_registry = command_registry
        self.storage_root = storage_root
        self._tool_specs: list[dict[str, Any]] = []
        self._command_specs: list[dict[str, Any]] = []
        self._hook_specs: list[tuple[HookType, Any]] = []
        self._storage = None
        self._active = False

    def _require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise PermissionError(
                f"Extension '{self.extension_id}' did not declare {permission}"
            )

    def register_tool(self, definition, execute, permission_tier):
        """Stage one tool for the existing tool registry."""
        self._require("tools.register")
        validated = validate_extension_tool_definition(definition)
        if not callable(execute):
            raise ValueError("Tool executor must be callable")
        if permission_tier not in EXTENSION_PERMISSION_TIERS:
            raise ValueError(
                "permission_tier must be read_only, mutation, or generated_code"
            )
        if any(spec["definition"]["name"] == validated["name"] for spec in self._tool_specs):
            raise ValueError(f"Duplicate extension tool: {validated['name']}")
        self._tool_specs.append(
            {
                "definition": validated,
                "execute": execute,
                "permission_tier": permission_tier,
                "active": True,
            }
        )
        return validated["name"]

    def register_command(self, name, handler, description, accepts_args=False):
        """Stage one slash command for the existing command registry."""
        self._require("commands.register")
        if self.command_registry is None:
            raise RuntimeError("Command registration is unavailable in this runtime")
        normalized = str(name).lower()
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        if not _COMMAND_PATTERN.fullmatch(normalized):
            raise ValueError(
                "Command name must use 2-64 lowercase letters, digits, or hyphens"
            )
        if not callable(handler):
            raise ValueError("Command handler must be callable")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("Command description is required")
        if any(spec["name"] == normalized for spec in self._command_specs):
            raise ValueError(f"Duplicate extension command: {normalized}")
        self._command_specs.append(
            {
                "name": normalized,
                "handler": handler,
                "description": description.strip()[:200],
                "accepts_args": bool(accepts_args),
            }
        )
        return normalized

    def on(self, event_name, handler):
        """Stage a non-blocking lifecycle observer."""
        self._require("hooks.observe")
        hook_type = OBSERVE_EVENTS.get(str(event_name))
        if hook_type is None:
            raise ValueError(
                f"Unsupported observe event: {event_name}. "
                f"Valid: {', '.join(sorted(OBSERVE_EVENTS))}"
            )
        if not callable(handler):
            raise ValueError("Hook handler must be callable")
        if any(
            hook_type == registered_type
            and getattr(wrapper, "_extension_handler", None) is handler
            for registered_type, wrapper in self._hook_specs
        ):
            raise ValueError(f"Duplicate extension hook: {event_name}")

        def observe(context: HookContext):
            snapshot = HookContext(
                hook_type=context.hook_type,
                tool_name=context.tool_name,
                tool_input=_isolated_mapping(context.tool_input),
                tool_result=_isolated_mapping(context.tool_result),
                message=context.message,
                error=context.error,
                metadata=_isolated_mapping(context.metadata),
            )
            handler(snapshot)
            return context

        observe._extension_handler = handler
        self._hook_specs.append((hook_type, observe))
        return observe

    def get_extension_storage(self):
        """Return bounded storage that no other extension can address."""
        self._require("storage.read_write")
        if self._storage is None:
            self._storage = ExtensionStorage(self.extension_id, self.storage_root)
        return self._storage

    def set_extension_tool_active(self, name, enabled):
        """Toggle only a tool owned by this API instance."""
        for spec in self._tool_specs:
            if spec["definition"]["name"] == name:
                spec["active"] = bool(enabled)
                if self._active:
                    set_extension_tool_active(self.owner, name, enabled)
                return
        raise ValueError(f"Extension does not own tool: {name}")

    def preflight(self, *, replacing_owner=None):
        """Validate conflicts before changing any live registry."""
        for spec in self._tool_specs:
            name = spec["definition"]["name"]
            allowed, error = can_register_extension_tool(
                name,
                replacing_owner=replacing_owner,
            )
            if not allowed:
                raise ValueError(error)
        if self._command_specs:
            names = [spec["name"] for spec in self._command_specs]
            allowed, error = self.command_registry.can_register(
                names,
                replacing_owner=replacing_owner,
            )
            if not allowed:
                raise ValueError(error)

    def activate(self):
        """Apply staged registrations, rolling back partial activation."""
        if self._active:
            return
        self.preflight()
        self._active = True
        try:
            for spec in self._tool_specs:
                name = register_extension_tool(
                    self.owner,
                    spec["definition"],
                    spec["execute"],
                    spec["permission_tier"],
                )
                if not spec["active"]:
                    set_extension_tool_active(self.owner, name, False)
            for spec in self._command_specs:
                self.command_registry.register(
                    spec["name"],
                    spec["handler"],
                    spec["description"],
                    category="extensions",
                    accepts_args=spec["accepts_args"],
                    owner=self.owner,
                )
            manager = get_hooks_manager()
            for hook_type, hook in self._hook_specs:
                manager.register(hook_type, hook, owner=self.owner)
        except Exception:
            self.deactivate()
            raise

    def deactivate(self):
        """Remove this extension's registrations, never built-ins."""
        if not self._active:
            return
        unregister_extension_tools(self.owner)
        if self.command_registry is not None:
            self.command_registry.unregister_owner(self.owner)
        get_hooks_manager().unregister_owner(self.owner)
        self._active = False

    def registrations(self):
        """Enumerate identity-attached registrations for status and tests."""
        return {
            "owner": self.owner,
            "tools": [spec["definition"]["name"] for spec in self._tool_specs],
            "commands": [spec["name"] for spec in self._command_specs],
            "hooks": [hook_type.value for hook_type, _hook in self._hook_specs],
            "active": self._active,
        }


def _isolated_mapping(value: Any) -> dict[str, Any]:
    """Copy observer data without letting nested edits reach live context."""
    if not isinstance(value, dict):
        return {}
    try:
        return copy.deepcopy(value)
    except Exception:
        return json.loads(json.dumps(value, default=str))
