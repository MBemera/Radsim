"""Terminal output formatting for RadSim Agent."""

import itertools
import sys
import threading
import time
from importlib.metadata import version as get_version

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


def print_prompt(active_modes: list = None):
    """Print the input prompt with optional mode indicators.

    Args:
        active_modes: List of active mode names to display
    """
    mode_prefix = ""
    if active_modes:
        mode_tags = " ".join(f"[{m}]" for m in active_modes)
        mode_prefix = colorize(mode_tags + " ", "bright_magenta")

    prompt = mode_prefix + colorize("> ", "cyan")
    return input(prompt)


def print_error(message):
    """Print an error message."""
    print(colorize(f"Error: {message}", "red"))


def print_success(message):
    """Print a success message."""
    print(colorize(f"✓ {message}", "green"))


def print_warning(message):
    """Print a warning message."""
    print(colorize(f"⚠ {message}", "yellow"))


def print_info(message):
    """Print an info message."""
    print(colorize(message, "dim"))


def print_teach(message):
    """Print a teaching message in magenta (for Teach Mode).

    Args:
        message: The teaching content to display
    """
    # Use magenta/bright_magenta to distinguish from green success messages
    print(colorize(f"  💡 {message}", "bright_magenta"))


def print_code(code, language=None):
    """Print code with basic formatting."""
    print()
    if language:
        print(colorize(f"```{language}", "dim"))
    print(code)
    if language:
        print(colorize("```", "dim"))
    print()


class Spinner:
    """Animated terminal spinner with multiple style options."""

    def __init__(self, message="Thinking...", delay=0.1, style="dots"):
        """Initialize spinner.

        Args:
            message: Text to display next to spinner
            delay: Seconds between animation frames
            style: One of 'dots', 'braille', 'moon', 'arrows'
        """
        spinner_frames = SPINNER_STYLES.get(style, SPINNER_STYLES["dots"])
        self.spinner = itertools.cycle(spinner_frames)
        self.message = message
        self.delay = delay
        self.style = style
        self.stop_running = False
        self.thread = None

    def spin(self):
        """Spin animation loop."""
        while not self.stop_running:
            if supports_color():
                sys.stdout.write(
                    f"\r{colorize(next(self.spinner), 'bright_cyan')} {colorize(self.message, 'dim')}"
                )
            else:
                sys.stdout.write(f"\r{next(self.spinner)} {self.message}")
            sys.stdout.flush()
            time.sleep(self.delay)

    def start(self):
        """Start the spinner in a separate thread."""
        self.stop_running = False
        self.thread = threading.Thread(target=self.spin)
        self.thread.start()

    def stop(self):
        """Stop the spinner and clear the line."""
        self.stop_running = True
        if self.thread:
            self.thread.join()
        sys.stdout.write("\r" + " " * (len(self.message) + 4) + "\r")
        sys.stdout.flush()


class ThinkingIndicator:
    """Animated thinking indicator with elapsed time display.

    Shows: ⠋ Thinking... (3.2s)
    """

    def __init__(self, message="Thinking", style="dots"):
        """Initialize thinking indicator.

        Args:
            message: Base message to display
            style: Spinner style from SPINNER_STYLES
        """
        self.message = message
        self.style = style
        self.stop_running = False
        self.thread = None
        self.start_time = None
        self.lock = threading.Lock()

    def _animation_loop(self):
        """Run the animation loop in background thread."""
        spinner_frames = SPINNER_STYLES.get(self.style, SPINNER_STYLES["dots"])
        spinner = itertools.cycle(spinner_frames)

        while not self.stop_running:
            elapsed = time.time() - self.start_time
            elapsed_str = f"({elapsed:.1f}s)"

            with self.lock:
                current_message = self.message

            display_text = f"{current_message}... {elapsed_str}"

            if supports_color():
                frame = colorize(next(spinner), "bright_cyan")
                text = colorize(display_text, "dim")
                sys.stdout.write(f"\r{frame} {text}")
            else:
                sys.stdout.write(f"\r{next(spinner)} {display_text}")

            sys.stdout.flush()
            time.sleep(0.1)

    def start(self):
        """Start the thinking indicator."""
        self.stop_running = False
        self.start_time = time.time()
        self.thread = threading.Thread(target=self._animation_loop)
        self.thread.start()

    def update(self, message):
        """Update the displayed message.

        Args:
            message: New message to display
        """
        with self.lock:
            self.message = message

    def stop(self):
        """Stop the thinking indicator and clear the line."""
        self.stop_running = True
        if self.thread:
            self.thread.join()

        # Clear the line
        clear_width = len(self.message) + 30
        sys.stdout.write("\r" + " " * clear_width + "\r")
        sys.stdout.flush()


