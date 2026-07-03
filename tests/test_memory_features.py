"""Tests for memory subsystem fixes: secret sanitization coverage,
session identity, lazy project-memory creation, and recent-file tracking."""

import os
from pathlib import Path

import pytest

from radsim.memory import (
    ProjectMemory,
    SessionMemory,
    sanitize_data,
)


class TestSecretSanitization:
    """Every current key format must be redacted before hitting disk."""

    @pytest.mark.parametrize(
        "secret",
        [
            "sk-proj-Ab1_Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv",       # OpenAI project key
            "sk-ant-api03-Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv",   # Anthropic
            "sk-or-v1-abcdef1234567890abcdef1234567890",        # OpenRouter
            "AIzaSyA1234567890abcdefghijklmnopqrstuvw",         # Google
            "ghp_" + "A1b2C3d4" * 5,                            # GitHub classic (40 chars)
            "github_pat_" + "A1b2C3d4E5f6G7h8I9j0K1" * 2,       # GitHub fine-grained
            "AKIAIOSFODNN7EXAMPLE",                              # AWS access key ID
            "xoxb-" + "0000000000-0000000000-" + "x" * 24,                  # Slack bot token
            "123456789:AAF6soG9xqLYzXvW8_kJp2QrTuVwXyZabcd",    # Telegram bot token
        ],
    )
    def test_secret_redacted(self, secret):
        result = sanitize_data(f"my key is {secret} ok")
        assert secret not in result
        assert "[REDACTED_SECRET]" in result

    def test_nested_structures_sanitized(self):
        data = {
            "note": "token = abcdef1234567890abcdef",
            "list": ["sk-proj-Ab1_Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv"],
        }
        result = sanitize_data(data)
        assert "[REDACTED_SECRET]" in result["note"]
        assert "[REDACTED_SECRET]" in result["list"][0]

    def test_normal_text_untouched(self):
        text = "Refactor the user-service and add tests for skill-based routing"
        assert sanitize_data(text) == text


class TestSessionIdentity:
    def test_session_id_includes_path_hash(self, tmp_path, monkeypatch):
        """Two projects with the same folder name must not share sessions."""
        import radsim.memory

        monkeypatch.setattr(radsim.memory, "CONFIG_DIR", tmp_path / "config")

        dir_a = tmp_path / "work" / "api"
        dir_b = tmp_path / "personal" / "api"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)

        monkeypatch.setattr(Path, "cwd", staticmethod(lambda: dir_a))
        session_a = SessionMemory()
        monkeypatch.setattr(Path, "cwd", staticmethod(lambda: dir_b))
        session_b = SessionMemory()

        assert session_a.session_id != session_b.session_id
        assert session_a.session_id.startswith("api_")
        assert session_b.session_id.startswith("api_")

    def test_expiry_default_survives_short_break(self, tmp_path, monkeypatch):
        import radsim.memory

        monkeypatch.setattr(radsim.memory, "CONFIG_DIR", tmp_path / "config")

        session = SessionMemory(session_id="test_expiry")
        session.update_activity()
        # A recent session must not be considered expired
        assert session.is_expired() is False


class TestLazyProjectMemory:
    def test_construction_has_no_side_effects(self, tmp_path):
        """Constructing ProjectMemory must not create .radsim anywhere."""
        project = tmp_path / "clean_project"
        project.mkdir()

        ProjectMemory(project_dir=project)

        assert not (project / ".radsim").exists()

    def test_write_creates_scaffolding_with_gitignore(self, tmp_path):
        project = tmp_path / "opted_in"
        project.mkdir()

        memory = ProjectMemory(project_dir=project)
        memory.set_context("focus", "auth module")

        assert (project / ".radsim" / "memory.json").exists()
        gitignore = project / ".radsim" / ".gitignore"
        assert gitignore.exists()
        assert "memory.json" in gitignore.read_text()

    def test_ensure_initialized_creates_agents_md(self, tmp_path):
        project = tmp_path / "explicit_init"
        project.mkdir()

        memory = ProjectMemory(project_dir=project)
        memory.ensure_initialized()

        agents_md = project / ".radsim" / "agents.md"
        assert agents_md.exists()
        assert "RadSim Agents Memory" in agents_md.read_text()


class TestRecentFileTracking:
    def test_read_records_in_opted_in_project(self, tmp_path, monkeypatch):
        """Reads record recent files once a project has .radsim."""
        from radsim.tools.file_ops import read_file

        (tmp_path / ".radsim").mkdir()
        target = tmp_path / "main.py"
        target.write_text("print('hi')\n")

        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = read_file(str(target))
            assert result["success"] is True

            memory = ProjectMemory(project_dir=tmp_path)
            recent_paths = [
                entry["path"] for entry in memory.data.get("recent_files", [])
            ]
            assert any("main.py" in p for p in recent_paths)
        finally:
            os.chdir(original_cwd)

    def test_read_does_not_scatter_radsim_dirs(self, tmp_path, monkeypatch):
        """Reads in a project without .radsim must not create one."""
        from radsim.tools.file_ops import read_file

        target = tmp_path / "notes.txt"
        target.write_text("hello\n")

        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = read_file(str(target))
            assert result["success"] is True
            assert not (tmp_path / ".radsim").exists()
        finally:
            os.chdir(original_cwd)
