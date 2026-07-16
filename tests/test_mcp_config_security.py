"""Security regression tests for MCP config permissions (R-05).

~/.radsim/mcp.json can hold plaintext env secrets, but save_config wrote it
with a plain write_text and left it mode 0644 under a normal umask, readable
by other local users. These tests prove the file is written 0600 via an
atomic replace, the directory is 0700, and a pre-existing permissive file is
repaired on load.
"""

import os
import stat

import pytest

from radsim import mcp_client
from radsim.mcp_client import MCPClientManager, MCPServerConfig

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics")


@pytest.fixture
def mcp_path(tmp_path, monkeypatch):
    path = tmp_path / ".radsim" / "mcp.json"
    monkeypatch.setattr(mcp_client, "MCP_CONFIG_PATH", path)
    return path


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


class TestSaveConfigPermissions:
    @posix_only
    def test_saved_file_is_0600(self, mcp_path):
        manager = MCPClientManager()
        manager.add_server_config(
            MCPServerConfig(name="secret-srv", command="run", env={"TOKEN": "s3cr3t"})
        )
        assert mcp_path.exists()
        assert _mode(mcp_path) == 0o600

    @posix_only
    def test_directory_is_0700(self, mcp_path):
        manager = MCPClientManager()
        manager.add_server_config(MCPServerConfig(name="srv", command="run"))
        assert _mode(mcp_path.parent) == 0o700

    def test_no_temp_files_left_behind(self, mcp_path):
        manager = MCPClientManager()
        manager.add_server_config(MCPServerConfig(name="srv", command="run"))
        leftovers = list(mcp_path.parent.glob(".mcp-*"))
        assert leftovers == []

    def test_content_round_trips(self, mcp_path):
        manager = MCPClientManager()
        manager.add_server_config(
            MCPServerConfig(name="srv", command="run", env={"TOKEN": "s3cr3t"})
        )
        reloaded = MCPClientManager()
        reloaded.load_config()
        configs = reloaded.get_server_configs()
        assert "srv" in configs
        assert configs["srv"].env == {"TOKEN": "s3cr3t"}


class TestLoadRepairsPermissions:
    @posix_only
    def test_permissive_existing_file_is_tightened(self, mcp_path):
        mcp_path.parent.mkdir(parents=True, exist_ok=True)
        mcp_path.write_text('{"mcpServers": {}}')
        os.chmod(mcp_path, 0o644)
        assert _mode(mcp_path) == 0o644

        MCPClientManager().load_config()
        assert _mode(mcp_path) == 0o600
