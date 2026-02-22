"""Tests for radsim/tools/search.py

One test, one thing. Use tmp_path for file system operations.
"""


from radsim.tools.search import glob_files, grep_search

# =============================================================================
# glob_files tests
# =============================================================================


class TestGlobFiles:
    """Tests for glob_files function."""

    def test_glob_matches_python_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "main.py").touch()
        (tmp_path / "utils.py").touch()
        (tmp_path / "readme.md").touch()

        result = glob_files("*.py", str(tmp_path))

        assert result["success"] is True
        assert result["count"] == 2
        assert "main.py" in result["matches"]
        assert "utils.py" in result["matches"]

    def test_glob_no_matches_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data.csv").touch()

        result = glob_files("*.py", str(tmp_path))

        assert result["success"] is True
        assert result["count"] == 0
        assert result["matches"] == []

    def test_glob_nested_directories(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        nested_dir = tmp_path / "src" / "lib"
        nested_dir.mkdir(parents=True)
        (nested_dir / "deep.py").touch()
        (tmp_path / "top.py").touch()

        result = glob_files("**/*.py", str(tmp_path))

        assert result["success"] is True
        assert result["count"] == 2
        matched_names = [m.split("/")[-1] for m in result["matches"]]
        assert "deep.py" in matched_names
        assert "top.py" in matched_names

    def test_glob_skips_hidden_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "visible.py").touch()
        hidden_dir = tmp_path / ".hidden"
        hidden_dir.mkdir()
        (hidden_dir / "secret.py").touch()

        result = glob_files("**/*.py", str(tmp_path))

        assert result["success"] is True
        matched_names = [m.split("/")[-1] for m in result["matches"]]
        assert "visible.py" in matched_names
        assert "secret.py" not in matched_names

    def test_glob_returns_sorted_matches(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "zebra.py").touch()
        (tmp_path / "alpha.py").touch()
        (tmp_path / "middle.py").touch()

        result = glob_files("*.py", str(tmp_path))

        assert result["success"] is True
        assert result["matches"] == sorted(result["matches"])

    def test_glob_invalid_directory_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = glob_files("*.py", "/nonexistent/path/that/does/not/exist")

        assert result["success"] is False


# =============================================================================
# grep_search tests
# =============================================================================


class TestGrepSearch:
    """Tests for grep_search function."""

    def test_grep_finds_matching_text(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "code.py"
        test_file.write_text("def hello_world():\n    return 42\n")

        result = grep_search("hello_world", str(tmp_path))

        assert result["success"] is True
        assert result["count"] >= 1
        assert any("hello_world" in m["content"] for m in result["matches"])

    def test_grep_no_matches_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "code.py"
        test_file.write_text("def greet():\n    pass\n")

        result = grep_search("NONEXISTENT_PATTERN", str(tmp_path))

        assert result["success"] is True
        assert result["count"] == 0
        assert result["matches"] == []

    def test_grep_regex_pattern(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "data.txt"
        test_file.write_text("error: something failed\nwarning: be careful\ninfo: all good\n")

        result = grep_search(r"error|warning", str(tmp_path))

        assert result["success"] is True
        assert result["count"] == 2

    def test_grep_invalid_regex_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = grep_search("[invalid regex", str(tmp_path))

        assert result["success"] is False
        assert "invalid regex" in result["error"].lower()

    def test_grep_case_insensitive(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "mixed.txt"
        test_file.write_text("Hello\nhELLO\nhello\n")

        result = grep_search("hello", str(tmp_path), ignore_case=True)

        assert result["success"] is True
        assert result["count"] == 3

    def test_grep_file_pattern_filter(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        py_file = tmp_path / "code.py"
        py_file.write_text("target_text = True\n")
        js_file = tmp_path / "code.js"
        js_file.write_text("const target_text = true;\n")

        result = grep_search("target_text", str(tmp_path), file_pattern="*.py")

        assert result["success"] is True
        assert result["count"] == 1
        assert result["matches"][0]["file"].endswith(".py")

    def test_grep_skips_hidden_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        visible = tmp_path / "visible.txt"
        visible.write_text("findme\n")
        hidden = tmp_path / ".hidden_file"
        hidden.write_text("findme\n")

        result = grep_search("findme", str(tmp_path))

        assert result["success"] is True
        matched_files = [m["file"] for m in result["matches"]]
        assert not any(".hidden_file" in f for f in matched_files)

    def test_grep_reports_line_numbers(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        test_file = tmp_path / "numbered.txt"
        test_file.write_text("aaa\nbbb\nccc\ntarget\neee\n")

        result = grep_search("target", str(tmp_path))

        assert result["success"] is True
        assert result["matches"][0]["line"] == 4

    def test_grep_reports_files_searched_count(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "file1.txt").write_text("content\n")
        (tmp_path / "file2.txt").write_text("content\n")

        result = grep_search("content", str(tmp_path))

        assert result["success"] is True
        assert result["files_searched"] == 2
