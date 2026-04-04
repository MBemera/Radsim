# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""MCP (Model Context Protocol) client integration for RadSim.

Allows RadSim to connect to external MCP servers and use their tools
alongside native RadSim tools. Supports stdio, SSE, and Streamable HTTP
transports.

Install the MCP SDK to enable: pip install radsimcli[mcp]
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Config file location
MCP_CONFIG_PATH = Path.home() / ".radsim" / "mcp.json"


def is_mcp_sdk_installed() -> bool:
    """Check if the MCP SDK is installed without importing it."""
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


def _sanitize_server_name(name: str) -> str:
    """Sanitize server name for use in function names.

    Replaces spaces and special characters with underscores to ensure
    valid function names when used in mcp_<server>_<tool> format.
    """
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str
    transport: str = "stdio"  # "stdio", "sse", or "streamable_http"
    command: str | None = None  # For stdio transport
    args: list = field(default_factory=list)  # For stdio transport
    env: dict = field(default_factory=dict)  # Extra env vars for stdio
    url: str | None = None  # For SSE / Streamable HTTP
    auto_connect: bool = True

    def to_dict(self):
        """Serialize to config dict."""
        result = {"transport": self.transport, "autoConnect": self.auto_connect}
        if self.transport == "stdio":
            result["command"] = self.command
            if self.args:
                result["args"] = self.args
            if self.env:
                result["env"] = self.env
        else:
            result["url"] = self.url
        return result

    @classmethod
    def from_dict(cls, name, data):
        """Deserialize from config dict."""
        return cls(
            name=name,
            transport=data.get("transport", "stdio"),
            command=data.get("command"),
            args=data.get("args", []),
            env=data.get("env", {}),
            url=data.get("url"),
            auto_connect=data.get("autoConnect", True),
        )


@dataclass
class MCPServerConnection:
    """Runtime state for a connected MCP server."""

    config: MCPServerConfig
    session: Any = None  # mcp.ClientSession
    tools: list = field(default_factory=list)  # List of tool definitions
    connected: bool = False
    error: str | None = None

    # Context managers to keep alive for the connection
    _transport_ctx: Any = None
    _session_ctx: Any = None


