"""Terminal output formatting for RadSim Agent."""

import sys
import time
from importlib.metadata import version as get_version

from .ui import (
    Spinner,
    print_error,
    print_hint,
    print_info,
    print_prompt,
    print_success,
    print_teach,
    print_typewriter,
    print_warning,
    show_error_panel,
    show_success_panel,
)

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

# Spinner style definitions
SPINNER_STYLES = {
    "dots": ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
    "braille": ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"],
    "moon": ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"],
    "arrows": ["←", "↖", "↑", "↗", "→", "↘", "↓", "↙"],
}

# RadSim ASCII Logo (Option B - Blocky)
RADSIM_LOGO_LINES = [
    "  ██████   █████  ██████  ███████ ██ ███    ███",
    "  ██   ██ ██   ██ ██   ██ ██      ██ ████  ████",
    "  ██████  ███████ ██   ██ ███████ ██ ██ ████ ██",
    "  ██   ██ ██   ██ ██   ██      ██ ██ ██  ██  ██",
    "  ██   ██ ██   ██ ██████  ███████ ██ ██      ██",
]

RADSIM_TAGLINE = "Radically Simple Code"


def supports_color():
    """Check if terminal supports colors."""
    if not hasattr(sys.stdout, "isatty"):
        return False
    if not sys.stdout.isatty():
        return False
    return True


def colorize(text, color):
    """Apply color to text if supported."""
    if not supports_color():
        return text
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


def print_boot_sequence(provider, model, animated=True):
    """Print the RadSim boot-up sequence with logo and animation."""
    if not supports_color():
        animated = False

    # Clear some space
    print()

    if animated:
        # Animated logo reveal (line by line)
        for line in RADSIM_LOGO_LINES:
            print(colorize(line, "bright_cyan"))
            time.sleep(0.06)
    else:
        for line in RADSIM_LOGO_LINES:
            print(colorize(line, "bright_cyan"))

    # Tagline with style
    print()
    tagline_styled = f"  ⚡ {RADSIM_TAGLINE} ⚡"
    print(colorize(tagline_styled, "cyan"))

    # Animated loading bar
    if animated:
        print()
        loading_width = 40
        sys.stdout.write("  ")
        sys.stdout.write(colorize("[", "dim"))
        for _ in range(loading_width):
            sys.stdout.write(colorize("█", "bright_cyan"))
            sys.stdout.flush()
            time.sleep(0.015)
        sys.stdout.write(colorize("]", "dim"))
        sys.stdout.write(colorize(" Ready!\n", "green"))

    # System info box
    print()
    box_width = 47
    inner_width = box_width - 4  # Account for "  │" and "│"

    print(colorize("  ┌" + "─" * (box_width - 2) + "┐", "dim"))

    # Provider line
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
    version_val = get_version("radsim")
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

    # Quick tips
    print(colorize("  Type your request or use commands:", "dim"))
    if animated:
        sys.stdout.write("    ")
        sys.stdout.flush()
        print_typewriter("/help", delay=0.03, style="cyan", end="")
        print(colorize(" - Show all commands", "dim"))
        sys.stdout.write("    ")
        sys.stdout.flush()
        print_typewriter("/tools", delay=0.03, style="cyan", end="")
        print(colorize(" - List available tools (35 total)", "dim"))
        sys.stdout.write("    ")
        sys.stdout.flush()
        print_typewriter("/exit", delay=0.03, style="cyan", end="")
        print(colorize(" - Quit RadSim", "dim"))
    else:
        print(colorize("    /help", "cyan") + colorize(" - Show all commands", "dim"))
        print(colorize("    /tools", "cyan") + colorize(" - List available tools (35 total)", "dim"))
        print(colorize("    /exit", "cyan") + colorize(" - Quit RadSim", "dim"))
    print()


def print_header(provider, model):
    """Print the RadSim header (legacy, calls boot sequence)."""
    print_boot_sequence(provider, model, animated=True)


