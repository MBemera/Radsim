"""Search tools for RadSim (glob and grep)."""

import fnmatch
import re
import shutil
import subprocess
from pathlib import Path

from .constants import MAX_SEARCH_RESULTS
from .validation import validate_path

SKIP_EXTENSIONS = frozenset(
    {
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bin",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".7z",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".webp",
        ".svg",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".pyc",
        ".pyo",
        ".class",
    }
)
MAX_SEARCH_SIZE = 500_000
RG_MAX_FILE_SIZE = "500K"


def _is_hidden_path(path):
    """Return True when a path contains a hidden segment."""
    return any(part.startswith(".") for part in path.parts)


def _iter_searchable_files(base_path, file_pattern=None):
    """Yield searchable files under a base path."""
    for file_path in base_path.rglob("*"):
        if not file_path.is_file():
            continue

        try:
            relative_path = file_path.relative_to(base_path)
        except ValueError:
            relative_path = file_path

        if _is_hidden_path(relative_path):
            continue

        if file_pattern and not fnmatch.fnmatch(file_path.name, file_pattern):
            continue

        if file_path.suffix.lower() in SKIP_EXTENSIONS:
            continue

        try:
            file_size = file_path.stat().st_size
        except OSError:
            continue

        if file_size > MAX_SEARCH_SIZE:
            continue

        yield file_path


def _normalize_relative_path(file_path):
    """Render a search result path relative to the current working directory when possible."""
    try:
        return str(file_path.relative_to(Path.cwd()))
    except ValueError:
        return str(file_path)


def glob_files(pattern, directory_path="."):
    """Find files matching a glob pattern."""
    is_safe, path, error = validate_path(directory_path)
    if not is_safe:
        return {"success": False, "error": error}

    if not path.is_dir():
        return {"success": False, "error": f"Not a directory: {directory_path}"}

    try:
        matches = []

        for match in path.glob(pattern):
            try:
                relative_path = match.relative_to(path)
            except ValueError:
                relative_path = match

            if _is_hidden_path(relative_path):
                continue

            matches.append(str(relative_path))
            if len(matches) >= MAX_SEARCH_RESULTS:
                break

        return {
            "success": True,
            "pattern": pattern,
            "matches": sorted(matches),
            "count": len(matches),
        }
    except Exception as error:
        return {"success": False, "error": str(error)}


def _build_grep_output(pattern, matches, files_searched, output_mode):
    """Convert raw grep matches into the requested response shape."""
    if output_mode == "files_only":
        file_paths = sorted({match["file"] for match in matches})
        return {
            "success": True,
            "pattern": pattern,
            "matches": file_paths,
            "count": len(file_paths),
            "files_searched": files_searched,
        }

    if output_mode == "count":
        counts = {}
        for match in matches:
            counts[match["file"]] = counts.get(match["file"], 0) + 1
        return {
            "success": True,
            "pattern": pattern,
            "matches": counts,
            "count": len(matches),
            "files_searched": files_searched,
        }

    return {
        "success": True,
        "pattern": pattern,
        "matches": matches,
        "count": len(matches),
        "files_searched": files_searched,
    }


def _grep_with_python(path, regex, file_pattern, context_lines):
    """Python fallback for grep search."""
    matches = []
    files_searched = 0

    for file_path in _iter_searchable_files(path, file_pattern):
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        lines = content.split("\n")
        files_searched += 1

        for line_num, line in enumerate(lines, 1):
            if not regex.search(line):
                continue

            match_info = {
                "file": _normalize_relative_path(file_path),
                "line": line_num,
                "content": line.strip()[:200],
            }

            if context_lines > 0:
                start = max(0, line_num - context_lines - 1)
                end = min(len(lines), line_num + context_lines)
                match_info["context"] = lines[start:end]

            matches.append(match_info)

            if len(matches) >= MAX_SEARCH_RESULTS:
                return matches, files_searched

    return matches, files_searched


def _build_rg_command(pattern, file_pattern, ignore_case):
    """Build a ripgrep command for the fast path."""
    command = [
        "rg",
        "--line-number",
        "--no-heading",
        "--color",
        "never",
        "--max-count",
        str(MAX_SEARCH_RESULTS),
        "--max-filesize",
        RG_MAX_FILE_SIZE,
    ]

    if ignore_case:
        command.append("--ignore-case")

    if file_pattern:
        command.extend(["--glob", file_pattern])

    for extension in sorted(SKIP_EXTENSIONS):
        command.extend(["--glob", f"!**/*{extension}"])

    command.extend([pattern, "."])
    return command


def _grep_with_ripgrep(pattern, path, file_pattern, ignore_case):
    """Run grep search through ripgrep when available."""
    command = _build_rg_command(pattern, file_pattern, ignore_case)
    result = subprocess.run(
        command,
        cwd=str(path),
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode not in {0, 1}:
        error_text = result.stderr.strip() or result.stdout.strip()
        if "regex" in error_text.lower():
            return None, None, {"success": False, "error": f"Invalid regex: {error_text}"}
        return None, None, None

    matches = []
    files_searched = set()

    for line in result.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue

        file_name, line_number, content = parts
        relative_file = file_name[2:] if file_name.startswith("./") else file_name

        matches.append(
            {
                "file": relative_file,
                "line": int(line_number),
                "content": content.strip()[:200],
            }
        )
        files_searched.add(relative_file)

    return matches, len(files_searched), None


def grep_search(
    pattern,
    directory_path=".",
    file_pattern=None,
    ignore_case=False,
    context_lines=0,
    output_mode="content",
):
    """Search file contents with regex."""
    is_safe, path, error = validate_path(directory_path)
    if not is_safe:
        return {"success": False, "error": error}

    try:
        regex_flags = re.IGNORECASE if ignore_case else 0
        regex = re.compile(pattern, regex_flags)
    except re.error as error:
        return {"success": False, "error": f"Invalid regex: {error}"}

    matches = None
    files_searched = None

    if context_lines == 0 and shutil.which("rg"):
        matches, files_searched, error_result = _grep_with_ripgrep(
            pattern,
            path,
            file_pattern,
            ignore_case,
        )
        if error_result:
            return error_result

    if matches is None:
        matches, files_searched = _grep_with_python(path, regex, file_pattern, context_lines)

    return _build_grep_output(pattern, matches, files_searched, output_mode)


def search_files(pattern, directory_path=".", case_sensitive=False):
    """Simple text search that returns matching files."""
    result = grep_search(
        re.escape(pattern),
        directory_path,
        ignore_case=not case_sensitive,
        output_mode="files_only",
    )
    if not result["success"]:
        return result

    return {"success": True, "matches": result["matches"], "count": result["count"]}
