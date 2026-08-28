"""Deterministic provider-facing tool-schema serialization."""

from __future__ import annotations

from typing import Any

from .bounded_cache import MISSING, BoundedCache

_schema_cache = BoundedCache(max_entries=32)


def canonicalize_tool_schemas(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return validated schemas with stable mapping keys and tool order.

    Canonicalising all 72 registered schemas costs about 2.3 ms and runs on
    every provider request, so the result is cached against the registry
    version and the selected tool names. Registering, removing, or toggling a
    tool bumps that version; :func:`clear_schema_cache` handles anything the
    version cannot see, such as a reconnected MCP server replacing a schema
    body while keeping its name.
    """
    cache_key = _cache_key(tools)
    if cache_key is not None:
        cached = _schema_cache.get(cache_key)
        if cached is not MISSING:
            # A shallow copy so a caller sorting or appending cannot corrupt
            # the entry every later request reads.
            return list(cached)

    canonical_tools = [_canonicalize_mapping(tool) for tool in tools]
    names = [_tool_name(tool) for tool in canonical_tools]
    if len(names) != len(set(names)):
        raise ValueError("Tool schema names must be unique")
    canonical_tools.sort(key=_tool_name)

    if cache_key is None:
        return canonical_tools

    # Store and return separate lists: the caller must not be able to reach
    # the entry every later request reads.
    _schema_cache.set(cache_key, canonical_tools)
    return list(canonical_tools)


def clear_schema_cache() -> None:
    """Drop cached schemas when a source the registry version cannot see changes."""
    _schema_cache.clear()


def schema_cache_stats() -> dict[str, Any]:
    """Return schema-cache hit rate and size."""
    return _schema_cache.stats()


def _cache_key(tools: list[dict[str, Any]]) -> tuple[Any, ...] | None:
    """Return a cheap key, or None when the input cannot be keyed safely."""
    try:
        from .tools import registry_version

        names = tuple(tool["name"] for tool in tools)
    except (AttributeError, ImportError, KeyError, TypeError):
        return None
    if not all(isinstance(name, str) for name in names):
        return None
    return (registry_version(), names)


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