def print_status_bar(model, input_tokens, output_tokens):
    """Print a status bar with model info, token usage, and cost estimate."""
    if not supports_color():
        return

    import shutil

    from .config import MODEL_PRICING

    columns, _ = shutil.get_terminal_size()

    total_tokens = input_tokens + output_tokens

    # Calculate cost estimate
    pricing = MODEL_PRICING.get(model, (0.0, 0.0))
    input_cost = (input_tokens / 1_000_000) * pricing[0]
    output_cost = (output_tokens / 1_000_000) * pricing[1]
    total_cost = input_cost + output_cost

    # Format cost string
    if total_cost > 0:
        cost_str = f" | ~${total_cost:.4f}"
    else:
        cost_str = " | Free"

    status = f" {model} | Tokens: {total_tokens:,} (In: {input_tokens:,} / Out: {output_tokens:,}){cost_str} "

    # Right align
    padding = columns - len(status) - 2
    if padding < 0:
        padding = 0

    print()
    print(" " * padding + colorize(status, "dim"))
    print()




def print_code(code, language=None):
    """Print code with basic formatting."""
    print()
    if language:
        print(colorize(f"```{language}", "dim"))
    print(code)
    if language:
        print(colorize("```", "dim"))
    print()

class ThinkingIndicator(Spinner):
    """Animated thinking indicator (alias for Spinner)."""
    pass

def print_thinking():
    """Print thinking indicator (legacy)."""
    pass

def clear_thinking():
    """Clear the thinking indicator (legacy)."""
    pass


# Teach comment prefix pattern for inline teaching annotations
# Matches: # 🎓, // 🎓, -- 🎓, /* 🎓 */, <!-- 🎓 -->
TEACH_COMMENT_PREFIXES = ("# 🎓", "// 🎓", "-- 🎓")
TEACH_COMMENT_WRAPPED = ("/* 🎓", "<!-- 🎓")


def is_teach_comment(line):
    """Check if a line is a teaching comment.

    Returns True for lines that are inline teaching annotations
    (prefixed with # 🎓, // 🎓, etc.)
    """
    stripped = line.strip()
    if any(stripped.startswith(prefix) for prefix in TEACH_COMMENT_PREFIXES):
        return True
    if any(stripped.startswith(prefix) for prefix in TEACH_COMMENT_WRAPPED):
        return True
    return False


def strip_teach_comments(content):
    """Remove all teaching comment lines from code content.

    Strips lines prefixed with # 🎓, // 🎓, etc. so the file
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


# Buffer for accumulating partial lines during streaming
_stream_line_buffer = ""


def print_stream_chunk(text):
    """Print a chunk of streamed text with teach mode magenta styling.

    Buffers partial lines so teach comment lines (containing 🎓) can be
    detected and colorized in bright_magenta as complete lines arrive.
    """
    global _stream_line_buffer

    # Check if teach mode is active (cached per-chunk for performance)
    teach_active = False
    try:
        from .modes import is_mode_active

        teach_active = is_mode_active("teach")
    except Exception:
        pass

    if not teach_active or not supports_color():
        sys.stdout.write(text)
        sys.stdout.flush()
        return

    # Buffer text and process complete lines with magenta styling
    _stream_line_buffer += text
    while "\n" in _stream_line_buffer:
        line, _stream_line_buffer = _stream_line_buffer.split("\n", 1)
        if is_teach_comment(line):
            sys.stdout.write(colorize(line, "bright_magenta") + "\n")
        else:
            sys.stdout.write(line + "\n")

    # Flush any remaining partial line (not yet a complete line)
    # Check if it starts with a teach prefix to style it early
    if _stream_line_buffer:
        if is_teach_comment(_stream_line_buffer):
            sys.stdout.write(colorize(_stream_line_buffer, "bright_magenta"))
        else:
            sys.stdout.write(_stream_line_buffer)
        _stream_line_buffer = ""

    sys.stdout.flush()


def reset_stream_state():
    """Reset the streaming state (call at start of new response)."""
    global _stream_line_buffer
    _stream_line_buffer = ""


def style_teach_content(text):
    """Style inline teach comments in text for display.

    Highlights lines containing 🎓 in magenta.
    """
    if "🎓" not in text:
        return text

    lines = text.split("\n")
    styled_lines = []
    for line in lines:
        if is_teach_comment(line):
            styled_lines.append(colorize(line, "bright_magenta"))
        else:
            styled_lines.append(line)
    return "\n".join(styled_lines)


def print_agent_response(text):
    """Print the agent's response with styled teach content."""
    print()
    styled_text = style_teach_content(text)
    print(styled_text)
    print()


