"""Terminal output formatting for RadSim Agent."""

import re
import shutil
import sys
import time
from collections.abc import Iterable, Sequence

from .commands_metadata import DEFAULT_COMMAND_SPECS, build_help_details
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


def print_block(lines: Iterable[str], *, blank_before: bool = True, blank_after: bool = True) -> None:
    """Print a group of already-formatted lines with optional surrounding space."""
    if blank_before:
        print()
    for line in lines:
        print(line)
    if blank_after:
        print()


def print_titled_block(title: str, lines: Iterable[str], *, footer: Iterable[str] = ()) -> None:
    """Print a standard command section without changing its line content."""
    footer_lines = tuple(footer)
    footer_block = ("", *footer_lines) if footer_lines else ()
    print_block((f"  ═══ {title} ═══", "", *lines, *footer_block))


def print_labeled_values(rows: Iterable[tuple[str, object]], *, label_width: int) -> None:
    """Print aligned label/value rows used by command summaries."""
    lines = (f"  {label:<{label_width}}{value}" for label, value in rows)
    print_block(lines)


def print_numbered_options(
    title: str, options: Iterable[str | Sequence[str]], *, introduction: Iterable[str] = (),
    blank_between: bool = False,
) -> None:
    """Print numbered options while leaving input and validation to the caller."""
    lines = [f"  {title}", *introduction, ""]
    for index, option in enumerate(options, 1):
        option_lines = (option,) if isinstance(option, str) else option
        if not option_lines:
            continue
        lines.extend((f"    {index}. {option_lines[0]}", *(f"       {line}" for line in option_lines[1:])))
        if blank_between:
            lines.append("")
    print_block(lines, blank_after=not blank_between)


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
    from .pricing import estimate_usage_cost

    columns, _ = shutil.get_terminal_size()

    total_tokens = input_tokens + output_tokens

    # Unknown pricing must show as unknown — never as "Free"
    pricing = get_model_pricing(model)
    if pricing is None:
        cost_str = " | cost n/a"
    else:
        estimate = estimate_usage_cost(
            {"input_tokens": input_tokens, "output_tokens": output_tokens},
            pricing,
        )
        total_cost = estimate.total_usd
        if total_cost is None:
            cost_str = " | cost n/a"
        else:
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

HELP_DETAILS = build_help_details(DEFAULT_COMMAND_SPECS)

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
