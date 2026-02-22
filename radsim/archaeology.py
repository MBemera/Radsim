"""Code Archaeology Engine.

Finds dead code, orphaned files, zombie dependencies, and unused imports.
All operations are read-only — nothing is deleted or modified without
explicit user confirmation through the command handler.
"""

import os
import re
from pathlib import Path

# Extensions we analyze
CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx"}


# ---------------------------------------------------------------------------
# Dead function detection
# ---------------------------------------------------------------------------

def find_dead_functions(directory, extensions=None):
    """Find functions defined but never referenced anywhere else in the project.

    Args:
        directory: Root directory to scan
        extensions: Optional set of extensions to include

    Returns:
        List of dicts: [{file, function, line, last_modified}]
    """
    target_extensions = extensions or CODE_EXTENSIONS
    directory = Path(directory)

    # Phase 1: Collect all function definitions
    definitions = []
    all_content = {}  # file -> content cache

    for filepath in _walk_source_files(directory, target_extensions):
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        all_content[filepath] = content
        extension = filepath.suffix.lower()

        if extension == ".py":
            for match in re.finditer(r"^[ \t]*def\s+(\w+)\s*\(", content, re.MULTILINE):
                func_name = match.group(1)
                line_number = content[:match.start()].count("\n") + 1
                # Skip dunder methods (they're called implicitly)
                if func_name.startswith("__") and func_name.endswith("__"):
                    continue
                definitions.append({
                    "file": str(filepath),
                    "basename": filepath.name,
                    "function": func_name,
                    "line": line_number,
                })

        elif extension in {".js", ".ts", ".jsx", ".tsx"}:
            for match in re.finditer(r"function\s+(\w+)\s*\(", content):
                func_name = match.group(1)
                line_number = content[:match.start()].count("\n") + 1
                definitions.append({
                    "file": str(filepath),
                    "basename": filepath.name,
                    "function": func_name,
                    "line": line_number,
                })

    # Phase 2: Check which definitions are never referenced elsewhere
    dead = []
    for defn in definitions:
        func_name = defn["function"]
        def_file = defn["file"]
        referenced = False

        for filepath, content in all_content.items():
            if str(filepath) == def_file:
                # In the same file, check for calls (not the definition itself)
                # Count occurrences — if > 1, it's called somewhere
                occurrences = len(re.findall(r"\b" + re.escape(func_name) + r"\b", content))
                if occurrences > 1:  # More than just the def line
                    referenced = True
                    break
            else:
                # In a different file, any mention counts as a reference
                if re.search(r"\b" + re.escape(func_name) + r"\b", content):
                    referenced = True
                    break

        if not referenced:
            dead.append(defn)

    return dead


# ---------------------------------------------------------------------------
# Orphaned file detection
# ---------------------------------------------------------------------------

def find_orphaned_files(directory, extensions=None):
    """Find source files that are never imported by any other file.

    Args:
        directory: Root directory to scan
        extensions: Optional set of extensions to include

    Returns:
        List of dicts: [{file, basename}]
    """
    target_extensions = extensions or CODE_EXTENSIONS
    directory = Path(directory)

    all_files = list(_walk_source_files(directory, target_extensions))
    all_content = {}

    for filepath in all_files:
        try:
            all_content[filepath] = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

    orphaned = []

    for filepath in all_files:
        basename = filepath.stem  # filename without extension
        is_imported = False

        # Skip __init__.py, __main__.py, setup.py, conftest.py — they're entry points
        if basename in ("__init__", "__main__", "setup", "conftest", "main"):
            continue

        # Skip test files — they're run by test frameworks, not imported
        if basename.startswith("test_") or basename.endswith("_test"):
            continue

        for other_path, content in all_content.items():
            if other_path == filepath:
                continue

            # Check for Python imports
            if re.search(r"\bimport\s+" + re.escape(basename) + r"\b", content):
                is_imported = True
                break
            if re.search(r"from\s+[\w.]*" + re.escape(basename) + r"\s+import\b", content):
                is_imported = True
                break
            # Check for JS/TS imports
            if re.search(r"(?:require|import).*['\"].*" + re.escape(basename) + r"['\"]", content):
                is_imported = True
                break

        if not is_imported:
            orphaned.append({
                "file": str(filepath),
                "basename": filepath.name,
            })

    return orphaned


