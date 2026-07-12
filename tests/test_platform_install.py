"""Tests for cross-platform detection and install command selection."""

from unittest.mock import patch

from radsim.tools import dependencies, platform_detect


class TestDetectOS:
    def test_darwin_is_macos(self):
        with patch("radsim.tools.platform_detect.platform.system", return_value="Darwin"):
            assert platform_detect.detect_os() == "macos"

    def test_windows(self):
        with patch("radsim.tools.platform_detect.platform.system", return_value="Windows"):
            assert platform_detect.detect_os() == "windows"

    def test_linux(self):
        with patch("radsim.tools.platform_detect.platform.system", return_value="Linux"):
            assert platform_detect.detect_os() == "linux"

    def test_unknown_platform_is_not_assumed_linux(self):
        with patch("radsim.tools.platform_detect.platform.system", return_value="Plan9"):
            assert platform_detect.detect_os() == "unknown"


class TestDetectPackageManager:
    def test_returns_first_available(self):
        def only_dnf(name):
            return "/usr/bin/dnf" if name == "dnf" else None

        with patch("radsim.tools.platform_detect.shutil.which", side_effect=only_dnf):
            assert platform_detect.detect_package_manager("linux") == "dnf"

    def test_none_when_nothing_available(self):
        with patch("radsim.tools.platform_detect.shutil.which", return_value=None):
            assert platform_detect.detect_package_manager("linux") is None


class TestInstallSystemToolCrossPlatform:
    """install_system_tool must not assume Homebrew on Linux."""

    def test_gh_on_linux_does_not_use_brew(self):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with patch("radsim.tools.dependencies.detect_os", return_value="linux"), \
             patch("radsim.tools.dependencies.detect_package_manager", return_value="dnf"), \
             patch("radsim.tools.dependencies.run_process", side_effect=fake_run):
            result = dependencies.install_system_tool("gh")

        assert result["success"] is True
        assert "brew" not in captured["cmd"]
        assert captured["cmd"][0] == "dnf"

    def test_gh_on_macos_uses_brew(self):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with patch("radsim.tools.dependencies.detect_os", return_value="macos"), \
             patch("radsim.tools.dependencies.detect_package_manager", return_value="brew"), \
             patch("radsim.tools.dependencies.run_process", side_effect=fake_run):
            dependencies.install_system_tool("gh")

        assert captured["cmd"] == ["brew", "install", "gh"]

    def test_npm_tool_is_cross_platform(self):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with patch("radsim.tools.dependencies.run_process", side_effect=fake_run):
            dependencies.install_system_tool("vercel")

        assert captured["cmd"][:3] == ["npm", "install", "-g"]

    def test_brew_prefix_without_brew_fails_cleanly(self):
        with patch("radsim.tools.dependencies.shutil.which", return_value=None):
            result = dependencies.install_system_tool("brew:some-tool")
        assert result["success"] is False
        assert "homebrew" in result["error"].lower()


class TestPythonProjectScaffolding:
    """Python project creation builds files directly, cross-platform."""

    def test_creates_structure(self, tmp_path):
        result = dependencies.init_project("python", name="myapp", working_dir=str(tmp_path))
        assert result["success"] is True
        assert (tmp_path / "myapp" / "__init__.py").exists()
        assert (tmp_path / "pyproject.toml").exists()
        assert 'name = "myapp"' in (tmp_path / "pyproject.toml").read_text()

    def test_rejects_traversal_name(self, tmp_path):
        result = dependencies.init_project("python", name="../evil", working_dir=str(tmp_path))
        assert result["success"] is False
        assert not (tmp_path.parent / "evil").exists()


class TestPackageArgumentInjection:
    """Package names starting with '-' must not reach the installer as flags."""

    def test_add_dependency_rejects_flag_like_name(self):
        result = dependencies.add_dependency("-rrequirements.txt")
        assert result["success"] is False
        assert "must not start with '-'" in result["error"]

    def test_pip_install_rejects_index_url_injection(self):
        result = dependencies.pip_install("--index-url=http://evil.example/simple")
        assert result["success"] is False
        assert "must not start with '-'" in result["error"]

    def test_npm_install_rejects_flag_like_name(self):
        result = dependencies.npm_install("--registry=http://evil.example")
        assert result["success"] is False

    def test_dependency_rejects_terminal_control_characters(self):
        for control_character in ("\x1b", "\x9b", "\u202e"):
            result = dependencies.pip_install(f"safe{control_character}[2Khidden")
            assert result["success"] is False
            assert "control" in result["error"]

    def test_install_system_tool_rejects_flag_after_prefix(self):
        result = dependencies.install_system_tool("pip:--index-url=http://evil.example")
        assert result["success"] is False

    def test_remove_dependency_rejects_empty(self):
        result = dependencies.remove_dependency("   ")
        assert result["success"] is False

    def test_npm_commands_reject_cmd_metacharacters(self):
        with patch(
            "radsim.tools.dependencies.detect_project_type",
            return_value={"package_manager": "npm"},
        ), patch("radsim.tools.dependencies.run_process") as mock_run:
            for metacharacter in "&|<>^%!":
                package = f"safe@1{metacharacter}whoami"
                assert dependencies.add_dependency(package)["success"] is False
                assert dependencies.remove_dependency(package)["success"] is False

        mock_run.assert_not_called()


class TestNpmSupplyChainPolicy:
    """Known malicious or unsafe npm package requests fail before execution."""

    def test_plain_crypto_js_is_blocked(self):
        result = dependencies.npm_install("plain-crypto-js")
        assert result["success"] is False
        assert "malicious" in result["error"].lower()

    def test_npm_alias_to_plain_crypto_js_is_blocked(self):
        result = dependencies.npm_install("safe-name@npm:plain-crypto-js@1.0.0")
        assert result["success"] is False

    def test_direct_npm_sources_are_blocked(self):
        unsafe_sources = (
            "https://registry.npmjs.org/plain-crypto-js/-/plain-crypto-js-1.0.0.tgz",
            "https://registry.npmjs.org/axios/-/axios-1.14.1.tgz",
            "file:../package.tgz",
            "git+https://example.com/package.git",
        )

        for source in unsafe_sources:
            result = dependencies.npm_install(source)
            assert result["success"] is False
            assert "registry package names" in result["error"]

    def test_compromised_axios_versions_are_blocked(self):
        for version in ("axios@1.14.1", "axios@0.30.4"):
            result = dependencies.npm_install(version)
            assert result["success"] is False

    def test_unpinned_axios_is_blocked(self):
        result = dependencies.npm_install("axios")
        assert result["success"] is False
        assert "pinned" in result["error"].lower()

    def test_known_safe_axios_is_passed_as_one_argv_item(self):
        with patch(
            "radsim.tools.dependencies.run_process",
            return_value={"returncode": 0, "stdout": "", "stderr": ""},
        ) as mock_run:
            result = dependencies.npm_install("axios@1.14.0")

        assert result["success"] is True
        assert mock_run.call_args.args[0][-1] == "axios@1.14.0"


class TestScaffoldArgumentSafety:
    def test_option_like_project_name_is_rejected(self):
        result = dependencies.init_project("vite", name="--registry")
        assert result["success"] is False

    def test_option_like_template_is_rejected(self):
        result = dependencies.init_project("vite", name="safe", template="--evil")
        assert result["success"] is False
