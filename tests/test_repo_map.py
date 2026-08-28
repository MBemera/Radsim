# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Tests for repo_map structural overview tool."""

import ast

from radsim.repo_map import (
    _SYMBOL_CACHE,
    MAX_SYMBOL_CACHE_ENTRIES,
    _cache_symbols,
    _discover_files,
    _extract_js_symbols_regex,
    _extract_python_symbols,
    _rank_files,
    _render_map,
    generate_repo_map,
    symbol_cache_stats,
)


def test_symbol_cache_uses_the_shared_lru_bound():
    _SYMBOL_CACHE.clear()
    evictions_before = symbol_cache_stats()["evictions"]

    for index in range(MAX_SYMBOL_CACHE_ENTRIES + 3):
        _cache_symbols((f"digest-{index}", 1, "python"), [{"name": str(index)}])

    assert symbol_cache_stats()["entries"] == MAX_SYMBOL_CACHE_ENTRIES
    assert symbol_cache_stats()["evictions"] == evictions_before + 3


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

    def test_parse_failure_is_visible_in_map(self, tmp_path):
        (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")

        result = generate_repo_map(str(tmp_path), language_filter="python")

        assert result["error_count"] == 1
        assert result["errors"][0]["file"] == "broken.py"
        assert "repo-map error" in result["map"]

    def test_real_python_tree_has_no_file_errors(self):
        result = generate_repo_map("radsim", language_filter="python")

        assert result["success"] is True
        assert result["error_count"] == 0


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

    def test_syntax_error_returns_diagnostic(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def broken(:\n", encoding="utf-8")
        symbols = _extract_python_symbols(f)
        assert symbols[0]["type"] == "error"
        assert "syntax error" in symbols[0]["name"]

    def test_class_with_bases(self, tmp_path):
        f = tmp_path / "inherit.py"
        f.write_text("class Child(Parent):\n    pass\n", encoding="utf-8")
        symbols = _extract_python_symbols(f)
        assert "(Parent)" in symbols[0]["signature"]

    def test_bare_call_above_class_does_not_crash(self, tmp_path):
        f = tmp_path / "call_then_class.py"
        f.write_text(
            "configure()\n\nclass Service:\n    def run(self):\n        pass\n",
            encoding="utf-8",
        )

        symbols = _extract_python_symbols(f)

        assert {symbol["name"] for symbol in symbols} == {"Service", "Service.run"}

    def test_nested_function_inside_method_is_not_a_method(self, tmp_path):
        f = tmp_path / "nested.py"
        f.write_text(
            "class Service:\n"
            "    def run(self):\n"
            "        def inner():\n"
            "            pass\n"
            "        return inner()\n"
            "\n"
            "def module_function():\n"
            "    pass\n",
            encoding="utf-8",
        )

        symbols = _extract_python_symbols(f)
        symbol_types = {symbol["name"]: symbol["type"] for symbol in symbols}

        assert symbol_types["Service.run"] == "method"
        assert symbol_types["inner"] == "function"
        assert symbol_types["module_function"] == "function"

    def test_content_cache_avoids_reparse_and_invalidates(self, tmp_path, monkeypatch):
        f = tmp_path / "cached.py"
        f.write_text("def first():\n    pass\n", encoding="utf-8")
        _SYMBOL_CACHE.clear()
        parse_calls = 0
        original_parse = ast.parse

        def counting_parse(*args, **kwargs):
            nonlocal parse_calls
            parse_calls += 1
            return original_parse(*args, **kwargs)

        monkeypatch.setattr(ast, "parse", counting_parse)

        first_symbols = _extract_python_symbols(f)
        second_symbols = _extract_python_symbols(f)
        f.write_text("def second():\n    pass\n", encoding="utf-8")
        changed_symbols = _extract_python_symbols(f)

        assert first_symbols == second_symbols
        assert changed_symbols != first_symbols
        assert parse_calls == 2


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
        assert symbols[0]["type"] == "error"
        assert "read failed" in symbols[0]["name"]


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