# ---------------------------------------------------------------------------
# Zombie dependency detection
# ---------------------------------------------------------------------------

def find_zombie_dependencies(directory):
    """Find packages in requirements.txt or pyproject.toml that are never imported.

    Args:
        directory: Root directory to scan

    Returns:
        List of dicts: [{package, source_file}]
    """
    directory = Path(directory)
    declared_packages = []

    # Read requirements.txt
    req_file = directory / "requirements.txt"
    if req_file.exists():
        try:
            for line in req_file.read_text().split("\n"):
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                # Extract package name (before any version specifier)
                package = re.split(r"[><=!~\[]", line)[0].strip()
                if package:
                    declared_packages.append({
                        "package": package,
                        "source": "requirements.txt",
                    })
        except OSError:
            pass

    # Read pyproject.toml dependencies
    pyproject = directory / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text()
            # Simple extraction: lines under [project] dependencies = [...]
            in_deps = False
            for line in content.split("\n"):
                if "dependencies" in line and "=" in line:
                    in_deps = True
                    continue
                if in_deps:
                    if line.strip() == "]":
                        in_deps = False
                        continue
                    # Extract package name from quoted dependency
                    match = re.search(r'"([a-zA-Z0-9_-]+)', line)
                    if match:
                        package = match.group(1)
                        declared_packages.append({
                            "package": package,
                            "source": "pyproject.toml",
                        })
        except OSError:
            pass

    if not declared_packages:
        return []

    # Collect all imports from source files
    all_imports = set()
    for filepath in _walk_source_files(directory, {".py"}):
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Collect import names
        for match in re.finditer(r"^\s*import\s+(\w+)", content, re.MULTILINE):
            all_imports.add(match.group(1))
        for match in re.finditer(r"^\s*from\s+(\w+)", content, re.MULTILINE):
            all_imports.add(match.group(1))

    # Check which declared packages are never imported
    # Package names can differ from import names (e.g., python-dotenv -> dotenv)
    # Use a mapping for common cases
    PACKAGE_TO_IMPORT = {
        "python-dotenv": "dotenv",
        "google-generativeai": "google",
        "google-cloud-aiplatform": "google",
        "beautifulsoup4": "bs4",
        "pillow": "PIL",
        "pyyaml": "yaml",
        "scikit-learn": "sklearn",
        "opencv-python": "cv2",
        "python-dateutil": "dateutil",
    }

    zombies = []
    # Also skip common meta-packages and build tools
    skip_packages = {"pip", "setuptools", "wheel", "hatchling", "hatch",
                     "pytest", "ruff", "black", "mypy", "flake8"}

    for decl in declared_packages:
        pkg = decl["package"].lower()
        if pkg in skip_packages:
            continue

        import_name = PACKAGE_TO_IMPORT.get(pkg, pkg.replace("-", "_"))

        if import_name not in all_imports:
            zombies.append(decl)

    return zombies


# ---------------------------------------------------------------------------
# Unused import detection
# ---------------------------------------------------------------------------