class ProgressBar:
    """Terminal progress bar with percentage and count display.

    Shows: Processing files ████████░░░░░░░░ 50% (5/10)
    """

    def __init__(self, total, description=""):
        """Initialize progress bar.

        Args:
            total: Total number of items to process
            description: Text description shown before the bar
        """
        self.total = max(total, 1)
        self.description = description
        self.current = 0
        self.bar_width = 20
        self.start_time = None

    def _render(self):
        """Render the progress bar to terminal."""
        if self.start_time is None:
            self.start_time = time.time()

        # Calculate progress
        percent = (self.current / self.total) * 100
        filled_width = int(self.bar_width * self.current / self.total)
        empty_width = self.bar_width - filled_width

        # Build bar characters
        filled_char = "█"
        empty_char = "░"
        bar = filled_char * filled_width + empty_char * empty_width

        # Build status string
        status = f"{percent:3.0f}% ({self.current}/{self.total})"

        # Combine description and bar
        if self.description:
            display = f"{self.description} {bar} {status}"
        else:
            display = f"{bar} {status}"

        # Colorize if supported
        if supports_color():
            colored_bar = colorize(filled_char * filled_width, "bright_cyan") + colorize(
                empty_char * empty_width, "dim"
            )
            if self.description:
                display = (
                    f"{colorize(self.description, 'cyan')} {colored_bar} {colorize(status, 'dim')}"
                )
            else:
                display = f"{colored_bar} {colorize(status, 'dim')}"

        sys.stdout.write(f"\r{display}")
        sys.stdout.flush()

    def update(self, current):
        """Update progress bar to new position.

        Args:
            current: Current progress value (0 to total)
        """
        self.current = min(current, self.total)
        self._render()

    def increment(self, amount=1):
        """Increment progress by given amount.

        Args:
            amount: Amount to increment by (default 1)
        """
        self.update(self.current + amount)

    def finish(self):
        """Complete the progress bar and move to next line."""
        self.current = self.total
        self._render()

        # Calculate elapsed time
        if self.start_time:
            elapsed = time.time() - self.start_time
            elapsed_str = f" ({elapsed:.1f}s)"
        else:
            elapsed_str = ""

        # Print completion message
        if supports_color():
            print(colorize(f" Done{elapsed_str}", "green"))
        else:
            print(f" Done{elapsed_str}")


def print_thinking():
    """Print thinking indicator (legacy)."""
    # Now handled by Spinner context in agent
    pass


def clear_thinking():
    """Clear the thinking indicator (legacy)."""
    # Now handled by Spinner context in agent
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
    """Print tool result in verbose Claude Code style.

    Args:
        tool_name: Name of the tool
        result: Result dictionary from tool execution
        duration_ms: Optional execution duration
    """
    success = result.get("success", False)

    # Status indicator
    if success:
        status = colorize("  ✓ ", "green")
    else:
        status = colorize("  ✗ ", "red")

    # Duration string
    duration_str = ""
    if duration_ms is not None:
        if duration_ms < 1000:
            duration_str = colorize(f" ({duration_ms:.0f}ms)", "dim")
        else:
            duration_str = colorize(f" ({duration_ms / 1000:.1f}s)", "dim")

    # Result summary based on tool
    if tool_name == "read_file":
        lines = result.get("line_count", 0)
        print(f"{status}Read {lines} lines{duration_str}")
    elif tool_name == "write_file":
        print(f"{status}File written{duration_str}")
    elif tool_name == "run_shell_command":
        code = result.get("returncode", 0)
        if success:
            print(f"{status}Exit code: {code}{duration_str}")
        else:
            print(f"{status}Failed (exit {code}){duration_str}")
    elif tool_name == "list_directory":
        count = result.get("count", 0)
        print(f"{status}Found {count} items{duration_str}")
    elif tool_name == "glob_files":
        count = result.get("count", 0)
        print(f"{status}Matched {count} files{duration_str}")
    elif tool_name == "grep_search":
        count = result.get("count", 0)
        files = result.get("files_searched", 0)
        print(f"{status}{count} matches in {files} files{duration_str}")
    else:
        if success:
            print(f"{status}Done{duration_str}")
        else:
            error = result.get("error", "Unknown error")[:50]
            print(f"{status}{error}{duration_str}")


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
    _session_files.append({
        "path": path,
        "content": content,
        "display_content": display_content,
    })


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
            line_text = line_text[:max_width - 3] + "..."
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


def print_help():
    """Print help information."""
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
        + colorize("Use /commands to see ALL available commands", "dim")
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
