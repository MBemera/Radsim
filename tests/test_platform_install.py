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
             patch("radsim.tools.dependencies.run_shell_command", side_effect=fake_run):
            result = dependencies.install_system_tool("gh")

        assert result["success"] is True
        assert "brew" not in captured["cmd"]
        assert "dnf" in captured["cmd"]

    def test_gh_on_macos_uses_brew(self):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with patch("radsim.tools.dependencies.detect_os", return_value="macos"), \
             patch("radsim.tools.dependencies.run_shell_command", side_effect=fake_run):
            dependencies.install_system_tool("gh")

        assert "brew install gh" in captured["cmd"]

    def test_npm_tool_is_cross_platform(self):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with patch("radsim.tools.dependencies.run_shell_command", side_effect=fake_run):
            dependencies.install_system_tool("vercel")

        assert captured["cmd"].startswith("npm install -g")

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