# ============================================================================
# CLAUDE CODE INSPIRED TRANSPARENT OUTPUT
# ============================================================================


def print_tool_call(tool_name, tool_input, style="full", show_code=False):
    """Print a tool call in Claude Code style - transparent, visible.

    Args:
        tool_name: Name of the tool being called
        tool_input: Dictionary of tool parameters
        style: 'full' shows all params, 'compact' shows summary
        show_code: If True and tool is write_file, show the code content
    """
    # Tool icon mapping
    icons = {
        "read_file": "📄",
        "write_file": "✏️",
        "replace_in_file": "🔄",
        "run_shell_command": "⚡",
        "list_directory": "📁",
        "glob_files": "🔍",
        "grep_search": "🔎",
        "git_status": "📊",
        "git_commit": "💾",
        "git_add": "➕",
        "web_fetch": "🌐",
        "run_tests": "🧪",
        "browser_open": "🌍",
    }
    icon = icons.get(tool_name, "🔧")

    print()
    print(colorize(f"  ┌─ {icon} ", "dim") + colorize(tool_name, "bright_cyan"))

    # Show intent if present (chain-of-thought for destructive tools)
    intent = tool_input.get("_intent") if tool_input else None
    if intent:
        print(colorize("  │  intent: ", "dim") + colorize(str(intent), "yellow"))

    # For write_file, show file path prominently and optionally show code
    if tool_name == "write_file" and tool_input:
        file_path = tool_input.get("file_path", "")
        content = tool_input.get("content", "")
        line_count = len(content.split("\n")) if content else 0

        print(colorize("  │  path: ", "dim") + colorize(file_path, "white"))
        print(colorize("  │  lines: ", "dim") + colorize(str(line_count), "white"))
        print(colorize("  └─", "dim"))

        # Store for /show command
        if content:
            set_last_written_file(file_path, content)

        # Show code content if requested (e.g., in Teach Mode)
        if show_code and content:
            print()
            print_code_content(content, file_path, max_lines=40, collapsed=False)

    elif style == "full" and tool_input:
        for key, value in tool_input.items():
            if key.startswith("_"):
                continue
            # Truncate long values
            val_str = str(value)
            if len(val_str) > 60:
                val_str = val_str[:57] + "..."
            print(colorize(f"  │  {key}: ", "dim") + colorize(val_str, "white"))
        print(colorize("  └─", "dim"))

    elif style == "compact" and tool_input:
        # Show just the main parameter
        main_keys = ["file_path", "command", "url", "pattern", "directory_path"]
        for key in main_keys:
            if key in tool_input:
                val_str = str(tool_input[key])
                if len(val_str) > 50:
                    val_str = val_str[:47] + "..."
                print(colorize("  │  ", "dim") + colorize(val_str, "white"))
                break
        print(colorize("  └─", "dim"))

    else:
        print(colorize("  └─", "dim"))


def print_tool_result_verbose(tool_name, result, duration_ms=None):
    """Print tool result using rich Status Panels."""
    success = result.get("success", False)

    # Duration string
    duration_str = ""
    if duration_ms is not None:
        if duration_ms < 1000:
            duration_str = f"{duration_ms:.0f}ms"
        else:
            duration_str = f"{duration_ms / 1000:.1f}s"

    # Result summary based on tool
    message = ""
    if tool_name == "read_file":
        lines = result.get("line_count", 0)
        message = f"Read {lines} lines"
    elif tool_name == "write_file":
        message = "File written"
    elif tool_name == "run_shell_command":
        code = result.get("returncode", 0)
        if success:
            message = f"Exit code: {code}"
        else:
            message = f"Failed (exit {code})"
    elif tool_name == "list_directory":
        count = result.get("count", 0)
        message = f"Found {count} items"
    elif tool_name == "glob_files":
        count = result.get("count", 0)
        message = f"Matched {count} files"
    elif tool_name == "grep_search":
        count = result.get("count", 0)
        files = result.get("files_searched", 0)
        message = f"{count} matches in {files} files"
    else:
        if success:
            message = "Done"
        else:
            message = result.get("error", "Unknown error")[:100]

    title = f"{tool_name} Result"
    content = f"[primary]{message}[/primary]"
    if duration_str:
        content += f"\n[muted]Duration: {duration_str}[/muted]"

    if success:
        show_success_panel(title, content)
    else:
        show_error_panel(title, content)


