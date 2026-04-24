"""Terminal UI mapping for RadSim using rich."""

import logging
import sys

from rich.console import Console, Group
from rich.control import Control
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.segment import ControlType
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from .terminal import supports_color
from .theme import (
    glyph,
    load_active_animation_level,
    load_active_palette,
    tool_category,
)

logger = logging.getLogger(__name__)

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import ANSI
    from prompt_toolkit.patch_stdout import patch_stdout

    _PTK_AVAILABLE = True
except ImportError:
    _PTK_AVAILABLE = False

_prompt_session = None

# RadSim palette — sourced from ~/.radsim/settings.json (user-selectable).
# Falls back to DEFAULT_PALETTE ("soft-neon") on first run.
COLORS = dict(load_active_palette()["colors"])

radsim_theme = Theme(
    {
        "primary": COLORS["primary"],
        "success": COLORS["success"],
        "warning": COLORS["warning"],
        "error": COLORS["error"],
        "muted": COLORS["muted"],
        "accent": COLORS["accent"],
        "subtle": COLORS["subtle"],
        "info": COLORS["primary"],
        "prompt": COLORS["primary"],
    }
)

console = Console(theme=radsim_theme, force_terminal=True if supports_color() else False)

TOOL_TAG_WIDTH = 10
TOOL_ARGUMENT_WIDTH = 34
TOOL_RESULT_WIDTH = 14
TOOL_FAIL_WIDTH = 12


def reload_theme():
    """Rebuild COLORS and push a new theme onto the console after a /theme change."""
    global COLORS
    COLORS = dict(load_active_palette()["colors"])
    new_theme = Theme(
        {
            "primary": COLORS["primary"],
            "success": COLORS["success"],
            "warning": COLORS["warning"],
            "error": COLORS["error"],
            "muted": COLORS["muted"],
            "accent": COLORS["accent"],
            "subtle": COLORS["subtle"],
            "info": COLORS["primary"],
            "prompt": COLORS["primary"],
        }
    )
    console.push_theme(new_theme)


def _pad_text(value, width):
    if len(value) <= width:
        return value.ljust(width)
    ellipsis = glyph("ellipsis")
    trim_width = max(width - len(ellipsis), 0)
    return f"{value[:trim_width]}{ellipsis}"


def _clear_inline_line():
    console.control(Control.move_to_column(0), Control((ControlType.ERASE_IN_LINE, 2)))
    console.file.flush()


def _rewrite_inline(renderable):
    _clear_inline_line()
    console.print(renderable, end="")
    console.file.flush()


def _tool_line(verb, color_name, argument, result, duration="", status=None):
    text = Text()

    tag = f"[{verb}]"
    tag_padding = " " * max(TOOL_TAG_WIDTH - len(tag), 1)
    text.append("  [", style="muted")
    text.append(verb, style=color_name)
    text.append("]", style="muted")
    text.append(tag_padding, style="muted")

    text.append(_pad_text(argument, TOOL_ARGUMENT_WIDTH), style="muted")

    if status:
        text.append(_pad_text(status, TOOL_FAIL_WIDTH), style="error")
        if result:
            text.append(result)
            if duration:
                text.append("   ")
        if duration:
            text.append(duration, style="muted")
        return text

    text.append(_pad_text(result, TOOL_RESULT_WIDTH))
    if duration:
        text.append(duration, style="muted")
    return text


class Spinner:
    """Contextual spinner for single-step operations."""

    def __init__(self, message="Thinking...", delay=0.1, style="dots"):
        self.message = message
        self.delay = delay
        self.style = style
        self.animation_level = load_active_animation_level()
        self.status = None
        self.is_active = False
        self._inline_visible = False

    def start(self):
        """Start the spinner."""
        if self.is_active:
            return

        if self.animation_level == "full":
            speed = 0.08 / self.delay if self.delay > 0 else 1.0
            self.status = console.status(
                f"[primary]{self.message}[/primary]",
                spinner="dots",
                spinner_style="primary",
                speed=speed,
            )
            self.status.start()
        elif self.animation_level == "subtle":
            console.print(f"  {self.message}", style="primary", end="")
            console.file.flush()
            self._inline_visible = True

        self.is_active = True

    def update(self, message):
        """Update the spinner message."""
        self.message = message
        if self.animation_level == "full" and self.status is not None:
            self.status.update(f"[primary]{self.message}[/primary]")
        elif self.animation_level == "subtle" and self._inline_visible:
            _rewrite_inline(Text(f"  {self.message}", style="primary"))

    def stop(self):
        """Stop the spinner."""
        if not self.is_active:
            return

        if self.animation_level == "full" and self.status is not None:
            self.status.stop()
        elif self.animation_level == "subtle" and self._inline_visible:
            _clear_inline_line()
            self._inline_visible = False

        self.status = None
        self.is_active = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


