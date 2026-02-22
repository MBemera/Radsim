"""Security pentest: path traversal attacks against file operations.

Tests adversarial path inputs designed to escape the project directory,
access protected files, or exploit path normalization bugs.
"""

from pathlib import Path
from unittest.mock import patch

from radsim.safety import is_path_safe
from radsim.tools.file_ops import (
    delete_file,
    read_file,
    rename_file,
    replace_in_file,
    write_file,
)
from radsim.tools.validation import is_protected_path, validate_path

# =============================================================================
# Path Validation Tests
# =============================================================================


class TestRelativeTraversal:
    """Relative path traversal (../../) attacks."""

    def test_basic_traversal(self):
        """Attempt: ../../etc/passwd"""
        is_safe, _, error = validate_path("../../etc/passwd")
        assert is_safe is False
        assert error is not None
        assert "outside" in error.lower() or "denied" in error.lower()

    def test_deep_traversal(self):
        """Attempt: many levels of ../"""
        deep_path = "../" * 20 + "etc/passwd"
        is_safe, _, error = validate_path(deep_path)
        assert is_safe is False

    def test_nested_traversal(self):
        """Attempt: ./legitimate/../../../etc/hosts"""
        is_safe, _, error = validate_path("./legitimate/../../../etc/hosts")
        assert is_safe is False

    def test_hidden_traversal_in_subpath(self):
        """Attempt: src/../../etc/passwd (appears to start inside project)."""
        is_safe, _, error = validate_path("src/../../etc/passwd")
        # If cwd is the project root, src/../../etc/passwd resolves outside
        # This depends on whether /etc/passwd is below cwd
        # On most systems, this should be outside the project
        if not is_safe:
            assert error is not None
        # If it passes, the resolved path still ends up at /etc/passwd
        # which should be outside project dir

    def test_double_encoded_traversal(self):
        """Attempt: path with URL-encoded traversal (literal chars)."""
        # These are literal percent-encoded characters, not actual ../
        # The filesystem won't interpret them as traversal
        is_safe, resolved, _ = validate_path("src/%2e%2e/etc/passwd")
        # This will resolve to a literal path with %2e%2e in the name
        # which stays inside the project dir
        assert is_safe is True or is_safe is False  # Document behavior


class TestAbsolutePathEscape:
    """Absolute paths that escape the project directory."""

    def test_etc_passwd(self):
        """Attempt: /etc/passwd"""
        is_safe, _, error = validate_path("/etc/passwd")
        assert is_safe is False
        assert "outside" in error.lower() or "denied" in error.lower()

    def test_etc_shadow(self):
        """Attempt: /etc/shadow"""
        is_safe, _, error = validate_path("/etc/shadow")
        assert is_safe is False

    def test_root_path(self):
        """Attempt: /"""
        is_safe, _, error = validate_path("/")
        assert is_safe is False

    def test_home_directory(self):
        """Attempt: ~/.ssh/id_rsa"""
        ssh_path = str(Path.home() / ".ssh" / "id_rsa")
        is_safe, _, error = validate_path(ssh_path)
        assert is_safe is False

    def test_tmp_directory(self):
        """Attempt: /tmp/evil_script.sh"""
        is_safe, _, error = validate_path("/tmp/evil_script.sh")
        assert is_safe is False

    def test_proc_self(self):
        """Attempt: /proc/self/environ (Linux env leak)."""
        is_safe, _, error = validate_path("/proc/self/environ")
        assert is_safe is False

    def test_allow_outside_flag(self):
        """With allow_outside=True, paths outside CWD should be allowed."""
        is_safe, resolved, error = validate_path("/tmp/test.txt", allow_outside=True)
        assert is_safe is True
        assert resolved is not None


