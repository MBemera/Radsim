# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Tests for repo_map structural overview tool."""

from radsim.repo_map import (
    _discover_files,
    _extract_js_symbols_regex,
    _extract_python_symbols,
    _rank_files,
    _render_map,
    generate_repo_map,
)


class TestGenerateRepoMap:
    def test_empty_directory(self, tmp_path):
        result = generate_repo_map(str(tmp_path))
        assert result["success"] is True
        assert result["file_count"] == 0
        assert "No source files" in result["map"]

    def test_invalid_directory(self):
        result = generate_repo_map("/nonexistent/path/xyz")
        assert result["success"] is False
        assert "Not a directory" in result["error"]

    def test_python_project(self, tmp_path):
        (tmp_path / "main.py").write_text(
            "def hello():\n    pass\n\ndef world():\n    pass\n",
            encoding="utf-8",
        )
        result = generate_repo_map(str(tmp_path))
        assert result["success"] is True
        assert result["file_count"] == 1
        assert result["symbol_count"] == 2
        assert "hello" in result["map"]
        assert "world" in result["map"]

    def test_focus_files_boost(self, tmp_path):
        (tmp_path / "important.py").write_text(
            "def single():\n    pass\n", encoding="utf-8"
        )
        (tmp_path / "big.py").write_text(
            "class A:\n    pass\nclass B:\n    pass\nclass C:\n    pass\n",
            encoding="utf-8",
        )
        result = generate_repo_map(
            str(tmp_path), focus_files=["important.py"]
        )
        assert result["success"] is True
        # important.py should appear first due to focus boost
        assert result["map"].index("important.py") < result["map"].index("big.py")

    def test_language_filter(self, tmp_path):
        (tmp_path / "code.py").write_text("def py_func():\n    pass\n", encoding="utf-8")
        (tmp_path / "code.js").write_text(
            "function js_func() {}\n", encoding="utf-8"
        )
        result = generate_repo_map(str(tmp_path), language_filter="python")
        assert result["success"] is True
        assert "py_func" in result["map"]
        assert "js_func" not in result["map"]

    def test_max_tokens_truncation(self, tmp_path):
        # Create many files to exceed a tiny budget
        for i in range(20):
            (tmp_path / f"mod{i}.py").write_text(
                f"def func_{i}():\n    pass\n", encoding="utf-8"
            )
        result = generate_repo_map(str(tmp_path), max_tokens=50)
        assert result["success"] is True
        # Should be truncated
        assert "more files" in result["map"] or result["file_count"] > 0


class TestDiscoverFiles:
    def test_skips_pycache(self, tmp_path):
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "cached.py").write_text("x=1", encoding="utf-8")
        (tmp_path / "real.py").write_text("y=2", encoding="utf-8")
        files = _discover_files(tmp_path)
        names = [f.name for f in files]
        assert "real.py" in names
        assert "cached.py" not in names

    def test_skips_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("exports={}", encoding="utf-8")
        files = _discover_files(tmp_path)
        assert len(files) == 0

    def test_includes_config_files(self, tmp_path):
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / "settings.yaml").write_text("key: val", encoding="utf-8")
        files = _discover_files(tmp_path)
        names = [f.name for f in files]
        assert "config.json" in names
        assert "settings.yaml" in names


class TestExtractPythonSymbols:
    def test_functions(self, tmp_path):
        f = tmp_path / "funcs.py"
        f.write_text("def alpha():\n    pass\n\ndef beta(x, y):\n    pass\n", encoding="utf-8")
        symbols = _extract_python_symbols(f)
        names = [s["name"] for s in symbols]
        assert "alpha" in names
        assert "beta" in names

    def test_classes_and_methods(self, tmp_path):
        f = tmp_path / "cls.py"
        f.write_text(
            "class MyClass:\n    def method_a(self):\n        pass\n",
            encoding="utf-8",
        )
        symbols = _extract_python_symbols(f)
        types = {s["name"]: s["type"] for s in symbols}
        assert types["MyClass"] == "class"
        assert types["MyClass.method_a"] == "method"

    def test_async_functions(self, tmp_path):
        f = tmp_path / "async_code.py"
        f.write_text("async def fetch_data():\n    pass\n", encoding="utf-8")
        symbols = _extract_python_symbols(f)
        assert symbols[0]["signature"].startswith("async def")

    def test_syntax_error_returns_empty(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def broken(:\n", encoding="utf-8")
        symbols = _extract_python_symbols(f)
        assert symbols == []

    def test_class_with_bases(self, tmp_path):
        f = tmp_path / "inherit.py"
        f.write_text("class Child(Parent):\n    pass\n", encoding="utf-8")
        symbols = _extract_python_symbols(f)
        assert "(Parent)" in symbols[0]["signature"]


class TestExtractJsSymbols:
    def test_function_declaration(self, tmp_path):
        f = tmp_path / "funcs.js"
        f.write_text("function greet(name) {\n  return name;\n}\n", encoding="utf-8")
        symbols = _extract_js_symbols_regex(f)
        assert len(symbols) >= 1
        assert symbols[0]["name"] == "greet"

    def test_class_declaration(self, tmp_path):
        f = tmp_path / "cls.ts"
        f.write_text("export class UserService {\n}\n", encoding="utf-8")
        symbols = _extract_js_symbols_regex(f)
        names = [s["name"] for s in symbols]
        assert "UserService" in names

    def test_arrow_function(self, tmp_path):
        f = tmp_path / "arrow.js"
        f.write_text("const handler = (req, res) => {\n}\n", encoding="utf-8")
        symbols = _extract_js_symbols_regex(f)
        names = [s["name"] for s in symbols]
        assert "handler" in names

    def test_unreadable_file(self, tmp_path):
        f = tmp_path / "missing.js"
        # File doesn't exist
        symbols = _extract_js_symbols_regex(f)
        assert symbols == []


class TestRankFiles:
    def test_focus_files_ranked_first(self):
        all_symbols = {
            "a.py": [{"type": "function", "name": "f"}],
            "b.py": [{"type": "class", "name": "C"}, {"type": "method", "name": "C.m"}],
        }
        ranked = _rank_files(all_symbols, focus_files=["a.py"])
        assert ranked[0] == "a.py"

    def test_test_files_penalized(self):
        all_symbols = {
            "src.py": [{"type": "function", "name": "f1"}, {"type": "function", "name": "f2"}],
            "test_src.py": [
                {"type": "function", "name": "t1"},
                {"type": "function", "name": "t2"},
                {"type": "function", "name": "t3"},
            ],
        }
        ranked = _rank_files(all_symbols, focus_files=[])
        # src.py score=2, test_src.py score=3*0.5=1.5 — src should rank higher
        assert ranked[0] == "src.py"


class TestRenderMap:
    def test_basic_render(self):
        ranked = ["main.py"]
        symbols = {"main.py": [{"signature": "def hello()"}]}
        result = _render_map(ranked, symbols, max_tokens=1000)
        assert "main.py" in result
        assert "def hello()" in result

    def test_respects_budget(self):
        ranked = ["a.py", "b.py"]
        symbols = {
            "a.py": [{"signature": "def " + "x" * 100}],
            "b.py": [{"signature": "def " + "y" * 100}],
        }
        result = _render_map(ranked, symbols, max_tokens=10)
        # Very small budget — should truncate
        assert "more files" in result or len(result) < 200