def find_unused_imports(file_path):
    """Find imports in a Python file that are never used.

    Args:
        file_path: Path to the Python file

    Returns:
        List of dicts: [{import_name, line, full_line}]
    """
    path = Path(file_path)
    if path.suffix.lower() != ".py":
        return []

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    unused = []
    lines = content.split("\n")

    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith("#"):
            continue

        # Match: from x import a, b, c
        match = re.match(r"from\s+[\w.]+\s+import\s+(.+)", stripped)
        if match:
            imports_str = match.group(1)
            # Handle parenthesized imports
            if imports_str.startswith("("):
                # Multi-line import — collect until closing paren
                import_block = imports_str
                for next_line in lines[line_number:]:
                    import_block += " " + next_line.strip()
                    if ")" in next_line:
                        break
                imports_str = import_block.strip("() ")

            for name in imports_str.split(","):
                name = name.strip()
                # Handle 'as' aliases
                if " as " in name:
                    name = name.split(" as ")[-1].strip()
                # Remove any trailing comments or parens
                name = name.split("#")[0].split(")")[0].strip()
                if not name or name == "\\":
                    continue

                # Check if this name appears anywhere in the rest of the file
                rest = content[content.index(line) + len(line):]
                if not re.search(r"\b" + re.escape(name) + r"\b", rest):
                    unused.append({
                        "import_name": name,
                        "line": line_number,
                        "full_line": stripped,
                    })

        # Match: import x
        match = re.match(r"import\s+(\w+)(?:\s+as\s+(\w+))?", stripped)
        if match and not stripped.startswith("from"):
            import_name = match.group(2) or match.group(1)
            rest = content[content.index(line) + len(line):]
            if not re.search(r"\b" + re.escape(import_name) + r"\b", rest):
                unused.append({
                    "import_name": import_name,
                    "line": line_number,
                    "full_line": stripped,
                })

    return unused


# ---------------------------------------------------------------------------
# Directory-wide unused import scan
# ---------------------------------------------------------------------------

def scan_unused_imports(directory, extensions=None):
    """Scan all Python files in a directory for unused imports.

    Args:
        directory: Root directory to scan
        extensions: Optional set of extensions (only .py supported for imports)

    Returns:
        List of dicts per file: [{file, basename, unused_imports}]
    """
    directory = Path(directory)
    results = []

    for filepath in _walk_source_files(directory, {".py"}):
        unused = find_unused_imports(filepath)
        if unused:
            results.append({
                "file": str(filepath),
                "basename": filepath.name,
                "unused_imports": unused,
            })

    return results


# ---------------------------------------------------------------------------
# Full archaeology report
# ---------------------------------------------------------------------------