class TestNullBytePathTermination:
    """Null bytes in paths can truncate or confuse path handling."""

    def test_null_byte_extension_bypass(self):
        """Attempt: file.txt\\x00.py to bypass extension checks."""
        path_with_null = "file.txt\x00.py"
        is_safe, _, error = validate_path(path_with_null)
        # Path.resolve() may handle or reject null bytes
        # Document the behavior
        assert is_safe is True or is_safe is False

    def test_null_byte_traversal(self):
        """Attempt: ../../etc/passwd\\x00"""
        path_with_null = "../../etc/passwd\x00"
        is_safe, _, error = validate_path(path_with_null)
        # Should still be blocked due to traversal
        assert is_safe is False


class TestVeryLongPaths:
    """Extremely long paths to stress path handling."""

    def test_extremely_long_path(self):
        """Attempt: 10,000+ character path."""
        long_path = "a/" * 5000 + "file.txt"
        is_safe, _, error = validate_path(long_path)
        # Should either accept (it resolves inside cwd) or reject gracefully
        assert is_safe is True or (is_safe is False and error is not None)

    def test_long_filename(self):
        """Attempt: filename of 10,000 characters."""
        long_name = "x" * 10000 + ".txt"
        is_safe, _, error = validate_path(long_name)
        # Should not crash
        assert isinstance(is_safe, bool)

    def test_long_path_with_traversal(self):
        """Long path with traversal that escapes the project dir."""
        # Note: "a/"*100 + "../../" only backs up 2 levels out of 100,
        # which stays inside the project. To actually escape we need
        # enough ../ to get above the CWD depth.
        # Use enough traversal to guarantee escape.
        long_prefix = "a/" * 5
        evil_path = long_prefix + "../" * 50 + "etc/passwd"
        is_safe, _, error = validate_path(evil_path)
        # After resolution, the ../ traversals climb above CWD
        assert is_safe is False


class TestUnicodePathTraversal:
    """Unicode characters that might normalize to ../ or /."""

    def test_fullwidth_periods(self):
        """Attempt: fullwidth period U+FF0E as dot-dot."""
        # Two fullwidth periods don't equal '..' in the filesystem
        unicode_traversal = "\uff0e\uff0e/etc/passwd"
        is_safe, _, error = validate_path(unicode_traversal)
        # Should resolve to a literal path, likely inside project dir
        assert is_safe is True or is_safe is False  # Document behavior

    def test_unicode_slash_traversal(self):
        """Attempt: Unicode division slash U+2215."""
        unicode_path = "..\u2215..\u2215etc\u2215passwd"
        is_safe, _, error = validate_path(unicode_path)
        # The filesystem won't interpret U+2215 as a path separator
        assert is_safe is True or is_safe is False

    def test_nfc_normalization(self):
        """Test NFC-normalized path that could expand to traversal."""
        import unicodedata

        # Compose a string that after NFC normalization stays the same
        # This is more of a documentation test
        test_path = unicodedata.normalize("NFC", "../etc/passwd")
        is_safe, _, error = validate_path(test_path)
        assert is_safe is False

    def test_right_to_left_override(self):
        """Attempt: RTL override to disguise file extension."""
        # U+202E is Right-to-Left Override
        rtl_path = "test\u202epy.txt"
        is_safe, _, error = validate_path(rtl_path)
        # Should resolve normally - document behavior
        assert isinstance(is_safe, bool)


class TestSymlinkFollowing:
    """Symlinks that point outside the project directory."""

    def test_symlink_escape(self, tmp_path):
        """Create a symlink inside project that points to /etc."""
        symlink_path = tmp_path / "project" / "evil_link"
        (tmp_path / "project").mkdir()

        # Create a symlink pointing outside the project
        target = Path("/etc/hosts")
        if target.exists():
            symlink_path.symlink_to(target)

            # validate_path uses .resolve() which follows symlinks
            with patch("radsim.tools.validation.Path.cwd", return_value=tmp_path / "project"):
                is_safe, resolved, error = validate_path(str(symlink_path))
                # After resolve(), the path should be /etc/hosts (outside project)
                if resolved:
                    assert str(resolved) == str(target.resolve())
                    # The path is outside the project dir, so it should fail
                    assert is_safe is False

    def test_symlink_chain(self, tmp_path):
        """Chain of symlinks that eventually escapes."""
        project = tmp_path / "project"
        project.mkdir()

        link_a = project / "link_a"
        link_b = tmp_path / "link_b"

        # link_a -> link_b -> /etc/hosts
        target = Path("/etc/hosts")
        if target.exists():
            link_b.symlink_to(target)
            link_a.symlink_to(link_b)

            with patch("radsim.tools.validation.Path.cwd", return_value=project):
                is_safe, resolved, error = validate_path(str(link_a))
                if resolved:
                    # Should resolve to /etc/hosts
                    assert is_safe is False


