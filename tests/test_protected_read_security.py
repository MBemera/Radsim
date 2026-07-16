"""Security regression tests for protected/secret file reads (R-02).

read_file / read_document / read_image / read_many_files are read-only and
run without confirmation, and validate_path only checked project
containment — so a repository .env (or SSH key, cloud credential, ...) could
be read and its contents shipped to the model provider silently. These tests
prove secret paths are detected on the canonical path and that a read of one
is gated behind an explicit, non-bypassable confirmation.
"""

from unittest.mock import patch

import pytest

from radsim.agent_policy import AgentPolicyMixin
from radsim.tools.validation import (
    clear_path_validation_cache,
    is_secret_read_path,
)


class TestSecretReadDetection:
    @pytest.mark.parametrize(
        "path",
        [
            ".env",
            ".env.local",
            ".env.production",
            "config/.env",
            "prod.env",
            "id_rsa",
            "id_ed25519",
            "deploy_key.pem",
            "server.key",
            "cert.pfx",
            ".npmrc",
            ".pypirc",
            ".netrc",
            ".git-credentials",
            "credentials",
            "service-account-prod.json",
            "home/user/.ssh/id_rsa",
            "root/.aws/credentials",
            "some/.gnupg/secring.gpg",
        ],
    )
    def test_flags_secret_paths(self, path):
        is_secret, reason = is_secret_read_path(path)
        assert is_secret is True, path
        assert reason

    @pytest.mark.parametrize(
        "path",
        [
            "main.py",
            "tokenizer.py",          # substring "token" must NOT trip it
            "password_reset.py",     # substring "password" must NOT trip it
            "src/secrets_manager.go",
            "README.md",
            "environment.yml",
            "keyboard.js",           # substring "key" must NOT trip it
        ],
    )
    def test_does_not_flag_ordinary_source(self, path):
        is_secret, _ = is_secret_read_path(path)
        assert is_secret is False, path

    def test_symlink_to_env_is_flagged_on_resolved_path(self, tmp_path):
        secret = tmp_path / ".env"
        secret.write_text("ANTHROPIC_API_KEY=sk-should-not-leak")
        link = tmp_path / "notes.txt"
        try:
            link.symlink_to(secret)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable on this platform")

        resolved = str(link.resolve())
        # The display name looks innocent; the resolved target is a secret.
        is_secret, _ = is_secret_read_path("notes.txt", resolved)
        assert is_secret is True


class _Policy(AgentPolicyMixin):
    """Minimal concrete mixin host for the two read-gate methods."""


class TestProtectedReadGate:
    def test_targets_detected_for_read_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        clear_path_validation_cache()
        (tmp_path / ".env").write_text("SECRET=1")

        targets = _Policy()._protected_read_targets("read_file", {"file_path": ".env"})
        assert targets, "protected .env read should be flagged"

    def test_ordinary_file_not_gated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        clear_path_validation_cache()
        (tmp_path / "main.py").write_text("print(1)")

        targets = _Policy()._protected_read_targets("read_file", {"file_path": "main.py"})
        assert targets == []

    def test_many_files_flags_only_secret(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        clear_path_validation_cache()
        (tmp_path / "a.py").write_text("x")
        (tmp_path / ".env").write_text("SECRET=1")

        targets = _Policy()._protected_read_targets(
            "read_many_files", {"file_paths": ["a.py", ".env"]}
        )
        assert len(targets) == 1

    def test_rejection_blocks_read(self):
        with patch("radsim.agent_policy.confirm_action", return_value=False) as confirm, \
             patch("radsim.agent_policy.execute_tool") as executed:
            result = _Policy()._confirm_protected_read(
                "read_file", {"file_path": ".env"}, [("/proj/.env", "secret file (.env)")]
            )
        assert result["success"] is False
        assert "rejected" in result["error"].lower()
        confirm.assert_called_once()
        executed.assert_not_called()

    def test_approval_allows_read(self):
        with patch("radsim.agent_policy.confirm_action", return_value=True), \
             patch("radsim.agent_policy.execute_tool", return_value={"success": True, "content": "x"}) as executed:
            result = _Policy()._confirm_protected_read(
                "read_file", {"file_path": ".env"}, [("/proj/.env", "secret file (.env)")]
            )
        assert result["success"] is True
        executed.assert_called_once()

    def test_auto_confirm_cannot_bypass(self):
        """config=None means auto-confirm never silently approves the read."""
        captured = {}

        def fake_confirm(message, config=None):
            captured["config"] = config
            return False

        with patch("radsim.agent_policy.confirm_action", side_effect=fake_confirm), \
             patch("radsim.agent_policy.execute_tool"):
            _Policy()._confirm_protected_read(
                "read_file", {"file_path": ".env"}, [("/proj/.env", "secret file (.env)")]
            )
        assert captured["config"] is None
