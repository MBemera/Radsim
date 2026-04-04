"""Tests for project detection caching in radsim.tools.testing."""

import json

from radsim.runtime_context import get_runtime_context
from radsim.tools.testing import detect_project_type


class TestDetectProjectType:
    """Tests for cached project detection."""

    def setup_method(self):
        get_runtime_context().clear_all()

    def teardown_method(self):
        get_runtime_context().clear_all()

    def test_detects_python_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

        result = detect_project_type()

        assert result["project_type"] == "python"
        assert result["test_framework"] == "pytest"

    def test_reuses_cached_package_json_until_file_changes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        package_json = tmp_path / "package.json"
        package_json.write_text(
            json.dumps({"scripts": {"test": "vitest", "lint": "eslint ."}}),
            encoding="utf-8",
        )

        first_result = detect_project_type()

        package_json.write_text(
            json.dumps({"scripts": {"test": "jest", "lint": "eslint ."}}),
            encoding="utf-8",
        )

        second_result = detect_project_type()

        assert first_result["test_framework"] == "vitest"
        assert second_result["test_framework"] == "jest"