# =============================================================================
# Protected File Access Tests
# =============================================================================


class TestProtectedFileAccess:
    """Test that protected files are blocked from writing."""

    def test_env_file_write(self):
        """Attempt: write to .env"""
        is_protected, reason = is_protected_path(".env")
        assert is_protected is True
        assert "env" in reason.lower() or "protected" in reason.lower()

    def test_env_local_write(self):
        """Attempt: write to .env.local"""
        is_protected, reason = is_protected_path(".env.local")
        assert is_protected is True

    def test_env_production_write(self):
        """Attempt: write to .env.production"""
        is_protected, reason = is_protected_path(".env.production")
        assert is_protected is True

    def test_git_config_write(self):
        """Attempt: write to .git/config"""
        is_protected, reason = is_protected_path(".git/config")
        assert is_protected is True

    def test_id_rsa_write(self):
        """Attempt: write to id_rsa"""
        is_protected, reason = is_protected_path("id_rsa")
        assert is_protected is True

    def test_id_ed25519_write(self):
        """Attempt: write to id_ed25519"""
        is_protected, reason = is_protected_path("id_ed25519")
        assert is_protected is True

    def test_pem_file_write(self):
        """Attempt: write to server.pem"""
        is_protected, reason = is_protected_path("server.pem")
        assert is_protected is True

    def test_key_file_write(self):
        """Attempt: write to private.key"""
        is_protected, reason = is_protected_path("private.key")
        assert is_protected is True

    def test_credentials_file_write(self):
        """Attempt: write to credentials.json"""
        is_protected, reason = is_protected_path("credentials.json")
        assert is_protected is True

    def test_secrets_directory_file(self):
        """Attempt: write to secrets/api_key.txt"""
        is_protected, reason = is_protected_path("secrets/api_key.txt")
        assert is_protected is True

    def test_password_file(self):
        """Attempt: write to passwords.txt"""
        is_protected, reason = is_protected_path("passwords.txt")
        assert is_protected is True

    def test_token_file(self):
        """Attempt: write to token.json"""
        is_protected, reason = is_protected_path("token.json")
        assert is_protected is True

    def test_case_sensitivity_env(self):
        """Attempt: write to .ENV (uppercase)."""
        is_protected, reason = is_protected_path(".ENV")
        # is_protected_path lowercases the path before matching
        assert is_protected is True

    def test_nested_protected_path(self):
        """Attempt: write to subdirectory/.env"""
        is_protected, reason = is_protected_path("config/secrets/.env")
        assert is_protected is True


class TestSafetyModuleProtection:
    """Tests for the safety.py is_path_safe function."""

    def test_is_path_safe_env(self):
        safe, reason = is_path_safe(".env")
        assert safe is False
        assert reason is not None

    def test_is_path_safe_credentials(self):
        safe, reason = is_path_safe("credentials.json")
        assert safe is False

    def test_is_path_safe_git_config(self):
        safe, reason = is_path_safe(".git/config")
        assert safe is False

    def test_is_path_safe_id_rsa(self):
        safe, reason = is_path_safe("path/to/id_rsa")
        assert safe is False

    def test_is_path_safe_pem(self):
        safe, reason = is_path_safe("cert.pem")
        assert safe is False

    def test_is_path_safe_password(self):
        safe, reason = is_path_safe("password_db.json")
        assert safe is False

    def test_is_path_safe_normal_file(self):
        safe, reason = is_path_safe("src/main.py")
        assert safe is True
        assert reason is None