class ToolEventHandle:
    """A single-line tool event that can be updated in place."""

    def __init__(self, tool_name, argument):
        self.tool_name = tool_name
        self.argument = argument
        self.verb, self.color_name = tool_category(tool_name)
        self.animation_level = load_active_animation_level()
        self.can_rewrite = self.animation_level != "off" and sys.stdout.isatty()
        self.is_finished = False

        if self.can_rewrite:
            _rewrite_inline(
                _tool_line(
                    self.verb,
                    self.color_name,
                    self.argument,
                    f"running{glyph('ellipsis')}",
                )
            )

    def update(self, argument):
        """Rewrite the argument column while the tool is still running."""
        if self.is_finished:
            return

        self.argument = argument
        if self.can_rewrite:
            _rewrite_inline(
                _tool_line(
                    self.verb,
                    self.color_name,
                    self.argument,
                    f"running{glyph('ellipsis')}",
                )
            )

    def finish(self, ok, result, duration_ms, error=None):
        """Render the final tool state."""
        if self.is_finished:
            return

        duration = ""
        if duration_ms is not None:
            if duration_ms < 1000:
                duration = f"{duration_ms:.0f}ms"
            else:
                duration = f"{duration_ms / 1000:.1f}s"

        line = _tool_line(
            self.verb,
            self.color_name,
            self.argument,
            result,
            duration=duration,
            status=None if ok else "fail",
        )

        if self.can_rewrite:
            _clear_inline_line()
            console.print(line)
        else:
            console.print(line)

        if not ok and error:
            console.print(f"  └ error: {error}", style="error")

        self.is_finished = True

    def __del__(self):
        if __debug__ and not self.is_finished:
            logger.warning("ToolEventHandle for %s was not finished before cleanup", self.tool_name)


def tool_event(tool_name, argument):
    """Create a single-line tool event handle."""
    return ToolEventHandle(tool_name, argument)


