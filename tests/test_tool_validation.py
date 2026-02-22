"""Tests for radsim/tools/validation.py

One test, one thing. Clear names, obvious assertions.
"""


from radsim.tools.validation import (
    is_protected_path,
    validate_path,
    validate_shell_command,
)

# =============================================================================
# validate_path tests
# =============================================================================


class TestValidatePath:
    """Tests for validate_path function."""

    def test_valid_path_inside_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "src" / "main.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.touch()

        is_safe, path, error = validate_path("src/main.py")

        assert is_safe is True
        assert path is not None
        assert error is None

    def test_empty_path_rejected(self):
        is_safe, path, error = validate_path("")

        assert is_safe is False
        assert "empty" in error.lower()

    def test_none_path_rejected(self):
        is_safe, path, error = validate_path(None)

        assert is_safe is False
        assert "empty" in error.lower()

    def test_path_outside_project_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        is_safe, path, error = validate_path("/etc/passwd")

        assert is_safe is False
        assert "outside project" in error.lower()

    def test_path_traversal_with_dotdot_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        is_safe, path, error = validate_path("../../etc/passwd")

        assert is_safe is False
        assert "outside project" in error.lower()

    def test_allow_outside_flag_permits_external_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        is_safe, path, error = validate_path("/tmp/external.txt", allow_outside=True)

        assert is_safe is True
        assert error is None

    def test_cwd_itself_is_valid(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        is_safe, path, error = validate_path(str(tmp_path))

        assert is_safe is True


# =============================================================================
# is_protected_path tests
# =============================================================================


class TestIsProtectedPath:
    """Tests for is_protected_path function."""

    def test_env_file_is_protected(self):
        is_protected, reason = is_protected_path(".env")

        assert is_protected is True
        assert reason is not None

    def test_env_production_is_protected(self):
        is_protected, reason = is_protected_path(".env.production")

        assert is_protected is True

    def test_credentials_file_is_protected(self):
        is_protected, reason = is_protected_path("config/credentials.json")

        assert is_protected is True

    def test_ssh_key_rsa_is_protected(self):
        is_protected, reason = is_protected_path("~/.ssh/id_rsa")

        assert is_protected is True

    def test_ssh_key_ed25519_is_protected(self):
        is_protected, reason = is_protected_path("keys/id_ed25519")

        assert is_protected is True

    def test_pem_file_is_protected(self):
        is_protected, reason = is_protected_path("certs/server.pem")

        assert is_protected is True

    def test_key_file_is_protected(self):
        is_protected, reason = is_protected_path("ssl/private.key")

        assert is_protected is True

    def test_secrets_directory_is_protected(self):
        is_protected, reason = is_protected_path("secrets/api_keys.txt")

        assert is_protected is True

    def test_password_file_is_protected(self):
        is_protected, reason = is_protected_path("password.txt")

        assert is_protected is True

    def test_token_file_is_protected(self):
        is_protected, reason = is_protected_path("token.json")

        assert is_protected is True

    def test_normal_python_file_not_protected(self):
        is_protected, reason = is_protected_path("src/main.py")

        assert is_protected is False
        assert reason is None

    def test_normal_readme_not_protected(self):
        is_protected, reason = is_protected_path("README.md")

        assert is_protected is False
        assert reason is None

    def test_normal_config_not_protected(self):
        """A generic config.py without sensitive patterns is allowed."""
        is_protected, reason = is_protected_path("src/config.py")

        assert is_protected is False


# =============================================================================
# validate_shell_command tests
# =============================================================================


class TestValidateShellCommand:
    """Tests for validate_shell_command function."""

    def test_safe_echo_command(self):
        is_valid, error = validate_shell_command("echo hello")

        assert is_valid is True
        assert error is None

    def test_safe_ls_command(self):
        is_valid, error = validate_shell_command("ls -la")

        assert is_valid is True

    def test_safe_git_status(self):
        is_valid, error = validate_shell_command("git status")

        assert is_valid is True

    def test_empty_command_rejected(self):
        is_valid, error = validate_shell_command("")

        assert is_valid is False
        assert "empty" in error.lower()

    def test_none_command_rejected(self):
        is_valid, error = validate_shell_command(None)

        assert is_valid is False

    def test_path_traversal_in_argument_rejected(self):
        is_valid, error = validate_shell_command("cat ../../etc/passwd")

        assert is_valid is False
        assert "traversal" in error.lower()

    def test_dotdot_in_flags_blocked(self):
        """Path traversal hidden inside flag arguments must be blocked."""
        is_valid, error = validate_shell_command("cmd --option=../value")

        assert is_valid is False
        assert "traversal" in error.lower()

    def test_invalid_quoting_rejected(self):
        is_valid, error = validate_shell_command("echo 'unterminated")

        assert is_valid is False
        assert "invalid" in error.lower()