def run_full_archaeology(directory):
    """Run all archaeology checks on a directory.

    Args:
        directory: Root directory to scan

    Returns:
        dict with dead_functions, orphaned_files, zombie_deps, unused_imports
    """
    directory = Path(directory)

    dead_functions = find_dead_functions(directory)
    orphaned_files = find_orphaned_files(directory)
    zombie_deps = find_zombie_dependencies(directory)
    unused_imports = scan_unused_imports(directory)

    total_unused_imports = sum(len(r["unused_imports"]) for r in unused_imports)

    # Estimate cleanup savings
    estimated_lines = len(dead_functions) * 10 + total_unused_imports

    return {
        "dead_functions": dead_functions,
        "orphaned_files": orphaned_files,
        "zombie_deps": zombie_deps,
        "unused_imports": unused_imports,
        "summary": {
            "dead_function_count": len(dead_functions),
            "orphaned_file_count": len(orphaned_files),
            "zombie_dep_count": len(zombie_deps),
            "unused_import_count": total_unused_imports,
            "estimated_cleanup_lines": estimated_lines,
        },
        "directory": str(directory),
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_archaeology_report(results):
    """Format a full archaeology report for terminal display.

    Args:
        results: Result from run_full_archaeology()

    Returns:
        List of lines to print
    """
    lines = []
    lines.append("")
    lines.append("  ═══ CODE ARCHAEOLOGY REPORT ═══")
    lines.append("")

    summary = results["summary"]

    # Dead functions
    dead = results["dead_functions"]
    lines.append(f"  🦴 Dead Functions: {summary['dead_function_count']}")
    if dead:
        for defn in dead[:10]:
            lines.append(f"    - {defn['basename']}:{defn['function']}()  (L{defn['line']})")
        if len(dead) > 10:
            lines.append(f"    ... and {len(dead) - 10} more")
    else:
        lines.append("    None found ✅")
    lines.append("")

    # Orphaned files
    orphaned = results["orphaned_files"]
    lines.append(f"  📦 Orphaned Files: {summary['orphaned_file_count']}")
    if orphaned:
        for entry in orphaned[:10]:
            lines.append(f"    - {entry['basename']}  (0 references)")
        if len(orphaned) > 10:
            lines.append(f"    ... and {len(orphaned) - 10} more")
    else:
        lines.append("    None found ✅")
    lines.append("")

    # Zombie dependencies
    zombies = results["zombie_deps"]
    lines.append(f"  🧟 Zombie Dependencies: {summary['zombie_dep_count']}")
    if zombies:
        for dep in zombies[:10]:
            lines.append(f"    - {dep['package']}  (in {dep['source']}, never imported)")
        if len(zombies) > 10:
            lines.append(f"    ... and {len(zombies) - 10} more")
    else:
        lines.append("    None found ✅")
    lines.append("")

    # Unused imports
    imports = results["unused_imports"]
    lines.append(f"  📎 Unused Imports: {summary['unused_import_count']}")
    if imports:
        for file_result in imports[:10]:
            fname = file_result["basename"]
            for imp in file_result["unused_imports"][:3]:
                lines.append(f"    - {fname}:L{imp['line']} — {imp['import_name']}")
            remaining = len(file_result["unused_imports"]) - 3
            if remaining > 0:
                lines.append(f"      ... and {remaining} more in {fname}")
        if len(imports) > 10:
            lines.append(f"    ... and {len(imports) - 10} more files")
    else:
        lines.append("    None found ✅")
    lines.append("")

    # Summary
    estimated = summary["estimated_cleanup_lines"]
    if estimated > 0:
        lines.append(f"  Estimated cleanup: ~{estimated} lines removable")
    lines.append("")

    lines.append("  Sub-commands:")
    lines.append("    /archaeology imports  — Unused imports only")
    lines.append("    /archaeology deps     — Zombie dependencies only")
    lines.append("    /archaeology clean    — Interactive cleanup (with confirmation)")
    lines.append("")

    return lines


def format_imports_report(import_results):
    """Format unused imports report.

    Args:
        import_results: List from scan_unused_imports()

    Returns:
        List of lines to print
    """
    lines = []
    lines.append("")
    lines.append("  ═══ UNUSED IMPORTS ═══")
    lines.append("")

    if not import_results:
        lines.append("  No unused imports found ✅")
        lines.append("")
        return lines

    total = sum(len(r["unused_imports"]) for r in import_results)
    lines.append(f"  Found {total} unused import(s) across {len(import_results)} file(s):")
    lines.append("")

    for file_result in import_results:
        fname = file_result["basename"]
        lines.append(f"  📄 {fname}")
        for imp in file_result["unused_imports"]:
            lines.append(f"    L{imp['line']:>4}: {imp['full_line']}")
        lines.append("")

    return lines


def format_deps_report(zombie_deps):
    """Format zombie dependencies report.

    Args:
        zombie_deps: List from find_zombie_dependencies()

    Returns:
        List of lines to print
    """
    lines = []
    lines.append("")
    lines.append("  ═══ ZOMBIE DEPENDENCIES ═══")
    lines.append("")

    if not zombie_deps:
        lines.append("  No zombie dependencies found ✅")
        lines.append("")
        return lines

    lines.append(f"  Found {len(zombie_deps)} package(s) declared but never imported:")
    lines.append("")

    for dep in zombie_deps:
        lines.append(f"    🧟 {dep['package']:<30} (in {dep['source']})")
    lines.append("")
    lines.append("  Note: Some packages may be used indirectly (plugins, CLI tools).")
    lines.append("  Review before removing.")
    lines.append("")

    return lines


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _walk_source_files(directory, extensions):
    """Walk a directory tree yielding source files, skipping junk dirs."""
    skip_dirs = {
        ".git", "__pycache__", "node_modules", ".venv", "venv",
        ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
        ".egg-info", "eggs", ".eggs",
    }

    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in skip_dirs
                   and not d.endswith(".egg-info")]

        for filename in files:
            filepath = Path(root) / filename
            if filepath.suffix.lower() in extensions:
                yield filepath