class PhaseProgressBar:
    """Progress bar for operations with known multiple steps."""

    def __init__(self, total_steps, description="Processing..."):
        self.progress = Progress(
            SpinnerColumn(spinner_name="dots", style="primary"),
            TextColumn("[primary]{task.description}"),
            BarColumn(complete_style="primary", finished_style="success"),
            TaskProgressColumn(),
            TextColumn("[muted]({task.completed}/{task.total})[/muted]"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        )
        self.task_id = self.progress.add_task(description, total=total_steps)
        self.is_active = False

    def start(self):
        if not self.is_active:
            self.progress.start()
            self.is_active = True

    def update(self, advance=1, description=None):
        kwargs = {"advance": advance}
        if description:
            kwargs["description"] = description
        self.progress.update(self.task_id, **kwargs)

    def stop(self):
        if self.is_active:
            self.progress.stop()
            self.is_active = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def show_success_panel(title, content):
    """Display a success panel."""
    panel = Panel(
        content,
        title=f"ok {title}",
        border_style="success",
        expand=False,
        padding=(0, 2),
    )
    console.print(panel)


def show_error_panel(title, content):
    """Display an error panel."""
    panel = Panel(
        content,
        title=f"error {title}",
        border_style="error",
        expand=False,
        padding=(0, 2),
    )
    console.print(panel)


def print_prompt(active_modes: list = None, registry=None) -> str:
    """Print the distinctive RadSim prompt and capture input.

    When a CommandRegistry is supplied and prompt_toolkit is available on
    a TTY, an inline dropdown of registered slash commands appears as soon
    as the user types `/`, filtering alphabetically as more characters are
    typed (Codex / Claude Code CLI style).

    Returns:
        The user's string input.
    """
    mode_prefix = ""
    if active_modes:
        mode_tags = " ".join(f"[{mode}]" for mode in active_modes)
        mode_prefix = f"[accent]{mode_tags}[/accent] "

    prompt = mode_prefix + f"[primary]{glyph('prompt')}[/primary] "

    if _PTK_AVAILABLE and registry is not None and sys.stdin.isatty():
        from .command_completer import build_completer

        global _prompt_session
        if _prompt_session is None:
            _prompt_session = PromptSession()

        with console.capture() as cap:
            console.print(prompt, end="")
        ansi_prompt = ANSI(cap.get().rstrip("\n"))

        with patch_stdout(raw=True):
            return _prompt_session.prompt(
                ansi_prompt,
                completer=build_completer(registry),
                complete_while_typing=True,
            )


    return console.input(prompt)


def print_teach(message):
    """Print a teaching message in accent color."""
    console.print(f"[accent]  [teach] {message}[/accent]")


def print_success(message):
    console.print(f"[success]ok[/success] {message}")


def print_error(message):
    console.print(f"[error]error:[/error] {message}")


def print_warning(message):
    console.print(f"[warning]warning:[/warning] {message}")


def print_info(message):
    console.print(f"[muted]{message}[/muted]")


class LiveStatusTable:
    """Real-time updating status table for parallel or multiple operations."""

    def __init__(self, title="Operations"):
        self.table = Table(title=title, style="primary", border_style="primary")
        self.table.add_column("Task", style="cyan")
        self.table.add_column("Status", justify="center")
        self.table.add_column("Duration", justify="right", style="muted")

        self.tasks = {}
        self.live = Live(self.table, console=console, refresh_per_second=4)

    def add_task(self, name, status="[warning]pending[/warning]", duration="--"):
        """Add a new task to the table."""
        self.tasks[name] = {"status": status, "duration": str(duration)}
        self._update_table()

    def update_task(self, name, status, duration):
        """Update an existing task."""
        if name in self.tasks:
            self.tasks[name] = {"status": status, "duration": str(duration)}
            self._update_table()

    def _update_table(self):
        self.table.columns[0]._cells.clear()
        self.table.columns[1]._cells.clear()
        self.table.columns[2]._cells.clear()

        for name, info in self.tasks.items():
            self.table.add_row(name, info["status"], info["duration"])

    def start(self):
        self.live.start()

    def stop(self):
        self.live.stop()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def print_hint(message):
    """Print an inline hint or tip."""
    console.print(f"[muted]   Tip: {message}[/muted]")


class TaskDashboard:
    """Mini dashboard for long-running or multi-step tasks."""

    def __init__(self, title="RadSim Task", total_steps=100):
        self.title = title
        self.progress = Progress(
            SpinnerColumn(spinner_name="dots", style="primary"),
            TextColumn("[primary]{task.description}"),
            BarColumn(complete_style="primary", finished_style="success"),
            TaskProgressColumn(),
            TextColumn("[muted]({task.completed}/{task.total})[/muted]"),
            TimeElapsedColumn(),
            console=console,
        )
        self.task_id = self.progress.add_task("Initializing...", total=total_steps)
        self.extra_info = []
        self.live = Live(self._build_panel(), console=console, refresh_per_second=4, transient=True)

    def _build_panel(self):
        content = [self.progress]
        if self.extra_info:
            content.append(Text(""))
            content.extend([Text(line, style="muted") for line in self.extra_info])
            content.append(Text("\nPress [Ctrl+C] to cancel", style="dim"))

        group = Group(*content)
        return Panel(group, title=f" RadSim: {self.title} ", border_style="primary", expand=False)

    def update(self, advance=0, description=None, info=None):
        if description:
            self.progress.update(self.task_id, description=description)
        if advance:
            self.progress.update(self.task_id, advance=advance)
        if info is not None:
            self.extra_info = info
        self.live.update(self._build_panel())

    def start(self):
        self.live.start()

    def stop(self):
        self.live.stop()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
