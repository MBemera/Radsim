"""Deterministic provider-facing tool-schema serialization."""

from __future__ import annotations

from typing import Any


def canonicalize_tool_schemas(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return validated schemas with stable mapping keys and tool order."""
    canonical_tools = [_canonicalize_mapping(tool) for tool in tools]
    names = [_tool_name(tool) for tool in canonical_tools]
    if len(names) != len(set(names)):
        raise ValueError("Tool schema names must be unique")
    return sorted(canonical_tools, key=_tool_name)


def _canonicalize_mapping(value: Any) -> Any:
    """Recursively sort mapping keys while preserving meaningful list order."""
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Tool schema mapping keys must be strings")
        return {key: _canonicalize_mapping(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonicalize_mapping(item) for item in value]
    return value


def _tool_name(tool: Any) -> str:
    """Return a valid tool name or reject malformed provider input."""
    if not isinstance(tool, dict):
        raise ValueError("Each tool schema must be an object")
    name = tool.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Each tool schema must have a non-empty name")
    return name