def print_shell_output(stdout, stderr=None, max_lines=20):
    """Print shell command output in a visible panel.

    Args:
        stdout: Standard output string
        stderr: Standard error string (optional)
        max_lines: Maximum lines to show before truncating
    """
    if not stdout and not stderr:
        return

    print(colorize("  ┌─ Output ─────────────────────────────────────", "dim"))

    if stdout:
        lines = stdout.strip().split("\n")
        shown_lines = lines[:max_lines]
        for line in shown_lines:
            # Truncate very long lines
            if len(line) > 80:
                line = line[:77] + "..."
            print(colorize("  │ ", "dim") + line)

        if len(lines) > max_lines:
            remaining = len(lines) - max_lines
            print(colorize(f"  │ ... ({remaining} more lines)", "dim"))

    if stderr:
        print(colorize("  │", "dim"))
        print(colorize("  │ stderr:", "yellow"))
        lines = stderr.strip().split("\n")[:5]
        for line in lines:
            if len(line) > 80:
                line = line[:77] + "..."
            print(colorize("  │ ", "dim") + colorize(line, "yellow"))

    print(colorize("  └──────────────────────────────────────────────", "dim"))


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
        header = colorize(f"  ┌─ 📝 {file_path} ", "dim") + colorize(
            f"({total_lines} lines)", "dim"
        )
        if highlight_teach:
            header += colorize("  🎓 teaching annotations shown in magenta", "bright_magenta")
        print(header)
    else:
        print(colorize("  ┌─ Code Content ", "dim") + colorize(f"({total_lines} lines)", "dim"))

    def format_line(line_number, line_text):
        """Format a single line with line number, optionally highlighting teach comments."""
        line_num_str = colorize(f"  │ {line_number:4d} │ ", "dim")
        # Wider limit for teach annotations (educational prose needs more room)
        max_width = 120 if (highlight_teach and is_teach_comment(line_text)) else 80
        if len(line_text) > max_width:
            line_text = line_text[: max_width - 3] + "..."
        if highlight_teach and is_teach_comment(line_text):
            return line_num_str + colorize(line_text, "bright_magenta")
        return line_num_str + line_text

    if collapsed and total_lines > 10:
        for i, line in enumerate(lines[:5], 1):
            print(format_line(i, line))

        print(colorize("  │  ... │ ", "dim") + colorize(f"({total_lines - 8} more lines)", "gray"))

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


def print_thinking_step(step_text):
    """Print a thinking/reasoning step.

    Args:
        step_text: Description of what the agent is thinking/doing
    """
    print(colorize(f"  → {step_text}", "dim"))


def print_section_header(title):
    """Print a section header for organizing output.

    Args:
        title: Section title
    """
    width = 50
    padding = width - len(title) - 4
    print()
    print(colorize(f"  ── {title} ", "bright_cyan") + colorize("─" * padding, "dim"))


def print_file_change(file_path, change_type="modified"):
    """Print a file change notification.

    Args:
        file_path: Path to the file
        change_type: One of 'created', 'modified', 'deleted'
    """
    icons = {
        "created": ("✚", "green"),
        "modified": ("●", "yellow"),
        "deleted": ("✖", "red"),
    }
    icon, color = icons.get(change_type, ("●", "cyan"))
    print(colorize(f"  {icon} ", color) + colorize(file_path, "white"))