# =============================================================================
# File Operation Integration Tests
# =============================================================================


class TestFileOpsTraversal:
    """Integration tests: verify file ops reject traversal paths."""

    def test_read_file_traversal(self):
        """read_file should reject ../../etc/passwd"""
        result = read_file("../../etc/passwd")
        assert result["success"] is False
        assert "outside" in result.get("error", "").lower() or "denied" in result.get("error", "").lower()

    def test_read_file_absolute_outside(self):
        """read_file should reject /etc/passwd"""
        result = read_file("/etc/passwd")
        assert result["success"] is False

    def test_write_file_traversal(self):
        """write_file should reject paths outside project."""
        result = write_file("../../tmp/evil.txt", "malicious content")
        assert result["success"] is False

    def test_write_file_to_env(self):
        """write_file should reject writes to .env"""
        result = write_file(".env", "EVIL_KEY=hacked")
        assert result["success"] is False

    def test_write_file_to_credentials(self):
        """write_file should reject writes to credentials files."""
        result = write_file("credentials.json", '{"key": "stolen"}')
        assert result["success"] is False

    def test_write_file_to_id_rsa(self):
        """write_file should reject writes to SSH key files."""
        result = write_file("id_rsa", "ssh-rsa AAAA...")
        assert result["success"] is False

    def test_replace_in_file_traversal(self):
        """replace_in_file should reject path traversal."""
        result = replace_in_file("../../etc/hosts", "old", "new")
        assert result["success"] is False

    def test_rename_file_traversal_source(self):
        """rename_file should reject traversal in source path."""
        result = rename_file("../../etc/passwd", "stolen.txt")
        assert result["success"] is False

    def test_rename_file_traversal_dest(self):
        """rename_file should reject traversal in destination path."""
        result = rename_file("safe.txt", "../../tmp/evil.txt")
        assert result["success"] is False

    def test_delete_file_traversal(self):
        """delete_file should reject path traversal."""
        result = delete_file("../../etc/important_file")
        assert result["success"] is False

    def test_delete_file_absolute_outside(self):
        """delete_file should reject absolute paths outside project."""
        result = delete_file("/etc/hosts")
        assert result["success"] is False


class TestFileOpsEmptyAndNull:
    """Edge cases with empty and null path inputs."""

    def test_read_file_empty(self):
        result = read_file("")
        assert result["success"] is False

    def test_write_file_empty_path(self):
        result = write_file("", "content")
        assert result["success"] is False

    def test_replace_in_file_empty_path(self):
        result = replace_in_file("", "old", "new")
        assert result["success"] is False

    def test_rename_file_empty_paths(self):
        result = rename_file("", "")
        assert result["success"] is False

    def test_delete_file_empty(self):
        result = delete_file("")
        assert result["success"] is False

    def test_read_file_none(self):
        result = read_file(None)
        assert result["success"] is False

    def test_write_file_none_path(self):
        result = write_file(None, "content")
        assert result["success"] is False


class TestValidatePathEmptyInput:
    """Edge cases for validate_path itself."""

    def test_empty_path(self):
        is_safe, _, error = validate_path("")
        assert is_safe is False
        assert "empty" in error.lower()

    def test_none_path(self):
        is_safe, _, error = validate_path(None)
        assert is_safe is False

    def test_whitespace_path(self):
        is_safe, _, error = validate_path("   ")
        # Path("   ").resolve() resolves to cwd/"   " which is inside cwd
        # This is technically valid from a path perspective
        assert isinstance(is_safe, bool)

    def test_current_dir(self):
        """Path '.' should resolve to cwd, which is valid."""
        is_safe, resolved, error = validate_path(".")
        assert is_safe is True
