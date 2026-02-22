"""Tests for the Code Archaeology engine."""


import pytest

from radsim.archaeology import (
    find_dead_functions,
    find_orphaned_files,
    find_unused_imports,
    find_zombie_dependencies,
    format_archaeology_report,
    format_deps_report,
    format_imports_report,
    run_full_archaeology,
    scan_unused_imports,
)


@pytest.fixture
def project_dir(tmp_path):
    """Create a mini project structure for testing."""
    # main.py — entry point, imports utils
    main = tmp_path / "main.py"
    main.write_text(
        "from utils import helper_function\n"
        "import os\n"
        "\n"
        "def main():\n"
        "    result = helper_function()\n"
        "    print(result)\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )

    # utils.py — referenced by main.py
    utils = tmp_path / "utils.py"
    utils.write_text(
        "import json\n"
        "import re\n"
        "\n"
        "def helper_function():\n"
        "    return 'hello'\n"
        "\n"
        "def dead_function():\n"
        "    '''This function is never called anywhere.'''\n"
        "    return 42\n"
        "\n"
        "def another_dead():\n"
        "    '''Also never called.'''\n"
        "    return 99\n"
    )

    # config.py — orphaned, never imported by anyone
    config = tmp_path / "config.py"
    config.write_text(
        "import os\n"
        "\n"
        "DEBUG = True\n"
        "HOST = 'localhost'\n"
    )

    # requirements.txt with zombie deps
    reqs = tmp_path / "requirements.txt"
    reqs.write_text(
        "os\n"
        "json\n"
        "flask>=2.0\n"
        "requests>=2.28\n"
        "# This is a comment\n"
    )

    return tmp_path


class TestDeadFunctions:
    def test_finds_dead_functions(self, project_dir):
        dead = find_dead_functions(project_dir)
        dead_names = [d["function"] for d in dead]
        assert "dead_function" in dead_names
        assert "another_dead" in dead_names

    def test_live_function_not_flagged(self, project_dir):
        dead = find_dead_functions(project_dir)
        dead_names = [d["function"] for d in dead]
        assert "helper_function" not in dead_names
        assert "main" not in dead_names

    def test_result_structure(self, project_dir):
        dead = find_dead_functions(project_dir)
        if dead:
            item = dead[0]
            assert "file" in item
            assert "function" in item
            assert "line" in item
            assert "basename" in item

    def test_empty_directory(self, tmp_path):
        dead = find_dead_functions(tmp_path)
        assert dead == []


class TestOrphanedFiles:
    def test_finds_orphaned_files(self, project_dir):
        orphaned = find_orphaned_files(project_dir)
        orphaned_names = [o["basename"] for o in orphaned]
        assert "config.py" in orphaned_names

    def test_imported_file_not_orphaned(self, project_dir):
        orphaned = find_orphaned_files(project_dir)
        orphaned_names = [o["basename"] for o in orphaned]
        assert "utils.py" not in orphaned_names

    def test_skips_init(self, project_dir):
        init = project_dir / "__init__.py"
        init.write_text("")
        orphaned = find_orphaned_files(project_dir)
        orphaned_names = [o["basename"] for o in orphaned]
        assert "__init__.py" not in orphaned_names

    def test_skips_test_files(self, project_dir):
        test = project_dir / "test_something.py"
        test.write_text("def test_foo():\n    assert True\n")
        orphaned = find_orphaned_files(project_dir)
        orphaned_names = [o["basename"] for o in orphaned]
        assert "test_something.py" not in orphaned_names


class TestZombieDependencies:
    def test_finds_zombie_deps(self, project_dir):
        zombies = find_zombie_dependencies(project_dir)
        zombie_names = [z["package"] for z in zombies]
        # flask and requests are in requirements.txt but never imported
        assert "flask" in zombie_names
        assert "requests" in zombie_names

    def test_imported_deps_not_flagged(self, project_dir):
        zombies = find_zombie_dependencies(project_dir)
        zombie_names = [z["package"] for z in zombies]
        # json and os are imported and used
        assert "os" not in zombie_names
        assert "json" not in zombie_names

    def test_no_requirements_file(self, tmp_path):
        zombies = find_zombie_dependencies(tmp_path)
        assert zombies == []


class TestUnusedImports:
    def test_finds_unused_import(self, project_dir):
        # utils.py imports re but never uses it
        unused = find_unused_imports(project_dir / "utils.py")
        unused_names = [u["import_name"] for u in unused]
        assert "re" in unused_names

    def test_used_import_not_flagged(self, project_dir):
        unused = find_unused_imports(project_dir / "main.py")
        unused_names = [u["import_name"] for u in unused]
        assert "helper_function" not in unused_names

    def test_unsupported_extension(self, tmp_path):
        js = tmp_path / "app.js"
        js.write_text("const x = require('express')\n")
        unused = find_unused_imports(js)
        assert unused == []

    def test_nonexistent_file(self):
        unused = find_unused_imports("/nonexistent.py")
        assert unused == []


class TestScanUnusedImports:
    def test_scans_directory(self, project_dir):
        results = scan_unused_imports(project_dir)
        assert isinstance(results, list)
        # Should find at least the 're' import in utils.py
        all_unused = []
        for r in results:
            all_unused.extend(r["unused_imports"])
        unused_names = [u["import_name"] for u in all_unused]
        assert "re" in unused_names


class TestFullArchaeology:
    def test_full_scan(self, project_dir):
        results = run_full_archaeology(project_dir)
        assert "dead_functions" in results
        assert "orphaned_files" in results
        assert "zombie_deps" in results
        assert "unused_imports" in results
        assert "summary" in results

    def test_summary_structure(self, project_dir):
        results = run_full_archaeology(project_dir)
        summary = results["summary"]
        assert "dead_function_count" in summary
        assert "orphaned_file_count" in summary
        assert "zombie_dep_count" in summary
        assert "unused_import_count" in summary
        assert "estimated_cleanup_lines" in summary


class TestFormatting:
    def test_full_report(self, project_dir):
        results = run_full_archaeology(project_dir)
        lines = format_archaeology_report(results)
        assert len(lines) > 5
        assert any("ARCHAEOLOGY" in line for line in lines)

    def test_imports_report(self, project_dir):
        results = scan_unused_imports(project_dir)
        lines = format_imports_report(results)
        assert isinstance(lines, list)
        assert len(lines) > 0

    def test_deps_report(self, project_dir):
        zombies = find_zombie_dependencies(project_dir)
        lines = format_deps_report(zombies)
        assert isinstance(lines, list)
        assert len(lines) > 0

    def test_empty_report(self, tmp_path):
        results = run_full_archaeology(tmp_path)
        lines = format_archaeology_report(results)
        assert any("✅" in line for line in lines)