def print_command_hints(context: str, hints: list = None):
    """Print relevant command hints for a context.

    Args:
        context: What situation we're in (e.g., 'model', 'error', 'slow')
        hints: Optional list of (command, description) tuples
    """
    if hints is None:
        # Default hints by context
        hint_map = {
            "model": [
                ("/switch", "Quick switch model"),
                ("/config", "Full configuration"),
                ("/free", "Use free model"),
            ],
            "error": [
                ("/clear", "Clear and retry"),
                ("/new", "Fresh start"),
                ("/improve", "Mark for improvement"),
            ],
            "slow": [
                ("/switch", "Try faster model"),
                ("/free", "Use free model"),
            ],
            "success": [
                ("/good", "Mark as good"),
                ("/skill add", "Save as preference"),
            ],
            "start": [
                ("/help", "Get help"),
                ("/skill", "Configure skills"),
                ("/commands", "All commands"),
            ],
        }
        hints = hint_map.get(context, [])

    if not hints:
        return

    print()
    print(colorize("  Available commands:", "dim"))
    for cmd, desc in hints:
        print(colorize(f"    {cmd:<14}", "cyan") + colorize(desc, "dim"))
    print()


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
        "related": ["/commands", "/tools", "/modes"],
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
        "title": "Free Model",
        "aliases": [],
        "summary": "Instantly switch to the cheapest OpenRouter model.",
        "usage": ["/free"],
        "details": (
            "Switches to Kimi K2.5 on OpenRouter ($0.14/$0.28 per 1M tokens).\n"
            "Requires an OPENROUTER_API_KEY in your .env file."
        ),
        "examples": ["/free"],
        "related": ["/switch", "/config"],
        "tips": ["Great for quick tasks where you don't need a top-tier model."],
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
        "related": ["/preferences", "/settings"],
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
        "related": ["/skill", "/preferences"],
    },
    "teach": {
        "title": "Teach Me Mode",
        "aliases": ["/t"],
        "summary": "Toggle teach mode — adds explanations to every response.",
        "usage": ["/teach", "/t"],
        "details": (
            "When teach mode is ON, RadSim adds 🎓 inline annotations explaining\n"
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
        "related": ["/improve", "/stats", "/preferences"],
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
        "related": ["/good", "/stats", "/preferences"],
    },
    "stats": {
        "title": "Learning Statistics",
        "aliases": [],
        "summary": "Show a summary of learning statistics.",
        "usage": ["/stats"],
        "details": (
            "Displays key learning metrics: tasks completed, success rate,\n"
            "errors tracked, feedback received, examples stored, and tools tracked."
        ),
        "examples": ["/stats"],
        "related": ["/report", "/audit", "/preferences"],
    },
    "report": {
        "title": "Learning Report",
        "aliases": [],
        "summary": "Export a detailed learning report.",
        "usage": ["/report"],
        "details": "Generates and prints a full-text learning report with all tracked data.",
        "examples": ["/report"],
        "related": ["/stats", "/audit"],
    },
    "audit": {
        "title": "Preference Audit",
        "aliases": [],
        "summary": "Audit all learned preferences.",
        "usage": ["/audit"],
        "details": (
            "Shows every preference RadSim has learned, with current values.\n"
            "Use /reset preferences to clear them."
        ),
        "examples": ["/audit"],
        "related": ["/preferences", "/stats", "/reset"],
    },
    "preferences": {
        "title": "Learned Preferences",
        "aliases": ["/prefs"],
        "summary": "Show current learned code style and behavior preferences.",
        "usage": ["/preferences", "/prefs"],
        "details": (
            "Displays learned preferences like indentation, naming convention,\n"
            "comment style, type hint usage, verbosity, and preferred tools."
        ),
        "examples": ["/preferences", "/prefs"],
        "related": ["/audit", "/stats", "/skill"],
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
        "related": ["/stats", "/preferences"],
    },
    "clear": {
        "title": "Clear Conversation",
        "aliases": ["/c"],
        "summary": "Clear the current conversation history.",
        "usage": ["/clear", "/c"],
        "details": (
            "Clears all messages in the current conversation. Does NOT reset\n"
            "learned preferences, skills, or token budgets — use /new for that."
        ),
        "examples": ["/clear", "/c"],
        "related": ["/new", "/reset"],
    },
    "new": {
        "title": "Fresh Start",
        "aliases": ["/fresh"],
        "summary": "Start a completely new conversation with fresh context.",
        "usage": ["/new", "/fresh"],
        "details": (
            "Clears conversation history AND resets rate limiters and budget\n"
            "counters. Use this for a clean slate when starting a new project."
        ),
        "examples": ["/new", "/fresh"],
        "related": ["/clear", "/reset"],
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
        "related": ["/commands", "/help"],
    },
    "commands": {
        "title": "All Commands",
        "aliases": ["/cmds"],
        "summary": "List every available slash command with descriptions.",
        "usage": ["/commands", "/cmds"],
        "details": (
            "Shows the full categorized list of every slash command. More\n"
            "comprehensive than /help, which shows only the most common ones."
        ),
        "examples": ["/commands", "/cmds"],
        "related": ["/help", "/tools"],
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
    print()
    print(colorize("  ╭─────────────────────────────────────────────╮", "dim"))
    header_text = f"  /{topic}"
    if alias_str:
        header_text += f"  ({alias_str})"
    padded = header_text.ljust(46)
    print(colorize("  │", "dim") + colorize(padded[2:], "bold") + colorize("│", "dim"))
    print(
        colorize("  │", "dim")
        + colorize(f"  {title}".ljust(44), "bright_cyan")
        + colorize("│", "dim")
    )
    print(colorize("  ╰─────────────────────────────────────────────╯", "dim"))
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
            print(colorize(f"    💡 {tip}", "dim"))
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

    # Default: show the overview menu
    print()
    print(colorize("  ╭─────────────────────────────────────────────╮", "dim"))
    print(
        colorize("  │", "dim")
        + colorize("           RadSim Help Menu", "bold")
        + colorize("                │", "dim")
    )
    print(colorize("  ╰─────────────────────────────────────────────╯", "dim"))
    print()

    print(colorize("  Essential Commands:", "bright_cyan"))
    print(colorize("    /help      ", "cyan") + colorize("Show this help", "dim"))
    print(colorize("    /commands  ", "cyan") + colorize("List ALL available commands", "dim"))
    print(colorize("    /tools     ", "cyan") + colorize("List all 35 available tools", "dim"))
    print()

    print(colorize("  Model & Provider:", "bright_cyan"))
    print(colorize("    /switch    ", "cyan") + colorize("Quick switch provider/model", "dim"))
    print(colorize("    /config    ", "cyan") + colorize("Full configuration setup", "dim"))
    print(colorize("    /free      ", "cyan") + colorize("Switch to free model", "dim"))
    print()

    print(colorize("  Customization:", "bright_cyan"))
    print(colorize("    /skill add ", "cyan") + colorize("Add custom instruction", "dim"))
    print(colorize("    /skill list", "cyan") + colorize("Show active skills", "dim"))
    print(colorize("    /prefs     ", "cyan") + colorize("Show learned preferences", "dim"))
    print()

    print(colorize("  Feedback:", "bright_cyan"))
    print(colorize("    /good, /+  ", "cyan") + colorize("Mark response as good", "dim"))
    print(colorize("    /improve,/-", "cyan") + colorize("Mark for improvement", "dim"))
    print(colorize("    /stats     ", "cyan") + colorize("Learning statistics", "dim"))
    print()

    print(colorize("  Code Analysis:", "bright_cyan"))
    print(colorize("    /complexity", "cyan") + colorize("Complexity budget & scoring", "dim"))
    print(colorize("    /stress    ", "cyan") + colorize("Adversarial code review", "dim"))
    print(colorize("    /archaeology", "cyan") + colorize("Find dead code & zombies", "dim"))
    print()

    print(colorize("  Session:", "bright_cyan"))
    print(colorize("    /clear     ", "cyan") + colorize("Clear conversation", "dim"))
    print(colorize("    /new       ", "cyan") + colorize("Fresh start + reset limits", "dim"))
    print(colorize("    /exit      ", "cyan") + colorize("Quit RadSim", "dim"))
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
