"""Tests for the Complexity Budget engine."""


import pytest

from radsim.complexity import (
    _count_branches,
    _count_long_functions,
    _count_single_letter_vars,
    _health_bar,
    _max_nesting_depth,
    calculate_file_complexity,
    check_budget,
    format_complexity_report,
    format_file_report,
    load_budget,
    save_budget,
    scan_project_complexity,
)


@pytest.fixture
def temp_dir(tmp_path):
    """Create a temp directory with sample Python files."""
    simple = tmp_path / "simple.py"
    simple.write_text(
        "def greet(name):\n"
        "    return f'Hello, {name}'\n"
    )

    complex_code = tmp_path / "complex.py"
    complex_code.write_text(
        "def process_data(data):\n"
        "    results = []\n"
        "    for item in data:\n"
        "        if item.get('type') == 'a':\n"
        "            if item.get('status') == 'active':\n"
        "                if item.get('score') > 0:\n"
        "                    for sub in item.get('children', []):\n"
        "                        if sub.get('valid'):\n"
        "                            results.append(sub)\n"
        "    return results\n"
    )

    # File with long function
    long_func = tmp_path / "long.py"
    body_lines = "\n".join(f"    x_{i} = {i}" for i in range(35))
    long_func.write_text(f"def really_long_function():\n{body_lines}\n    return x_0\n")

    # File with bad variables
    bad_vars = tmp_path / "bad_vars.py"
    bad_vars.write_text(
        "a = 10\n"
        "b = 20\n"
        "c = a + b\n"
        "result = c * 2\n"
    )

    return tmp_path


class TestBranchCounting:
    def test_python_branches(self):
        code = "if x:\n  pass\nfor i in range(10):\n  pass\nwhile True:\n  break\n"
        assert _count_branches(code, ".py") == 3

    def test_python_complex_branches(self):
        code = "if x and y or z:\n  if a:\n    pass\n  elif b:\n    pass\n"
        assert _count_branches(code, ".py") >= 4

    def test_javascript_branches(self):
        code = "if (x) {} for (let i=0; i<10; i++) {} while (true) {}\n"
        assert _count_branches(code, ".js") == 3

    def test_empty_content(self):
        assert _count_branches("", ".py") == 0


class TestNestingDepth:
    def test_flat_code(self):
        code = "x = 1\ny = 2\nresult = x + y\n"
        assert _max_nesting_depth(code) == 0

    def test_single_indent(self):
        code = "def foo():\n    return 1\n"
        assert _max_nesting_depth(code) == 1

    def test_deep_nesting(self):
        code = (
            "def foo():\n"
            "    if x:\n"
            "        for i in range(10):\n"
            "            if y:\n"
            "                if z:\n"
            "                    pass\n"
        )
        assert _max_nesting_depth(code) >= 4

    def test_comments_ignored(self):
        code = "# This is a comment\n        # Deep comment\nx = 1\n"
        assert _max_nesting_depth(code) == 0


class TestLongFunctions:
    def test_short_function(self):
        code = "def short():\n    return 1\n"
        count, funcs = _count_long_functions(code, ".py")
        assert count == 0
        assert funcs == []

    def test_long_function(self):
        lines = "\n".join(f"    line_{i} = {i}" for i in range(35))
        code = f"def long_func():\n{lines}\n"
        count, funcs = _count_long_functions(code, ".py")
        assert count == 1
        assert funcs[0]["name"] == "long_func"
        assert funcs[0]["lines"] > 30


class TestSingleLetterVars:
    def test_bad_vars(self):
        code = "a = 1\nb = 2\n"
        count = _count_single_letter_vars(code, ".py")
        assert count == 2

    def test_allowed_vars(self):
        code = "i = 0\nj = 1\nk = 2\nx = 3\ny = 4\n"
        count = _count_single_letter_vars(code, ".py")
        assert count == 0

    def test_normal_vars(self):
        code = "name = 'test'\ncount = 0\n"
        count = _count_single_letter_vars(code, ".py")
        assert count == 0


class TestCalculateFileComplexity:
    def test_simple_file(self, temp_dir):
        result = calculate_file_complexity(temp_dir / "simple.py")
        assert result is not None
        assert result["score"] >= 0
        assert result["basename"] == "simple.py"
        assert "breakdown" in result

    def test_complex_file(self, temp_dir):
        result = calculate_file_complexity(temp_dir / "complex.py")
        assert result is not None
        assert result["score"] > 0  # Should have branches + nesting
        assert result["breakdown"]["branches"] > 0

    def test_unsupported_extension(self, tmp_path):
        txt = tmp_path / "readme.txt"
        txt.write_text("Hello world")
        result = calculate_file_complexity(txt)
        assert result is None

    def test_nonexistent_file(self):
        result = calculate_file_complexity("/nonexistent/file.py")
        assert result is None

    def test_empty_file(self, tmp_path):
        empty = tmp_path / "empty.py"
        empty.write_text("")
        result = calculate_file_complexity(empty)
        assert result is not None
        assert result["score"] == 0


class TestScanProject:
    def test_scan_directory(self, temp_dir):
        result = scan_project_complexity(temp_dir)
        assert result["file_count"] >= 3
        assert result["total_score"] > 0
        assert len(result["files"]) >= 3
        assert len(result["hotspots"]) > 0

    def test_scan_sorted_by_score(self, temp_dir):
        result = scan_project_complexity(temp_dir)
        scores = [f["score"] for f in result["files"]]
        assert scores == sorted(scores, reverse=True)


class TestBudget:
    def test_save_and_load(self, tmp_path, monkeypatch):
        budget_file = tmp_path / "complexity_budget.json"
        monkeypatch.setattr("radsim.complexity.BUDGET_FILE", budget_file)

        save_budget(200)
        assert load_budget() == 200

    def test_load_no_file(self, tmp_path, monkeypatch):
        budget_file = tmp_path / "nonexistent.json"
        monkeypatch.setattr("radsim.complexity.BUDGET_FILE", budget_file)

        assert load_budget() is None

    def test_check_within_budget(self, temp_dir, tmp_path, monkeypatch):
        budget_file = tmp_path / "budget.json"
        monkeypatch.setattr("radsim.complexity.BUDGET_FILE", budget_file)

        save_budget(10000)  # Very high budget
        result = check_budget(temp_dir)
        assert result["within_budget"] is True

    def test_check_over_budget(self, temp_dir, tmp_path, monkeypatch):
        budget_file = tmp_path / "budget.json"
        monkeypatch.setattr("radsim.complexity.BUDGET_FILE", budget_file)

        save_budget(0)  # Impossibly low budget
        result = check_budget(temp_dir)
        # Score > 0, budget = 0, so over budget
        if result["score"] > 0:
            assert result["within_budget"] is False


class TestFormatting:
    def test_health_bar_within(self):
        bar = _health_bar(50, 100)
        assert "50/100" in bar
        assert "█" in bar

    def test_health_bar_no_budget(self):
        bar = _health_bar(50, None)
        assert "50/∞" in bar

    def test_format_report_returns_lines(self, temp_dir):
        scan = scan_project_complexity(temp_dir)
        lines = format_complexity_report(scan, budget=500)
        assert len(lines) > 5
        assert any("COMPLEXITY REPORT" in line for line in lines)

    def test_format_file_report(self, temp_dir):
        result = calculate_file_complexity(temp_dir / "complex.py")
        lines = format_file_report(result)
        assert len(lines) > 3
        assert any("Score" in line for line in lines)
