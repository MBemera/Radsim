"""Tests for the Access Control module."""


from radsim.access_control import _secure_compare, is_access_protected, verify_access_code


class TestSecureCompare:
    """Test constant-time string comparison."""

    def test_matching_strings(self):
        assert _secure_compare("hello", "hello") is True

    def test_non_matching_strings(self):
        assert _secure_compare("hello", "world") is False

    def test_empty_strings(self):
        assert _secure_compare("", "") is True

    def test_partial_match(self):
        assert _secure_compare("abc", "abcd") is False

    def test_unicode(self):
        assert _secure_compare("café", "café") is True
        assert _secure_compare("café", "cafe") is False


class TestAccessControl:
    """Test access code verification."""

    def test_no_code_configured_allows_access(self, monkeypatch):
        monkeypatch.delenv("RADSIM_ACCESS_CODE", raising=False)
        monkeypatch.setattr(
            "radsim.config.load_env_file",
            lambda: {"keys": {}},
        )
        assert verify_access_code("anything") is True

    def test_correct_code_passes(self, monkeypatch):
        monkeypatch.delenv("RADSIM_ACCESS_CODE", raising=False)
        monkeypatch.setattr(
            "radsim.config.load_env_file",
            lambda: {"keys": {"RADSIM_ACCESS_CODE": "secret123"}},
        )
        assert verify_access_code("secret123") is True

    def test_wrong_code_fails(self, monkeypatch):
        monkeypatch.delenv("RADSIM_ACCESS_CODE", raising=False)
        monkeypatch.setattr(
            "radsim.config.load_env_file",
            lambda: {"keys": {"RADSIM_ACCESS_CODE": "secret123"}},
        )
        assert verify_access_code("wrong") is False

    def test_whitespace_trimmed(self, monkeypatch):
        monkeypatch.delenv("RADSIM_ACCESS_CODE", raising=False)
        monkeypatch.setattr(
            "radsim.config.load_env_file",
            lambda: {"keys": {"RADSIM_ACCESS_CODE": "mycode"}},
        )
        assert verify_access_code("  mycode  ") is True

    def test_is_protected_when_code_set(self, monkeypatch):
        monkeypatch.delenv("RADSIM_ACCESS_CODE", raising=False)
        monkeypatch.setattr(
            "radsim.config.load_env_file",
            lambda: {"keys": {"RADSIM_ACCESS_CODE": "code"}},
        )
        assert is_access_protected() is True

    def test_not_protected_when_empty(self, monkeypatch):
        monkeypatch.delenv("RADSIM_ACCESS_CODE", raising=False)
        monkeypatch.setattr(
            "radsim.config.load_env_file",
            lambda: {"keys": {}},
        )
        assert is_access_protected() is False

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setattr(
            "radsim.config.load_env_file",
            lambda: {"keys": {}},
        )
        monkeypatch.setenv("RADSIM_ACCESS_CODE", "env_code")
        assert verify_access_code("env_code") is True
