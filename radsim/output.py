"""Terminal output formatting for RadSim Agent."""

import re
import shutil
import sys
import time

from .terminal import colorize_ansi, supports_color
from .theme import glyph, load_active_animation_level
from .ui import (
    Spinner,  # noqa: F401 — re-exported for use by agent.py, commands.py, cli.py
    print_error,  # noqa: F401 — re-exported for use by agent.py, commands.py, cli.py
    print_info,  # noqa: F401 — re-exported
    print_prompt,  # noqa: F401 — re-exported
    print_success,  # noqa: F401 — re-exported
    print_warning,  # noqa: F401 — re-exported
    tool_event,
)
from .version import get_radsim_version

# ANSI color codes
COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "italic": "\033[3m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",
    "bright_cyan": "\033[96m",
    "bright_blue": "\033[94m",
    "bright_magenta": "\033[95m",
    "bg_cyan": "\033[46m",
    "bg_red": "\033[41m",
    "bg_green": "\033[42m",
    "gray": "\033[90m",
}

# RadSim ASCII Logo (cube-block style — matches the RadSim brand artwork)
RADSIM_LOGO_LINES = [
    "  ██████   █████  ██████  ███████ ██ ███    ███",
    "  ██   ██ ██   ██ ██   ██ ██      ██ ████  ████",
    "  ██████  ███████ ██   ██ ███████ ██ ██ ████ ██",
    "  ██   ██ ██   ██ ██   ██      ██ ██ ██  ██  ██",
    "  ██   ██ ██   ██ ██████  ███████ ██ ██      ██",
]

# Logo lines are 47 columns wide (2-space lead + 45 visible cols).
LOGO_WIDTH = 47

# Robot mascot frames. The body is centered over the logo, with an ASCII
# lightning bolt zig-zagging out of the upper right of the head and connecting
# to the body. Each frame is exactly 5 lines so we can overdraw in place.
RADSIM_ROBOT_FRAMES = [
    [
        "                      ╭───╮╱",
        "                      │◉ ◉│╱",
        "                      ╰─┬─╯╲",
        "                     ┌──┴──┐╲",
        "                     └─────┘╱",
    ],
    [
        "                      ╭───╮╱",
        "                      │‾ ‾│╱",
        "                      ╰─┬─╯╲",
        "                     ┌──┴──┐╲",
        "                     └─────┘╱",
    ],
    [
        "                      ╭───╮ ",
        "                      │◉ ◉│ ",
        "                      ╰─┬─╯ ",
        "                     ┌──┴──┐ ",
        "                     └─────┘ ",
    ],
    [
        "                      ╭───╮╱",
        "                      │◉ ◉│╱",
        "                      ╰─┬─╯╲",
        "                     ┌──┴──┐╲",
        "                     └─────┘╱",
    ],
]

ROBOT_HEIGHT = len(RADSIM_ROBOT_FRAMES[0])

RADSIM_TAGLINE = "── radically simple coding agent ──"


def colorize(text, color):
    """Apply color to text if supported."""
    return colorize_ansi(text, color, COLORS, supports_color_fn=supports_color)