class MCPClientManager:
    """Manages connections to MCP servers and exposes their tools."""

    def __init__(self):
        self._servers: dict[str, MCPServerConfig] = {}
        self._connections: dict[str, MCPServerConnection] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_loop(self):
        """Get or create an event loop for async operations."""
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop

    def _run_async(self, coro):
        """Run an async coroutine synchronously."""
        loop = self._get_loop()
        return loop.run_until_complete(coro)

    # ── Config I/O ──────────────────────────────────────────────────────

    def load_config(self):
        """Load server configs from ~/.radsim/mcp.json."""
        self._servers.clear()
        if not MCP_CONFIG_PATH.exists():
            return

        try:
            data = json.loads(MCP_CONFIG_PATH.read_text())
            servers = data.get("mcpServers", {})
            for name, server_data in servers.items():
                self._servers[name] = MCPServerConfig.from_dict(name, server_data)
            logger.info("Loaded %d MCP server configs", len(self._servers))
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Failed to parse MCP config: %s", exc)

    def save_config(self):
        """Save current server configs to ~/.radsim/mcp.json."""
        MCP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {"mcpServers": {}}
        for name, config in self._servers.items():
            data["mcpServers"][name] = config.to_dict()
        MCP_CONFIG_PATH.write_text(json.dumps(data, indent=2) + "\n")

    def add_server_config(self, config: MCPServerConfig):
        """Add or update a server configuration and save."""
        self._servers[config.name] = config
        self.save_config()

    def remove_server_config(self, name: str) -> bool:
        """Remove a server configuration. Disconnects first if needed."""
        if name not in self._servers:
            return False
        if name in self._connections:
            self.disconnect(name)
        del self._servers[name]
        self.save_config()
        return True

    def get_server_configs(self) -> dict[str, MCPServerConfig]:
        """Return all server configs."""
        return dict(self._servers)

    # ── Connection Lifecycle ────────────────────────────────────────────

    def connect(self, name: str) -> bool:
        """Connect to a named MCP server. Returns True on success."""
        if name not in self._servers:
            logger.warning("No MCP server config named '%s'", name)
            return False

        config = self._servers[name]

        # Validate transport-specific fields before attempting connection
        if config.transport == "stdio" and not config.command:
            conn = MCPServerConnection(config=config, error="stdio transport requires a command")
            self._connections[name] = conn
            return False
        if config.transport in ("sse", "streamable_http") and not config.url:
            conn = MCPServerConnection(config=config, error=f"{config.transport} transport requires a URL")
            self._connections[name] = conn
            return False

        # Disconnect existing connection first
        if name in self._connections and self._connections[name].connected:
            self.disconnect(name)

        conn = MCPServerConnection(config=config)
        try:
            self._run_async(self._async_connect(conn))
            self._connections[name] = conn
            return conn.connected
        except Exception as exc:
            conn.error = str(exc)
            conn.connected = False
            self._connections[name] = conn
            logger.warning("Failed to connect to MCP server '%s': %s", name, exc)
            return False

    async def _async_connect(self, conn: MCPServerConnection):
        """Async connection logic dispatched by transport type."""
        transport = conn.config.transport
        if transport == "stdio":
            await self._connect_stdio(conn)
        elif transport == "sse":
            await self._connect_sse(conn)
        elif transport == "streamable_http":
            await self._connect_streamable_http(conn)
        else:
            raise ValueError(f"Unknown transport: {transport}")

    async def _connect_stdio(self, conn: MCPServerConnection):
        """Connect via stdio transport."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        config = conn.config
        params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=config.env if config.env else None,
        )

        transport_ctx = stdio_client(params)
        stdio_transport = await transport_ctx.__aenter__()
        conn._transport_ctx = transport_ctx

        read_stream, write_stream = stdio_transport
        session_ctx = ClientSession(read_stream, write_stream)
        session = await session_ctx.__aenter__()
        conn._session_ctx = session_ctx

        await session.initialize()
        conn.session = session
        conn.connected = True

        await self._discover_tools(conn)

    async def _connect_sse(self, conn: MCPServerConnection):
        """Connect via SSE transport."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        transport_ctx = sse_client(conn.config.url)
        sse_transport = await transport_ctx.__aenter__()
        conn._transport_ctx = transport_ctx

        read_stream, write_stream = sse_transport
        session_ctx = ClientSession(read_stream, write_stream)
        session = await session_ctx.__aenter__()
        conn._session_ctx = session_ctx

        await session.initialize()
        conn.session = session
        conn.connected = True

        await self._discover_tools(conn)

    async def _connect_streamable_http(self, conn: MCPServerConnection):
        """Connect via Streamable HTTP transport."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        transport_ctx = streamablehttp_client(conn.config.url)
        http_transport = await transport_ctx.__aenter__()
        conn._transport_ctx = transport_ctx

        read_stream, write_stream = http_transport[0], http_transport[1]
        session_ctx = ClientSession(read_stream, write_stream)
        session = await session_ctx.__aenter__()
        conn._session_ctx = session_ctx

        await session.initialize()
        conn.session = session
        conn.connected = True

        await self._discover_tools(conn)

    async def _discover_tools(self, conn: MCPServerConnection):
        """Query the server for available tools."""
        result = await conn.session.list_tools()
        conn.tools = []
        for tool in result.tools:
            conn.tools.append({
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
            })
        logger.info(
            "Discovered %d tools from MCP server '%s'",
            len(conn.tools),
            conn.config.name,
        )

    def disconnect(self, name: str):
        """Disconnect from a named MCP server."""
        conn = self._connections.get(name)
        if not conn:
            return

        try:
            self._run_async(self._async_disconnect(conn))
        except Exception as exc:
            logger.debug("Error during MCP disconnect for '%s': %s", name, exc)

        conn.connected = False
        conn.session = None
        conn.tools = []

    async def _async_disconnect(self, conn: MCPServerConnection):
        """Async cleanup of session and transport."""
        if conn._session_ctx:
            try:
                await conn._session_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            conn._session_ctx = None

        if conn._transport_ctx:
            try:
                await conn._transport_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            conn._transport_ctx = None

    def connect_auto_servers(self) -> list[str]:
        """Connect to all servers with autoConnect=True. Returns connected names."""
        connected = []
        for name, config in self._servers.items():
            if config.auto_connect:
                if self.connect(name):
                    connected.append(name)
        return connected

    def disconnect_all(self):
        """Disconnect from all servers."""
        for name in list(self._connections.keys()):
            self.disconnect(name)

    # ── Tool Access ─────────────────────────────────────────────────────

    def get_all_tools(self) -> list[dict]:
        """Return tool definitions for all connected servers.

        Tools are namespaced as mcp_<server>_<tool> to avoid conflicts
        with native RadSim tools. Server names are sanitized to ensure
        valid function names (no spaces or special chars).
        """
        tools = []
        for name, conn in self._connections.items():
            if not conn.connected:
                continue
            safe_name = _sanitize_server_name(name)
            for tool in conn.tools:
                namespaced_name = f"mcp_{safe_name}_{tool['name']}"
                tools.append({
                    "type": "function",
                    "function": {
                        "name": namespaced_name,
                        "description": f"[MCP:{name}] {tool['description']}",
                        "parameters": tool.get("input_schema", {}),
                    },
                })
        return tools

    def is_mcp_tool(self, tool_name: str) -> bool:
        """Check if a tool name belongs to an MCP server."""
        return tool_name.startswith("mcp_")

    def _parse_tool_name(self, namespaced_name: str):
        """Parse mcp_<server>_<tool> into (server_name, tool_name).

        Uses sanitized server names for matching, then returns the
        original server name for connection lookup.
        """
        prefix = "mcp_"
        if not namespaced_name.startswith(prefix):
            return None, None

        remainder = namespaced_name[len(prefix):]

        # Build sanitized→original name mapping, match longest first
        name_map = {_sanitize_server_name(k): k for k in self._connections}
        for safe_name in sorted(name_map.keys(), key=len, reverse=True):
            expected_prefix = safe_name + "_"
            if remainder.startswith(expected_prefix):
                tool_name = remainder[len(expected_prefix):]
                return name_map[safe_name], tool_name

        return None, None

    def call_tool(self, namespaced_name: str, arguments: dict) -> dict:
        """Call an MCP tool by its namespaced name.

        Returns:
            dict with "success" and either "result" or "error"
        """
        server_name, tool_name = self._parse_tool_name(namespaced_name)
        if not server_name:
            return {"success": False, "error": f"Cannot parse MCP tool name: {namespaced_name}"}

        conn = self._connections.get(server_name)
        if not conn or not conn.connected:
            return {"success": False, "error": f"MCP server '{server_name}' is not connected"}

        try:
            result = self._run_async(conn.session.call_tool(tool_name, arguments))
            # Extract text content from the result
            content_parts = []
            for item in result.content:
                if hasattr(item, "text"):
                    content_parts.append(item.text)
                elif hasattr(item, "data"):
                    content_parts.append(str(item.data))
                else:
                    content_parts.append(str(item))

            return {
                "success": not result.isError if hasattr(result, "isError") else True,
                "result": "\n".join(content_parts),
            }
        except Exception as exc:
            return {"success": False, "error": f"MCP tool call failed: {exc}"}

    def get_connection_status(self) -> list[dict]:
        """Return status info for all configured servers."""
        statuses = []
        for name, config in self._servers.items():
            conn = self._connections.get(name)
            statuses.append({
                "name": name,
                "transport": config.transport,
                "auto_connect": config.auto_connect,
                "connected": conn.connected if conn else False,
                "tool_count": len(conn.tools) if conn and conn.connected else 0,
                "error": conn.error if conn else None,
            })
        return statuses

    def get_connected_tool_list(self) -> list[dict]:
        """Return flat list of all tools from connected servers."""
        tools = []
        for name, conn in self._connections.items():
            if not conn.connected:
                continue
            safe_name = _sanitize_server_name(name)
            for tool in conn.tools:
                tools.append({
                    "server": name,
                    "name": tool["name"],
                    "namespaced": f"mcp_{safe_name}_{tool['name']}",
                    "description": tool["description"],
                })
        return tools


# ── Singleton ───────────────────────────────────────────────────────────

_manager: MCPClientManager | None = None


def get_mcp_manager() -> MCPClientManager:
    """Return the global MCP client manager singleton."""
    global _manager
    if _manager is None:
        _manager = MCPClientManager()
        _manager.load_config()
    return _manager
