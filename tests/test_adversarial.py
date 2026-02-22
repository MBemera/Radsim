"""Tests for the Adversarial Code Review engine."""


import pytest

from radsim.adversarial import (
    _detect_bare_except,
    _detect_boundary_issues,
    _detect_missing_input_validation,
    _detect_unguarded_io,
    _find_containing_function,
    _is_in_try_block,
    format_stress_report,
    stress_test_directory,
    stress_test_file,
)


@pytest.fixture
def temp_dir(tmp_path):
    """Create a temp directory with sample Python files."""

    # Good code — should pass
    good = tmp_path / "good.py"
    good.write_text(
        "def calculate_total(items):\n"
        "    if not items:\n"
        "        raise ValueError('items cannot be empty')\n"
        "    total = 0\n"
        "    for item in items:\n"
        "        total += item.price\n"
        "    return total\n"
    )

    # Bad code — should fail
    bad = tmp_path / "bad.py"
    bad.write_text(
        "def process(data):\n"
        "    result = data.split(',')\n"
        "    return result\n"
        "\n"
        "def load_stuff():\n"
        "    try:\n"
        "        f = open('data.txt')\n"
        "        return f.read()\n"
        "    except:\n"
        "        pass\n"
        "\n"
        "def risky_io():\n"
        "    content = open('file.txt').read()\n"
        "    return content\n"
    )

    return tmp_path


class TestMissingInputValidation:
    def test_detects_unguarded_function(self):
        code = (
            "def process(data):\n"
            "    result = data.split(',')\n"
            "    return result\n"
        )
        issues = _detect_missing_input_validation(code, ".py")
        assert len(issues) >= 1
        assert issues[0]["category"] == "input_validation"

    def test_skips_validated_function(self):
        code = (
            "def process(data):\n"
            "    if not data:\n"
            "        raise ValueError('data required')\n"
            "    return data.split(',')\n"
        )
        issues = _detect_missing_input_validation(code, ".py")
        assert len(issues) == 0

    def test_skips_dunder_methods(self):
        code = (
            "def __init__(self, value):\n"
            "    self.value = value\n"
        )
        issues = _detect_missing_input_validation(code, ".py")
        assert len(issues) == 0

    def test_skips_no_params(self):
        code = (
            "def get_time():\n"
            "    import time\n"
            "    return time.time()\n"
        )
        issues = _detect_missing_input_validation(code, ".py")
        assert len(issues) == 0


class TestBareExcept:
    def test_detects_bare_except(self):
        code = (
            "try:\n"
            "    risky()\n"
            "except:\n"
            "    pass\n"
        )
        issues = _detect_bare_except(code, ".py")
        assert len(issues) >= 1
        assert issues[0]["severity"] == "high"

    def test_detects_exception_catch_all(self):
        code = (
            "try:\n"
            "    risky()\n"
            "except Exception:\n"
            "    pass\n"
        )
        issues = _detect_bare_except(code, ".py")
        assert len(issues) >= 1

    def test_allows_specific_exceptions(self):
        code = (
            "try:\n"
            "    risky()\n"
            "except ValueError as e:\n"
            "    handle(e)\n"
        )
        issues = _detect_bare_except(code, ".py")
        assert len(issues) == 0


class TestUnguardedIO:
    def test_detects_unguarded_open(self):
        code = (
            "def read_file():\n"
            "    content = open('data.txt').read()\n"
            "    return content\n"
        )
        issues = _detect_unguarded_io(code, ".py")
        assert len(issues) >= 1
        assert issues[0]["category"] == "io_safety"

    def test_allows_guarded_open(self):
        code = (
            "def read_file():\n"
            "    try:\n"
            "        content = open('data.txt').read()\n"
            "        return content\n"
            "    except OSError:\n"
            "        return None\n"
        )
        issues = _detect_unguarded_io(code, ".py")
        assert len(issues) == 0


class TestBoundaryIssues:
    def test_detects_range_len_minus_one(self):
        code = (
            "def process(items):\n"
            "    for i in range(len(items) - 1):\n"
            "        pass\n"
        )
        issues = _detect_boundary_issues(code, ".py")
        assert len(issues) >= 1
        assert issues[0]["category"] == "boundary"


class TestHelpers:
    def test_find_containing_function(self):
        code = (
            "def foo():\n"
            "    x = 1\n"
            "\n"
            "def bar():\n"
            "    y = 2\n"
        )
        assert _find_containing_function(code, 2, ".py") == "foo"
        assert _find_containing_function(code, 5, ".py") == "bar"

    def test_find_function_in_module(self):
        code = "x = 1\ny = 2\n"
        assert _find_containing_function(code, 1, ".py") == "<module>"

    def test_is_in_try_block(self):
        lines = [
            "def foo():",
            "    try:",
            "        risky()",
            "    except:",
            "        pass",
        ]
        assert _is_in_try_block(lines, 2) is True
        assert _is_in_try_block(lines, 0) is False


class TestStressTestFile:
    def test_good_file_less_issues(self, temp_dir):
        result = stress_test_file(temp_dir / "good.py")
        assert result is not None
        assert result["basename"] == "good.py"
        # Good code should have fewer issues than bad code
        good_issue_count = len(result["issues"])

        bad_result = stress_test_file(temp_dir / "bad.py")
        bad_issue_count = len(bad_result["issues"])

        assert bad_issue_count > good_issue_count

    def test_unsupported_file(self, tmp_path):
        txt = tmp_path / "readme.txt"
        txt.write_text("Hello")
        assert stress_test_file(txt) is None

    def test_nonexistent_file(self):
        assert stress_test_file("/nonexistent.py") is None

    def test_result_structure(self, temp_dir):
        result = stress_test_file(temp_dir / "bad.py")
        assert "functions_tested" in result
        assert "passed" in result
        assert "failed" in result
        assert "issues" in result
        assert isinstance(result["issues"], list)


class TestStressTestDirectory:
    def test_scans_directory(self, temp_dir):
        result = stress_test_directory(temp_dir)
        assert result["total_functions"] > 0
        assert "severity" in result

    def test_result_structure(self, temp_dir):
        result = stress_test_directory(temp_dir)
        assert "total_issues" in result
        assert "total_functions" in result
        assert "total_passed" in result
        assert "files" in result


class TestFormatting:
    def test_format_directory_report(self, temp_dir):
        result = stress_test_directory(temp_dir)
        lines = format_stress_report(result)
        assert len(lines) > 3
        assert any("ADVERSARIAL" in line for line in lines)

    def test_format_single_file_report(self, temp_dir):
        result = stress_test_file(temp_dir / "bad.py")
        lines = format_stress_report(result)
        assert len(lines) > 3
        assert any("STRESS TEST" in line for line in lines)

    def test_format_clean_file(self, temp_dir):
        result = stress_test_file(temp_dir / "good.py")
        lines = format_stress_report(result)
        assert isinstance(lines, list)