def _center_line(text, width=LOGO_WIDTH):
    """Center a visible string within the given column width."""
    padding = max(0, (width - len(text)) // 2)
    return " " * padding + text


def _print_robot_frame(frame):
    """Render a single mascot frame in bright cyan."""
    for line in frame:
        sys.stdout.write("\r\033[2K")
        sys.stdout.write(colorize(line, "bright_cyan") + "\n")
    sys.stdout.flush()


def _animate_robot_drop(frame):
    """Print the mascot one line at a time so it appears to drop in."""
    for line in frame:
        print(colorize(line, "bright_cyan"))
        sys.stdout.flush()
        time.sleep(0.06)


def _animate_robot_loop(frames, cycles=3, frame_delay=0.18):
    """Cycle through mascot frames in place to keep it engaging."""
    for _ in range(cycles):
        for frame in frames[1:]:
            sys.stdout.write(f"\033[{ROBOT_HEIGHT}A")
            _print_robot_frame(frame)
            time.sleep(frame_delay)
        sys.stdout.write(f"\033[{ROBOT_HEIGHT}A")
        _print_robot_frame(frames[0])
        time.sleep(frame_delay)


def _print_logo_solid(logo_lines):
    """Print the RadSim logo as a single solid block (no sweep)."""
    for line in logo_lines:
        print(colorize(line, "bright_cyan"))
    sys.stdout.flush()


def _animate_tagline(tagline):
    """Type the tagline in character by character, centered under the logo."""
    leading = " " * max(0, (LOGO_WIDTH - len(tagline)) // 2)
    sys.stdout.write(leading)
    for ch in tagline:
        sys.stdout.write(colorize(ch, "cyan"))
        sys.stdout.flush()
        time.sleep(0.015)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _disabled_confirmation_labels():
    """Return short labels for confirmation prompts the user switched off.

    Display-only helper; any config error reads as everything enabled.
    """
    try:
        from .agent_config import get_agent_config_manager

        manager = get_agent_config_manager()
        labels = []
        if not manager.confirmation_enabled("shell_commands"):
            labels.append("shell commands")
        if not manager.confirmation_enabled("file_deletion"):
            labels.append("file deletion")
        return labels
    except Exception:
        return []


def print_boot_sequence(provider, model, animated=True):
    """Print the RadSim boot-up sequence with logo and animation."""
    animation_level = load_active_animation_level()
    animated = animated and animation_level == "full"

    print()

    if animated:
        _animate_robot_drop(RADSIM_ROBOT_FRAMES[0])
        _animate_robot_loop(RADSIM_ROBOT_FRAMES, cycles=2)
        _print_logo_solid(RADSIM_LOGO_LINES)
        print()
        _animate_tagline(RADSIM_TAGLINE)
    else:
        for line in RADSIM_ROBOT_FRAMES[0]:
            print(colorize(line, "bright_cyan"))
        for line in RADSIM_LOGO_LINES:
            print(colorize(line, "bright_cyan"))
        print()
        print(colorize(_center_line(RADSIM_TAGLINE), "cyan"))

    print()
    box_width = 47
    inner_width = box_width - 4

    print(colorize("  ┌" + "─" * (box_width - 2) + "┐", "dim"))

    provider_val = provider.upper()
    provider_padding = inner_width - 10 - len(provider_val)
    print(
        colorize("  │", "dim")
        + "  Provider: "
        + colorize(provider_val, "bright_cyan")
        + " " * provider_padding
        + colorize("│", "dim")
    )

    # Model line
    model_display = model[:28] + ".." if len(model) > 30 else model
    model_padding = inner_width - 10 - len(model_display)
    print(
        colorize("  │", "dim")
        + "  Model:    "
        + colorize(model_display, "cyan")
        + " " * model_padding
        + colorize("│", "dim")
    )

    # Version line
    version_val = get_radsim_version()
    version_padding = inner_width - 10 - len(version_val)
    print(
        colorize("  │", "dim")
        + "  Version:  "
        + colorize(version_val, "dim")
        + " " * version_padding
        + colorize("│", "dim")
    )

    print(colorize("  └" + "─" * (box_width - 2) + "┘", "dim"))
    print()

    disabled_confirmations = _disabled_confirmation_labels()
    if disabled_confirmations:
        summary = ", ".join(disabled_confirmations)
        print(colorize(f"  [!] Confirmation OFF for: {summary} — runs without prompts", "red"))
        print(colorize("      Restore with: /settings security_level balanced", "dim"))
        print()

    print(colorize("  Type your request or use commands:", "dim"))
    print(colorize("    /help", "cyan") + colorize(" - Show all commands", "dim"))
    print(
        colorize("    /tools", "cyan")
        + colorize(f" - List available tools ({_count_tools()} total)", "dim")
    )
    print(colorize("    /undo", "cyan") + colorize(" - Revert the last file change", "dim"))
    print(colorize("    !<cmd>", "cyan") + colorize(" - Run a shell command yourself", "dim"))
    print(colorize("    /exit", "cyan") + colorize(" - Quit RadSim", "dim"))
    print()


def _count_tools():
    """Return the live native tool count so help text never goes stale."""
    try:
        from .tools import TOOL_DEFINITIONS

        return len(TOOL_DEFINITIONS)
    except Exception:
        return "many"


def print_header(provider, model):
    """Print the RadSim header (legacy, calls boot sequence)."""
    print_boot_sequence(provider, model, animated=True)


def print_status_bar(model, input_tokens, output_tokens):
    """Print a status bar with model info, token usage, and cost estimate."""
    if not supports_color():
        return

    import shutil

    from .config import get_model_pricing

    columns, _ = shutil.get_terminal_size()

    total_tokens = input_tokens + output_tokens

    # Unknown pricing must show as unknown — never as "Free"
    pricing = get_model_pricing(model)
    if pricing is None:
        cost_str = " | cost n/a"
    else:
        input_cost = (input_tokens / 1_000_000) * pricing[0]
        output_cost = (output_tokens / 1_000_000) * pricing[1]
        total_cost = input_cost + output_cost
        cost_str = f" | ~${total_cost:.4f}" if total_cost > 0 else " | Free"

    status = f" {model} | Tokens: {total_tokens:,} (In: {input_tokens:,} / Out: {output_tokens:,}){cost_str} "

    # Right align
    padding = columns - len(status) - 2
    if padding < 0:
        padding = 0

    print()
    print(" " * padding + colorize(status, "dim"))
    print()


# Teach comment prefix pattern for inline teaching annotations
LEGACY_TEACH_MARKER = "\U0001F393"

# Accept both the current [teach] marker and the legacy graduation-cap marker.
TEACH_COMMENT_PREFIXES = (
    "# [teach]",
    f"# {LEGACY_TEACH_MARKER}",
    "// [teach]",
    f"// {LEGACY_TEACH_MARKER}",
    "-- [teach]",
    f"-- {LEGACY_TEACH_MARKER}",
)
TEACH_COMMENT_WRAPPED = (
    "/* [teach]",
    f"/* {LEGACY_TEACH_MARKER}",
    "<!-- [teach]",
    f"<!-- {LEGACY_TEACH_MARKER}",
)


def is_teach_comment(line):
    """Check if a line is a teaching comment.

    Returns True for lines that are inline teaching annotations
    (prefixed with # [teach], // [teach], etc.)
    """
    stripped = line.strip()
    if any(stripped.startswith(prefix) for prefix in TEACH_COMMENT_PREFIXES):
        return True
    if any(stripped.startswith(prefix) for prefix in TEACH_COMMENT_WRAPPED):
        return True
    return False


def strip_teach_comments(content):
    """Remove all teaching comment lines from code content.

    Strips lines prefixed with # [teach], // [teach], etc. so the file
    written to disk contains only clean code.

    Args:
        content: The code content with teaching comments

    Returns:
        Clean code with teaching lines removed
    """
    lines = content.split("\n")
    clean_lines = [line for line in lines if not is_teach_comment(line)]

    # Remove consecutive blank lines left by stripping
    result_lines = []
    previous_blank = False
    for line in clean_lines:
        is_blank = line.strip() == ""
        if is_blank and previous_blank:
            continue
        result_lines.append(line)
        previous_blank = is_blank

    return "\n".join(result_lines)


# Streaming state: partial-line buffer and whether we are inside a fence.
_stream_line_buffer = ""
_stream_in_code_block = False


def print_stream_chunk(text):
    """Stream agent text one completed line at a time.

    Lines are buffered until their newline arrives so markdown can be
    rendered terminal-friendly and teach comments colorized. The final
    partial line is flushed by finish_stream() when the response ends.
    """
    global _stream_line_buffer

    teach_active = _teach_mode_active()

    _stream_line_buffer += text
    while "\n" in _stream_line_buffer:
        line, _stream_line_buffer = _stream_line_buffer.split("\n", 1)
        sys.stdout.write(_style_stream_line(line, teach_active) + "\n")
    sys.stdout.flush()


def finish_stream():
    """Flush any partial final line and reset the streaming state."""
    global _stream_line_buffer, _stream_in_code_block

    if _stream_line_buffer:
        sys.stdout.write(_style_stream_line(_stream_line_buffer, _teach_mode_active()))
        sys.stdout.flush()
    _stream_line_buffer = ""
    _stream_in_code_block = False


def _style_stream_line(line, teach_active):
    """Render one streamed line, tracking code-fence state across lines."""
    global _stream_in_code_block

    if teach_active and is_teach_comment(line):
        return colorize(line, "bright_magenta")
    rendered, _stream_in_code_block = render_markdown_line(line, _stream_in_code_block)
    return rendered


def _teach_mode_active():
    """True when teach mode should colorize [teach] comment lines."""
    if not supports_color():
        return False
    try:
        from .modes import is_mode_active

        return is_mode_active("teach")
    except Exception:
        return False


def reset_stream_state():
    """Reset the streaming state (call at start of new response)."""
    global _stream_line_buffer, _stream_in_code_block
    _stream_line_buffer = ""
    _stream_in_code_block = False


def style_teach_content(text):
    """Style inline teach comments in text for display.

    Highlights lines containing [teach] in magenta.
    """
    if "[teach]" not in text and LEGACY_TEACH_MARKER not in text:
        return text

    lines = text.split("\n")
    styled_lines = []
    for line in lines:
        if is_teach_comment(line):
            styled_lines.append(colorize(line, "bright_magenta"))
        else:
            styled_lines.append(line)
    return "\n".join(styled_lines)


_MARKDOWN_HEADER = re.compile(r"^(#{1,6})\s+(.*)$")
_MARKDOWN_RULE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_MARKDOWN_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MARKDOWN_INLINE_CODE = re.compile(r"`([^`]+)`")
_MARKDOWN_TABLE_DIVIDER = re.compile(r"^\|[\s:|-]+\|$")


def render_markdown_line(line, in_code_block):
    """Convert one markdown line to terminal-friendly text.

    Fenced code blocks pass through untouched so real code stays exact and
    copy-pasteable. Outside them, markdown decoration becomes plain text:
    headers lose their hashes, rules disappear, bold and inline-code markers
    become terminal styling, and table rows flatten to spaced columns.

    Returns:
        Tuple of (rendered line, updated in_code_block state).
    """
    if line.lstrip().startswith("```"):
        return colorize(line, "dim"), not in_code_block
    if in_code_block:
        return line, True

    header = _MARKDOWN_HEADER.match(line)
    if header:
        return colorize(header.group(2), "bold"), False

    if _MARKDOWN_RULE.match(line):
        return "", False

    stripped = line.strip()
    if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 1:
        if _MARKDOWN_TABLE_DIVIDER.match(stripped):
            return "", False
        indent = line[: len(line) - len(line.lstrip())]
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        return _render_inline_markdown(indent + "  ".join(cells)), False

    return _render_inline_markdown(line), False


def _render_inline_markdown(line):
    """Convert bold and inline-code markers to terminal styling."""
    line = _MARKDOWN_BOLD.sub(lambda match: colorize(match.group(1), "bold"), line)
    return _MARKDOWN_INLINE_CODE.sub(lambda match: colorize(match.group(1), "cyan"), line)


def render_markdown_text(text):
    """Convert a full markdown response to terminal-friendly text."""
    in_code_block = False
    rendered = []
    for line in text.split("\n"):
        styled, in_code_block = render_markdown_line(line, in_code_block)
        rendered.append(styled)
    return "\n".join(rendered)


def print_agent_response(text):
    """Print the agent's response as terminal-friendly text."""
    print()
    rendered = render_markdown_text(text)
    print(style_teach_content(rendered))
    print()


def _truncate_text(value, max_width):
    text = str(value).strip()
    if not text:
        return ""
    if len(text) <= max_width:
        return text
    ellipsis = glyph("ellipsis")
    trim_width = max(max_width - len(ellipsis), 0)
    return f"{text[:trim_width]}{ellipsis}"


def _format_duration(ms):
    if ms is None:
        return ""
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"


def _summarize_argument(tool_name, tool_input):
    if not isinstance(tool_input, dict):
        return _truncate_text(tool_input or "-", 50)

    if tool_name in {"read_file", "write_file", "replace_in_file", "delete_file"}:
        summary = tool_input.get("file_path", "-")
    elif tool_name == "read_many_files":
        count = len(tool_input.get("file_paths", []))
        summary = f"{count} files"
    elif tool_name == "rename_file":
        old_path = tool_input.get("old_path", "")
        new_path = tool_input.get("new_path", "")
        summary = f"{old_path} -> {new_path}"
    elif tool_name == "run_shell_command":
        summary = tool_input.get("command", "-")
    elif tool_name in {"list_directory", "create_directory"}:
        summary = tool_input.get("directory_path", ".")
    elif tool_name == "glob_files":
        summary = tool_input.get("pattern", "-")
    elif tool_name in {"grep_search", "search_files"}:
        pattern = tool_input.get("pattern", "")
        directory = tool_input.get("directory_path", ".")
        summary = f'"{pattern}" in {directory}'
    elif tool_name in {"run_tests", "lint_code", "format_code", "type_check"}:
        summary = (
            tool_input.get("test_command")
            or tool_input.get("test_path")
            or tool_input.get("file_path")
            or "project"
        )
    elif tool_name.startswith("git_"):
        summary = (
            tool_input.get("branch")
            or tool_input.get("file_path")
            or tool_input.get("message")
            or "git"
        )
    elif tool_name == "web_fetch":
        summary = tool_input.get("url", "-")
    elif tool_name.startswith("browser_"):
        summary = (
            tool_input.get("url")
            or tool_input.get("selector")
            or tool_input.get("path")
            or "browser"
        )
    elif tool_name in {"multi_edit", "batch_replace"}:
        summary = tool_input.get("file_path") or tool_input.get("file_pattern") or "edit"
    else:
        visible_items = [
            f"{key}={value}"
            for key, value in tool_input.items()
            if not str(key).startswith("_")
        ]
        summary = visible_items[0] if visible_items else "-"

    terminal_width = shutil.get_terminal_size((80, 24)).columns
    max_width = max(20, terminal_width - 30)
    return _truncate_text(summary, max_width)


def _result_summary(tool_name, result):
    success = result.get("success", False)

    if not success:
        return f"exit {result['returncode']}" if "returncode" in result else "error"

    if tool_name == "read_file":
        return f"{result.get('line_count', 0)} lines"
    if tool_name == "read_many_files":
        return f"{result.get('count', 0)} files"
    if tool_name == "write_file":
        added_lines = result.get("added_lines")
        removed_lines = result.get("removed_lines")
        if added_lines is not None and removed_lines is not None:
            return f"{glyph('diff_add')}{added_lines} {glyph('diff_del')}{removed_lines}"
        return "file written"
    if tool_name == "replace_in_file":
        added_lines = result.get("added_lines")
        removed_lines = result.get("removed_lines")
        if added_lines is not None and removed_lines is not None:
            return f"{glyph('diff_add')}{added_lines} {glyph('diff_del')}{removed_lines}"
        return f"{result.get('replacements_made', 0)} changes"
    if tool_name == "run_shell_command":
        return f"exit {result.get('returncode', 0)}"
    if tool_name == "list_directory":
        return f"{result.get('count', 0)} items"
    if tool_name == "glob_files":
        return f"{result.get('count', 0)} files"
    if tool_name in {"grep_search", "search_files"}:
        return f"{result.get('count', 0)} matches"
    if tool_name == "run_tests":
        return f"exit {result.get('returncode', 0)}"
    if tool_name == "git_add":
        return f"{len(result.get('staged_files', []))} staged"
    if tool_name == "git_commit":
        commit_hash = result.get("commit_hash", "")[:7]
        return commit_hash or "committed"
    if tool_name == "rename_file":
        return "renamed"
    if tool_name == "delete_file":
        return "deleted"
    if tool_name == "create_directory":
        return "created"
    if tool_name == "web_fetch":
        return "fetched"
    return "ok"


def _truncate_at_word(value, max_width):
    """Truncate on a word boundary so cut-off text stays readable."""
    text = str(value).strip()
    if len(text) <= max_width:
        return text
    ellipsis = glyph("ellipsis")
    cut = text[: max(max_width - len(ellipsis), 0)]
    head, _, _ = cut.rpartition(" ")
    return f"{head or cut}{ellipsis}"


def _extract_error_text(result):
    """Return up to three error lines — failures deserve full detail."""
    error_text = result.get("error") or result.get("stderr") or ""
    if not error_text:
        return None
    lines = [line.strip() for line in error_text.strip().splitlines() if line.strip()]
    shown = [_truncate_at_word(line, 300) for line in lines[:3]]
    if len(lines) > 3:
        shown.append(f"({len(lines) - 3} more lines)")
    return "\n".join(shown)


def print_tool_call(tool_name, tool_input, style="full", show_code=False):
    """Create a single-line tool event handle."""
    handle = tool_event(tool_name, _summarize_argument(tool_name, tool_input))

    if tool_name == "write_file" and isinstance(tool_input, dict):
        file_path = tool_input.get("file_path", "")
        content = tool_input.get("content", "")
        if content:
            set_last_written_file(file_path, content)
        if show_code and content:
            print()
            print_code_content(content, file_path, max_lines=40, collapsed=False)

    return handle


def print_tool_result_verbose(handle, tool_name, result, duration_ms=None):
    """Render the final tool result on the tool event line."""
    handle.finish(
        result.get("success", False),
        _result_summary(tool_name, result),
        duration_ms,
        error=_extract_error_text(result),
    )


def print_shell_output(stdout, stderr=None, max_lines=3):
    """Print shell command output as a plain indented block."""
    output_lines = []

    if stdout:
        output_lines.extend(stdout.strip().splitlines())

    if stderr:
        for line in stderr.strip().splitlines():
            output_lines.append(f"stderr: {line}")

    output_lines = [line for line in output_lines if line.strip()]
    if not output_lines:
        return

    shown_lines = output_lines[:max_lines]
    for line in shown_lines:
        print(f"    {_truncate_text(line, 120)}")

    remaining = len(output_lines) - len(shown_lines)
    if remaining > 0:
        print(f"    {glyph('ellipsis')}({remaining} more lines)")


# Track last written file for /show command
_last_written_file = {"path": None, "content": None, "display_content": None}

# Session file history for Ctrl+O / show all
_session_files: list[dict] = []


def set_last_written_file(path: str, content: str, display_content: str = None):
    """Store the last written file for /show command.

    Args:
        path: File path that was written
        content: Clean content (stripped of teach comments) written to disk
        display_content: Optional content with teach comments preserved for display
    """
    global _last_written_file
    _last_written_file = {
        "path": path,
        "content": content,
        "display_content": display_content,
    }
    # Also add to session history
    add_session_file(path, content, display_content)


def get_last_written_file():
    """Get the last written file info."""
    return _last_written_file


def add_session_file(path: str, content: str, display_content: str = None):
    """Add a file to the session history.

    Avoids duplicates by updating existing entries for the same path.
    """
    for entry in _session_files:
        if entry["path"] == path:
            entry["content"] = content
            entry["display_content"] = display_content
            return
    _session_files.append(
        {
            "path": path,
            "content": content,
            "display_content": display_content,
        }
    )


def get_all_session_files():
    """Get all files written during this session."""
    return list(_session_files)


def clear_session_files():
    """Clear session file history (called on /new)."""
    global _session_files, _last_written_file
    _session_files = []
    _last_written_file = {"path": None, "content": None, "display_content": None}


def print_all_session_code():
    """Display all files written during the session with teach annotations highlighted."""
    files = get_all_session_files()
    if not files:
        print()
        print("  No files have been written this session.")
        print()
        return

    print()
    print(colorize(f"  ═══ SESSION FILES ({len(files)} files) ═══", "bright_cyan"))
    print()

    for entry in files:
        # Prefer display_content (with teach annotations) over clean content
        content = entry.get("display_content") or entry.get("content", "")
        print_code_content(
            content,
            entry["path"],
            max_lines=0,  # 0 = show all lines
            collapsed=False,
            highlight_teach=True,
        )
        print()


def print_code_content(
    content: str,
    file_path: str = None,
    max_lines: int = 30,
    collapsed: bool = False,
    highlight_teach: bool = False,
):
    """Display code content with line numbers in a nice format.

    Args:
        content: The code content to display
        file_path: Optional file path for header
        max_lines: Maximum lines to show before truncating
        collapsed: If True, show only first/last few lines
        highlight_teach: If True, highlight teaching comment lines in magenta
    """
    if not content:
        return

    lines = content.split("\n")
    total_lines = len(lines)

    # Header
    if file_path:
        header = colorize(f"  ┌─ {file_path} ", "dim") + colorize(f"({total_lines} lines)", "dim")
        if highlight_teach:
            header += colorize("  [teach] annotations shown in magenta", "bright_magenta")
        print(header)
    else:
        print(colorize("  ┌─ Code Content ", "dim") + colorize(f"({total_lines} lines)", "dim"))

    def format_line(line_number, line_text):
        """Format a single line with line number, optionally highlighting teach comments."""
        line_num_str = colorize(f"  │ {line_number:4d} │ ", "dim")
        # Wider limit for teach annotations (educational prose needs more room)
        max_width = 120 if (highlight_teach and is_teach_comment(line_text)) else 80
        if len(line_text) > max_width:
            line_text = _truncate_text(line_text, max_width)
        if highlight_teach and is_teach_comment(line_text):
            return line_num_str + colorize(line_text, "bright_magenta")
        return line_num_str + line_text

    if collapsed and total_lines > 10:
        for i, line in enumerate(lines[:5], 1):
            print(format_line(i, line))

        print(
            colorize("  │  ... │ ", "dim")
            + colorize(f"({total_lines - 8} more lines)", "gray")
        )

        for i, line in enumerate(lines[-3:], total_lines - 2):
            print(format_line(i, line))
    elif max_lines and max_lines > 0:
        show_lines = lines[:max_lines]
        for i, line in enumerate(show_lines, 1):
            print(format_line(i, line))

        if total_lines > max_lines:
            remaining = total_lines - max_lines
            print(
                colorize("  │  ... │ ", "dim")
                + colorize(f"({remaining} more lines - type S to see all)", "gray")
            )
    else:
        # max_lines=0 or None means show ALL lines
        for i, line in enumerate(lines, 1):
            print(format_line(i, line))

    print(colorize("  └──────────────────────────────────────────────", "dim"))


# ============================================================================
# DETAILED HELP CONTENT
# ============================================================================

HELP_DETAILS = {
    "help": {
        "title": "Help Menu",
        "aliases": ["/h", "/?"],
        "summary": "Show the help menu or detailed help for a specific command.",
        "usage": ["/help", "/help <command>"],
        "details": (
            "Displays the main help menu with categorized commands.\n"
            "Pass a command name to get detailed help, usage examples, and tips."
        ),
        "examples": ["/help", "/help skill", "/help plan", "/h complexity"],
        "related": ["/tools", "/modes"],
        "tips": ["You can also ask naturally, e.g. 'how do I use skills?'"],
    },
    "switch": {
        "title": "Quick Switch Provider/Model",
        "aliases": ["/model"],
        "summary": "Interactively switch your AI provider and model.",
        "usage": ["/switch"],
        "details": (
            "Opens an interactive menu to select a new provider (Claude, GPT-5,\n"
            "Gemini, Vertex AI, OpenRouter) and then pick a model. Requires an\n"
            "API key already configured in your .env file."
        ),
        "examples": ["/switch", "/model"],
        "related": ["/config", "/free"],
        "tips": ["Use /free to instantly switch to the cheapest model."],
    },
    "config": {
        "title": "Provider Configuration",
        "aliases": ["/provider", "/swap"],
        "summary": "Full configuration setup for provider and API key.",
        "usage": ["/config"],
        "details": (
            "Re-runs the configuration wizard where you can change your AI\n"
            "provider and enter a new API key. This is the full setup flow —\n"
            "use /switch for a quicker model change."
        ),
        "examples": ["/config"],
        "related": ["/switch", "/setup", "/free"],
    },
    "free": {
        "title": "Cheapest Model",
        "aliases": [],
        "summary": "Instantly switch to the cheapest OpenRouter model.",
        "usage": ["/free"],
        "details": (
            "Switches to DeepSeek V4 Flash on OpenRouter ($0.09/$0.18 per 1M tokens).\n"
            "Requires an OPENROUTER_API_KEY in your .env file."
        ),
        "examples": ["/free"],
        "related": ["/switch", "/config"],
        "tips": ["Great for quick tasks where you don't need a top-tier model."],
    },
    "login": {
        "title": "Provider Login",
        "aliases": [],
        "summary": "Log in to a provider with an API key.",
        "usage": ["/login", "/login <provider>"],
        "details": (
            "Configures API credentials from inside RadSim:\n\n"
            "  • (no args)    — Pick a provider from a numbered menu\n"
            "  • <provider>   — Run the API-key wizard for that provider\n\n"
            "After login, RadSim hot-swaps to the newly configured provider."
        ),
        "examples": ["/login", "/login openrouter", "/login claude"],
        "related": ["/logout", "/config", "/switch"],
    },
    "logout": {
        "title": "Provider Logout",
        "aliases": [],
        "summary": "Remove a provider's saved API key and cached tokens.",
        "usage": ["/logout", "/logout <provider>"],
        "details": (
            "Removes the stored API key (and any cached OAuth tokens) for a\n"
            "provider. Pick from a menu or name the provider directly."
        ),
        "examples": ["/logout", "/logout openai"],
        "related": ["/login", "/config"],
    },
    "theme": {
        "title": "Color Theme",
        "aliases": ["/palette"],
        "summary": "Pick the UI color palette.",
        "usage": ["/theme", "/theme <name>"],
        "details": (
            "Changes RadSim's terminal color palette. Run without arguments\n"
            "for an interactive picker, or pass a palette name directly.\n"
            "The choice is saved in ~/.radsim/settings.json."
        ),
        "examples": ["/theme", "/palette"],
        "related": ["/font", "/animations"],
    },
    "font": {
        "title": "Font / Glyph Profile",
        "aliases": ["/glyphs"],
        "summary": "Pick the glyph profile (Nerd Font, Unicode, ASCII).",
        "usage": ["/font", "/font <profile>"],
        "details": (
            "Selects which glyph set RadSim uses for icons and symbols.\n"
            "Pick ASCII if your terminal font shows broken characters."
        ),
        "examples": ["/font", "/glyphs"],
        "related": ["/theme", "/animations"],
    },
    "animations": {
        "title": "Animation Level",
        "aliases": ["/anim"],
        "summary": "Set the animation level (full, subtle, off).",
        "usage": ["/animations", "/animations <level>"],
        "details": (
            "Controls spinners and boot animations:\n\n"
            "  • full   — Animated spinners and boot sequence\n"
            "  • subtle — Static indicators, no motion\n"
            "  • off    — Plain text only"
        ),
        "examples": ["/animations", "/anim off"],
        "related": ["/theme", "/font"],
    },
    "trust": {
        "title": "Confirmation Trust",
        "aliases": [],
        "summary": "View or reset learned confirmation trust.",
        "usage": ["/trust", "/trust reset [tool]", "/trust low", "/trust medium"],
        "details": (
            "RadSim learns which safe actions you routinely approve and can\n"
            "auto-confirm them (trust bandit). This command shows what has\n"
            "been learned, adjusts the trust threshold, or resets it."
        ),
        "examples": ["/trust", "/trust reset", "/trust reset write_file"],
        "related": ["/settings", "/stats"],
    },
    "background": {
        "title": "Background Jobs",
        "aliases": ["/bg"],
        "summary": "View and manage background sub-agent jobs.",
        "usage": ["/background", "/bg", "/bg<N>"],
        "details": (
            "Lists background sub-agent jobs with status and runtime.\n"
            "Use /bg<N> (e.g. /bg2) to view the result of job N.\n"
            "Job results are also injected into the conversation when done."
        ),
        "examples": ["/background", "/bg1"],
        "related": ["/job"],
    },
    "job": {
        "title": "Scheduled Jobs",
        "aliases": ["/jobs", "/cron"],
        "summary": "Manage scheduled cron jobs.",
        "usage": [
            "/job",
            "/job add",
            "/job remove   (pick from a list)",
            "/job pause    (pick from a list)",
            "/job resume   (pick from a list)",
            "/job run      (pick from a list)",
        ],
        "details": (
            "Schedules recurring commands (cron-style). Every action works\n"
            "without an id — you get a picker of your jobs:\n\n"
            "  • (no args)   — List all scheduled jobs\n"
            "  • add         — Create a new scheduled job\n"
            "  • remove      — Delete a job\n"
            "  • pause/resume— Toggle a job without deleting it\n"
            "  • run         — Run a job immediately\n\n"
            "Jobs the agent schedules for you (via the schedule_task tool)\n"
            "show up here too — they share one store."
        ),
        "examples": ["/job", "/job add", "/job run"],
        "related": ["/background", "/telegram"],
    },
    "ratelimit": {
        "title": "Rate Limit Settings",
        "aliases": ["/rl", "/limit"],
        "summary": "Set API call limit per turn to control agent throughput.",
        "usage": ["/ratelimit"],
        "details": (
            "Choose how many API calls the agent can make per turn:\n"
            "  Light (15)     - Conservative, good for simple tasks\n"
            "  Standard (30)  - Balanced, recommended for most work\n"
            "  Heavy (75)     - For complex multi-step tasks\n"
            "  Intensive (100)- For large refactors and deep analysis\n"
            "  Maximum (200)  - Maximum throughput, use with caution\n\n"
            "Setting is saved and persists across sessions."
        ),
        "examples": ["/ratelimit", "/rl"],
        "related": ["/switch", "/config", "/settings"],
        "tips": ["Start with Standard and increase if you hit limits on complex tasks."],
    },
    "mcp": {
        "title": "MCP Server Connections",
        "aliases": [],
        "summary": "Manage MCP (Model Context Protocol) server connections.",
        "usage": ["/mcp", "/mcp status", "/mcp list", "/mcp add", "/mcp connect <name>",
                  "/mcp disconnect <name>", "/mcp remove <name>"],
        "details": (
            "Connect to external MCP servers to extend RadSim with additional tools.\n"
            "MCP is the same protocol used by Claude Desktop, Cursor, and other tools.\n\n"
            "Subcommands:\n"
            "  status     - Show all servers and connection state (default)\n"
            "  list       - Show all tools from connected servers\n"
            "  add        - Interactively add a new server\n"
            "  connect    - Connect to a configured server\n"
            "  disconnect - Disconnect from a server\n"
            "  remove     - Remove a server configuration\n\n"
            "Config file: ~/.radsim/mcp.json\n"
            "Supports: stdio, SSE, and Streamable HTTP transports.\n"
            "Install MCP SDK: pip install radsimcli[mcp]"
        ),
        "examples": ["/mcp", "/mcp add", "/mcp connect filesystem", "/mcp list"],
        "related": ["/tools", "/config"],
        "tips": [
            "MCP tools appear alongside native tools in /tools output.",
            "All MCP tools require confirmation unless auto_confirm is enabled.",
            "Set autoConnect: true in config to connect on startup.",
        ],
    },
    "usage": {
        "title": "Session Usage & Cost",
        "aliases": ["/cost"],
        "summary": "Show this session's token usage and estimated cost.",
        "usage": ["/usage"],
        "details": (
            "Displays input/output token totals for the current session and\n"
            "an estimated cost based on the active model's pricing. Models\n"
            "without pricing data show cost as n/a."
        ),
        "examples": ["/usage", "/cost"],
        "related": ["/stats", "/ratelimit"],
    },
    "copy": {
        "title": "Copy to Clipboard",
        "aliases": ["/cp"],
        "summary": "Copy the last response, code block, or written file.",
        "usage": ["/copy", "/copy code", "/copy file"],
        "details": (
            "Copies content to the system clipboard:\n"
            "  • /copy       — the last full response\n"
            "  • /copy code  — the last fenced code block in the response\n"
            "  • /copy file  — the content of the last written file"
        ),
        "examples": ["/copy code"],
        "related": ["/show", "/export"],
    },
    "export": {
        "title": "Export Conversation",
        "aliases": [],
        "summary": "Save the conversation as a markdown file.",
        "usage": ["/export", "/export <filename>"],
        "details": (
            "Writes the conversation to a markdown file in the project\n"
            "directory (default: a timestamped name). Tool calls are noted;\n"
            "tool results and images are omitted to keep the export readable.\n"
            "Existing files are never overwritten."
        ),
        "examples": ["/export", "/export review-session.md"],
        "related": ["/copy", "/clear"],
    },
    "undo": {
        "title": "Undo File Changes",
        "aliases": [],
        "summary": "Restore files to their state before the last agent edit.",
        "usage": ["/undo", "/undo list"],
        "details": (
            "Before the agent writes, edits, renames, patches, or deletes a\n"
            "file, RadSim snapshots it. /undo restores the most recent\n"
            "checkpoint: rewritten files get their old content back, and\n"
            "files that did not exist before are removed.\n\n"
            "Covers write_file, replace_in_file, delete_file, rename_file,\n"
            "multi_edit, and apply_patch. Keeps the last 20 checkpoints per\n"
            "project; files over 5 MB are recorded but not snapshotted."
        ),
        "examples": ["/undo", "/undo list"],
        "related": ["/show"],
        "tips": ["Run /undo repeatedly to step further back."],
    },
    "hook": {
        "title": "Lifecycle Hooks",
        "aliases": ["/hooks"],
        "summary": "Run your own shell commands on agent events.",
        "usage": [
            "/hook            (interactive menu)",
            "/hook list",
            "/hook add",
            "/hook toggle     (arrow-key on/off switches)",
            "/hook remove     (pick from a list)",
            "/hook add <name> <event> <matcher> <command...>",
        ],
        "details": (
            "Hooks run a shell command when an agent event fires. Events:\n"
            "pre_tool, post_tool, session_start, session_end, on_error.\n"
            "The matcher is a glob against the tool name (git_*, *, ...);\n"
            "session hooks always fire.\n\n"
            "Every action works without arguments: bare /hook opens a menu,\n"
            "and remove/on/off show a picker of your hooks.\n\n"
            "Each hook receives a JSON payload on stdin. A pre_tool hook\n"
            "that exits with code 2 BLOCKS the tool call and its stderr is\n"
            "shown as the reason. Hooks can only block actions — they can\n"
            "never approve, skip a confirmation, or bypass validation.\n"
            "A pre_tool hook that fails to run blocks the call (fail closed)."
        ),
        "examples": [
            "/hook add test-gate pre_tool git_push pytest -q",
            "/hook add lint-after post_tool write_file ruff check .",
            "/hook off lint-after",
        ],
        "related": ["/skill", "/settings"],
        "tips": [
            "Hooks are stored in ~/.radsim/hooks.json (max 20).",
            "The command is everything after the matcher — no quotes needed.",
        ],
    },
    "skill": {
        "title": "Custom Skills & Instructions",
        "aliases": ["/skills"],
        "summary": "Add, list, remove, or import custom instructions.",
        "usage": [
            "/skill",
            "/skill add <instruction>",
            "/skill list",
            "/skill remove <n>",
            "/skill templates",
            "/skill learn <file>",
            "/skill clear",
        ],
        "details": (
            "Skills are persistent custom instructions that shape how RadSim\n"
            "responds. They survive across conversations.\n\n"
            "  • add       — Add a new instruction (e.g. 'Always use TypeScript')\n"
            "  • list      — Show all active skills\n"
            "  • remove    — Remove a skill by number\n"
            "  • templates — Show example skills to get started\n"
            "  • learn     — Import skills from a file\n"
            "  • clear     — Remove all skills"
        ),
        "examples": [
            "/skill add Always use TypeScript instead of JavaScript",
            "/skill list",
            "/skill remove 2",
            "/skill templates",
        ],
        "related": ["/stats", "/settings"],
        "tips": [
            "Skills are stored in ~/.radsim/skills.json",
            "Use /skill templates for inspiration",
        ],
    },
    "memory": {
        "title": "Persistent Memory",
        "aliases": ["/mem"],
        "summary": "Save, recall, and manage persistent memory entries.",
        "usage": ["/memory", "/memory remember <text>", "/memory forget <n>", "/memory list"],
        "details": (
            "Memory lets RadSim remember facts across conversations.\n\n"
            "  • remember — Save a piece of information\n"
            "  • forget   — Remove a memory by number\n"
            "  • list     — Show all stored memories"
        ),
        "examples": [
            "/memory remember My project uses PostgreSQL 16",
            "/memory list",
            "/memory forget 3",
        ],
        "related": ["/skill", "/stats"],
    },
    "teach": {
        "title": "Teach Me Mode",
        "aliases": ["/t"],
        "summary": "Toggle teach mode — adds explanations to every response.",
        "usage": ["/teach", "/t"],
        "details": (
            "When teach mode is ON, RadSim adds [teach] inline annotations explaining\n"
            "what each piece of code does and why. Great for learning new\n"
            "languages, frameworks, or understanding unfamiliar codebases.\n\n"
            "Annotations appear in magenta and are automatically stripped\n"
            "from files written to disk."
        ),
        "examples": ["/teach", "/t"],
        "related": ["/modes", "/show"],
        "tips": [
            "Press T as a hotkey to toggle teach mode quickly",
            "Annotations are stripped from saved files automatically",
        ],
    },
    "plan": {
        "title": "Plan Mode",
        "aliases": ["/p"],
        "summary": "Structured plan → confirm → execute workflow.",
        "usage": ["/plan", "/plan <task description>"],
        "details": (
            "Plan mode breaks complex tasks into steps:\n\n"
            "  1. You describe the task\n"
            "  2. RadSim generates a structured plan\n"
            "  3. You review and approve (or edit)\n"
            "  4. RadSim executes the approved plan step by step\n\n"
            "This gives you full control over multi-step operations."
        ),
        "examples": [
            "/plan refactor the auth module to use JWT tokens",
            "/plan add dark mode to the settings page",
            "/p",
        ],
        "related": ["/panning", "/complexity"],
        "tips": ["Use /plan for tasks with multiple files or risky changes."],
    },
    "panning": {
        "title": "Brain-Dump Processing",
        "aliases": ["/pan"],
        "summary": "Process messy brain-dumps into structured synthesis.",
        "usage": ["/panning", "/panning <brain dump text>"],
        "details": (
            "Panning mode takes unstructured thoughts, ideas, or notes and\n"
            "synthesizes them into a structured, actionable output. Great for:\n\n"
            "  • Converting rough notes into a spec\n"
            "  • Organizing scattered requirements\n"
            "  • Turning brainstorms into action items"
        ),
        "examples": [
            "/panning I need auth, maybe OAuth, also user profiles, and...",
            "/pan",
        ],
        "related": ["/plan"],
    },
    "complexity": {
        "title": "Complexity Budget & Scoring",
        "aliases": ["/cx"],
        "summary": "Analyze and manage code complexity.",
        "usage": [
            "/complexity",
            "/complexity budget <N>",
            "/complexity analyze <file>",
            "/complexity report",
        ],
        "details": (
            "The complexity system scores code and enforces budgets:\n\n"
            "  • (no args) — Interactive menu\n"
            "  • budget N  — Set max complexity budget\n"
            "  • analyze   — Score a specific file\n"
            "  • report    — Full project complexity report"
        ),
        "examples": ["/complexity", "/cx budget 50", "/complexity analyze src/auth.py"],
        "related": ["/stress", "/archaeology"],
    },
    "stress": {
        "title": "Adversarial Code Review",
        "aliases": ["/adversarial"],
        "summary": "Run adversarial stress testing on your code.",
        "usage": ["/stress", "/stress <file>"],
        "details": (
            "Stress testing tries to break your code by finding edge cases,\n"
            "security vulnerabilities, performance issues, and logic errors.\n"
            "Can target a specific file or run on the whole project."
        ),
        "examples": ["/stress", "/stress src/api/routes.py"],
        "related": ["/complexity", "/archaeology"],
    },
    "archaeology": {
        "title": "Dead Code Archaeology",
        "aliases": ["/arch", "/dead"],
        "summary": "Find dead code, zombie functions, and unused imports.",
        "usage": ["/archaeology", "/archaeology clean"],
        "details": (
            "Scans your project for:\n\n"
            "  • Unused imports\n"
            "  • Dead functions never called\n"
            "  • Zombie code (commented out blocks)\n"
            "  • Unreachable code paths\n\n"
            "Use 'clean' for interactive cleanup."
        ),
        "examples": ["/archaeology", "/arch clean"],
        "related": ["/complexity", "/stress"],
    },
    "settings": {
        "title": "Agent Settings",
        "aliases": ["/set"],
        "summary": "View or change agent configuration parameters.",
        "usage": ["/settings", "/settings <key> <value>", "/settings security_level <level>"],
        "details": (
            "Manage RadSim's internal settings:\n\n"
            "  • (no args)          — Interactive menu\n"
            "  • <key>              — View a single setting\n"
            "  • <key> <value>      — Change a setting\n"
            "  • security_level     — Set preset (strict/balanced/permissive)"
        ),
        "examples": [
            "/settings",
            "/settings security_level strict",
            "/set self_improvement.enabled true",
        ],
        "related": ["/evolve", "/config"],
    },
    "evolve": {
        "title": "Self-Improvement Proposals",
        "aliases": ["/self-improve"],
        "summary": "Review, generate, and manage self-improvement proposals.",
        "usage": ["/evolve", "/evolve analyze", "/evolve history", "/evolve stats"],
        "details": (
            "RadSim can propose improvements to itself based on usage patterns:\n\n"
            "  • (no args) — Review pending proposals\n"
            "  • analyze   — Generate new proposals from learning data\n"
            "  • history   — View past approved/rejected proposals\n"
            "  • stats     — Improvement statistics"
        ),
        "examples": ["/evolve", "/evolve analyze", "/evolve stats"],
        "related": ["/settings", "/selfmod"],
        "tips": ["Enable with: /settings self_improvement.enabled true"],
    },
    "selfmod": {
        "title": "Self-Modification",
        "aliases": ["/self"],
        "summary": "View or edit RadSim source code and custom prompt.",
        "usage": ["/selfmod", "/selfmod path", "/selfmod prompt", "/selfmod list"],
        "details": (
            "Access RadSim's own source code:\n\n"
            "  • path   — Show the RadSim source directory\n"
            "  • prompt — View/edit the custom system prompt\n"
            "  • list   — List all source files"
        ),
        "examples": ["/selfmod path", "/selfmod prompt", "/self list"],
        "related": ["/evolve", "/settings"],
    },
    "telegram": {
        "title": "Telegram Notifications",
        "aliases": ["/tg"],
        "summary": "Configure Telegram bot for notifications and remote control.",
        "usage": [
            "/telegram",
            "/telegram setup",
            "/telegram listen",
            "/telegram test",
            "/telegram send <msg>",
            "/telegram status",
        ],
        "details": (
            "Connect RadSim to a Telegram bot for:\n\n"
            "  • setup   — Configure bot token and chat ID\n"
            "  • listen  — Toggle receiving messages from Telegram\n"
            "  • test    — Send a test message\n"
            "  • send    — Send a custom message\n"
            "  • status  — Check current configuration"
        ),
        "examples": ["/telegram setup", "/tg test", "/telegram send Task done!"],
        "related": ["/settings"],
    },
    "good": {
        "title": "Positive Feedback",
        "aliases": ["/+"],
        "summary": "Mark the last response as good (positive feedback).",
        "usage": ["/good", "/+"],
        "details": (
            "Records positive feedback on the last response. RadSim uses this\n"
            "to learn your preferences and improve future responses."
        ),
        "examples": ["/good", "/+"],
        "related": ["/improve", "/stats"],
    },
    "improve": {
        "title": "Improvement Feedback",
        "aliases": ["/-"],
        "summary": "Mark the last response for improvement (negative feedback).",
        "usage": ["/improve", "/-"],
        "details": (
            "Records that the last response could be better. RadSim uses this\n"
            "alongside positive feedback to learn what works and what doesn't."
        ),
        "examples": ["/improve", "/-"],
        "related": ["/good", "/stats"],
    },
    "stats": {
        "title": "Learning Statistics",
        "aliases": [],
        "summary": "Show learning statistics and deeper learning views.",
        "usage": ["/stats", "/stats report", "/stats audit", "/stats prefs", "/stats prompt"],
        "details": (
            "Bare /stats shows key learning metrics: tasks completed, success\n"
            "rate, errors tracked, feedback received, and tools tracked.\n\n"
            "Subactions:\n"
            "  report — export the full-text learning report\n"
            "  audit  — audit every learned preference\n"
            "  prefs  — show learned code style preferences\n"
            "  prompt — show system prompt size by layer"
        ),
        "examples": ["/stats", "/stats prefs", "/stats prompt"],
        "related": ["/reset", "/skill"],
    },
    "reset": {
        "title": "Reset Learning Data",
        "aliases": [],
        "summary": "Reset a category of learned data or the token budget.",
        "usage": ["/reset", "/reset <category>"],
        "details": (
            "Reset specific learning categories:\n\n"
            "  • budget       — Reset token budget counters\n"
            "  • preferences  — Reset learned code style\n"
            "  • errors       — Reset error patterns\n"
            "  • examples     — Reset few-shot examples\n"
            "  • tools        — Reset tool effectiveness data\n"
            "  • reflections  — Reset task reflections\n"
            "  • all          — Reset everything"
        ),
        "examples": ["/reset budget", "/reset preferences", "/reset all"],
        "related": ["/stats"],
    },
    "clear": {
        "title": "Clear Conversation",
        "aliases": ["/c", "/new", "/fresh"],
        "summary": "Clear the conversation and start fresh.",
        "usage": ["/clear", "/new"],
        "details": (
            "Clears conversation history, the task tracker, and background\n"
            "jobs, and resets rate limiters and budget counters. Learned\n"
            "preferences and skills are kept — use /reset for those."
        ),
        "examples": ["/clear", "/new"],
        "related": ["/reset"],
    },
    "tools": {
        "title": "Available Tools",
        "aliases": [],
        "summary": "List all available tools the agent can use.",
        "usage": ["/tools"],
        "details": (
            "Displays the full list of tools available to RadSim, including\n"
            "file operations, git, shell, search, testing, and more."
        ),
        "examples": ["/tools"],
        "related": ["/help"],
    },
    "show": {
        "title": "Show Last Written File",
        "aliases": [],
        "summary": "Display the content of the last file written by the agent.",
        "usage": ["/show", "/show all"],
        "details": (
            "Shows the last file RadSim wrote, with line numbers. In teach\n"
            "mode, annotations are highlighted in magenta.\n\n"
            "  • (no args) — Show last written file\n"
            "  • all       — Show all files written this session"
        ),
        "examples": ["/show", "/show all"],
        "related": ["/teach"],
        "tips": ["Press S during a write confirmation to preview code."],
    },
    "modes": {
        "title": "Available Modes",
        "aliases": [],
        "summary": "List all available mode toggles.",
        "usage": ["/modes"],
        "details": "Shows all modes (teach, awake, etc.) and their current on/off status.",
        "examples": ["/modes"],
        "related": ["/teach", "/awake"],
    },
    "awake": {
        "title": "Stay-Awake Mode",
        "aliases": ["/caffeinate"],
        "summary": "Toggle stay-awake mode (prevents macOS sleep).",
        "usage": ["/awake", "/caffeinate"],
        "details": (
            "Uses macOS 'caffeinate' to prevent the system from sleeping.\n"
            "Useful during long-running tasks. Toggle off when done."
        ),
        "examples": ["/awake", "/caffeinate"],
        "related": ["/modes"],
    },
    "exit": {
        "title": "Exit RadSim",
        "aliases": ["/quit", "/q"],
        "summary": "Quit RadSim gracefully.",
        "usage": ["/exit", "/quit", "/q"],
        "details": "Exits RadSim cleanly. You can also type 'exit' or 'quit' without the slash.",
        "examples": ["/exit", "/quit"],
        "related": ["/kill"],
    },
    "kill": {
        "title": "Emergency Stop",
        "aliases": ["/stop", "/abort"],
        "summary": "EMERGENCY: Immediately terminate the agent.",
        "usage": ["/kill", "/stop", "/abort"],
        "details": (
            "Force-kills RadSim immediately. Use when the agent is stuck or\n"
            "doing something unexpected. Prefer /exit for normal shutdown."
        ),
        "examples": ["/kill", "/stop"],
        "related": ["/exit"],
        "tips": ["Only use in emergencies — /exit is safer for normal use."],
    },
    "setup": {
        "title": "Setup Wizard",
        "aliases": ["/onboarding"],
        "summary": "Re-run the initial setup wizard.",
        "usage": ["/setup", "/onboarding"],
        "details": (
            "Runs the full onboarding flow again: provider selection, API key\n"
            "entry, and model selection."
        ),
        "examples": ["/setup"],
        "related": ["/config", "/switch"],
    },
}

# Build an alias-to-topic lookup for quick matching
_ALIAS_TO_TOPIC = {}
for _topic, _info in HELP_DETAILS.items():
    _ALIAS_TO_TOPIC[_topic] = _topic
    _ALIAS_TO_TOPIC[f"/{_topic}"] = _topic
    for _alias in _info.get("aliases", []):
        _ALIAS_TO_TOPIC[_alias.lstrip("/")] = _topic
        _ALIAS_TO_TOPIC[_alias] = _topic
del _topic, _info  # Clean up loop variables from module scope
try:
    del _alias
except NameError:
    pass


def _resolve_help_topic(raw_topic):
    """Resolve a raw topic string to a HELP_DETAILS key, or None."""
    if not raw_topic:
        return None
    normalized = raw_topic.strip().lower().lstrip("/")
    return _ALIAS_TO_TOPIC.get(normalized) or _ALIAS_TO_TOPIC.get(f"/{normalized}")


def print_help_detail(topic):
    """Print detailed help for a specific topic.

    Args:
        topic: A key in HELP_DETAILS
    """
    info = HELP_DETAILS.get(topic)
    if not info:
        return

    title = info["title"]
    aliases = info.get("aliases", [])
    alias_str = ", ".join(aliases) if aliases else ""

    # Header box
    inner_width = 45
    header_text = f"  /{topic}"
    if alias_str:
        header_text += f"  ({alias_str})"

    print()
    print(colorize("  ╭" + "─" * inner_width + "╮", "dim"))
    print(
        colorize("  │", "dim")
        + colorize(header_text[:inner_width].ljust(inner_width), "bold")
        + colorize("│", "dim")
    )
    print(
        colorize("  │", "dim")
        + colorize(f"  {title}"[:inner_width].ljust(inner_width), "bright_cyan")
        + colorize("│", "dim")
    )
    print(colorize("  ╰" + "─" * inner_width + "╯", "dim"))
    print()

    # Summary
    print(colorize("  Summary:", "bright_cyan"))
    print(f"    {info['summary']}")
    print()

    # Usage
    usage = info.get("usage", [])
    if usage:
        print(colorize("  Usage:", "bright_cyan"))
        for u in usage:
            print(colorize(f"    {u}", "cyan"))
        print()

    # Details
    details = info.get("details", "")
    if details:
        print(colorize("  Details:", "bright_cyan"))
        for line in details.split("\n"):
            print(f"    {line}")
        print()

    # Examples
    examples = info.get("examples", [])
    if examples:
        print(colorize("  Examples:", "bright_cyan"))
        for ex in examples:
            print(colorize("    $ ", "dim") + colorize(ex, "white"))
        print()

    # Tips
    tips = info.get("tips", [])
    if tips:
        print(colorize("  Tips:", "yellow"))
        for tip in tips:
            print(colorize(f"    Tip: {tip}", "dim"))
        print()

    # Related
    related = info.get("related", [])
    if related:
        related_str = "  ".join(colorize(r, "cyan") for r in related)
        print(colorize("  Related: ", "dim") + related_str)
        print()


def print_help(topic=None):
    """Print help information, optionally for a specific topic.

    Args:
        topic: Optional command name to show detailed help for.
              If None, shows the overview menu.
    """
    if topic:
        resolved = _resolve_help_topic(topic)
        if resolved:
            print_help_detail(resolved)
        else:
            # Topic not found — show suggestions
            print()
            print(colorize(f"  No help found for '{topic}'.", "yellow"))
            print()
            available = sorted(HELP_DETAILS.keys())
            cols = 5
            print(colorize("  Available topics:", "dim"))
            for i in range(0, len(available), cols):
                row = available[i : i + cols]
                row_str = "".join(colorize(f"/{t:<16}", "cyan") for t in row)
                print(f"    {row_str}")
            print()
            print(
                colorize("  Usage: ", "dim")
                + colorize("/help <topic>", "cyan")
                + colorize("  e.g. /help skill", "dim")
            )
            print()
        return

    # Default: overview generated from the command registry, so /help can
    # never drift out of sync with the commands that actually exist.
    from .commands_metadata import DEFAULT_COMMAND_SPECS

    title = "RadSim Help Menu"
    inner_width = 45
    left_pad = " " * ((inner_width - len(title)) // 2)
    right_pad = " " * (inner_width - len(title) - len(left_pad))

    print()
    print(colorize("  ╭" + "─" * inner_width + "╮", "dim"))
    print(
        colorize("  │", "dim")
        + left_pad
        + colorize(title, "bold")
        + right_pad
        + colorize("│", "dim")
    )
    print(colorize("  ╰" + "─" * inner_width + "╯", "dim"))
    print()
    print(colorize(f"  {len(DEFAULT_COMMAND_SPECS)} commands, {_count_tools()} tools", "dim"))
    print()

    by_category = {}
    for spec in DEFAULT_COMMAND_SPECS:
        by_category.setdefault(spec["category"], []).append(spec)

    for category, specs in by_category.items():
        print(colorize(f"  {category.title()}:", "bright_cyan"))
        for spec in specs:
            primary = spec["names"][0]
            aliases = " ".join(spec["names"][1:])
            line = colorize(f"    {primary:<13}", "cyan") + colorize(spec["description"], "dim")
            if aliases:
                line += colorize(f"  ({aliases})", "gray")
            print(line)
        print()

    print(
        colorize("  ! <command>  ", "cyan")
        + colorize("Run a shell command yourself — output is shared with the agent", "dim")
    )
    print()
    print(
        colorize("  Tip: ", "yellow")
        + colorize("/help <command> ", "cyan")
        + colorize("for detailed help (e.g. ", "dim")
        + colorize("/help skill", "cyan")
        + colorize(")", "dim")
    )
    print()


def print_diff(old_content, new_content, filename=None):
    """Display a unified diff with colors.

    Uses the diff_display module for rendering.

    Args:
        old_content: Original file content
        new_content: New file content
        filename: Optional filename to display in header

    Returns:
        The diff string (also printed to terminal)
    """
    from .diff_display import show_diff

    diff_output = show_diff(old_content, new_content, filename)
    if diff_output:
        print(diff_output)
    return diff_output
