"""
Terminal UI mapping for RadSim using 'rich'.
Provides unified visual style using the custom palette, smooth animations,
progress bars, and status panels.
"""

import sys
import time

from rich.console import Console, Group
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
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# Define the unique RadSim color palette
COLORS = {
    "primary": "#00D4AA",    # Cyan
    "success": "#00C853",    # Green
    "warning": "#FFD600",    # Yellow
    "error": "#FF1744",      # Red
    "muted": "#78909C",      # Gray
    "accent": "#E040FB",     # Magenta
}

radsim_theme = Theme({
    "primary": COLORS["primary"],
    "success": COLORS["success"],
    "warning": COLORS["warning"],
    "error": COLORS["error"],
    "muted": COLORS["muted"],
    "accent": COLORS["accent"],

    # Semantic mappings
    "info": COLORS["primary"],
    "prompt": COLORS["primary"],
})

def supports_color():
    """Check if terminal supports colors."""
    if not hasattr(sys.stdout, "isatty"):
        return False
    if not sys.stdout.isatty():
        return False
    return True

# Initialize global console
console = Console(theme=radsim_theme, force_terminal=True if supports_color() else False)


class Spinner:
    """Contextual spinner for single-step operations."""

    def __init__(self, message="Thinking...", delay=0.1, style="dots"):
        """
        Initialize the spinner.

        Args:
            message: Text to display next to the spinner.
            delay: Animation delay (approximate mapping).
            style: Spinner style from rich (default 'dots').
        """
        self.message = message
        # Convert custom delay to rich speed multiplier
        self_speed = 0.08 / delay if delay > 0 else 1.0


        self.status = console.status(
            f"[primary]{self.message}[/primary]",
            spinner=style,
            spinner_style="primary",
            speed=self_speed
        )
        self.is_active = False

    def start(self):
        """Start the spinner."""
        if not self.is_active:
            self.status.start()
            self.is_active = True

    def update(self, message):
        """Update the spinner message."""
        self.message = message
        self.status.update(f"[primary]{self.message}[/primary]")

    def stop(self):
        """Stop the spinner."""
        if self.is_active:
            self.status.stop()
            self.is_active = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


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
            transient=True, # Custom behavior: clears after finishing
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
        title=f"✅ {title}",
        border_style="success",
        expand=False,
        padding=(0, 2)
    )
    console.print(panel)


def show_error_panel(title, content):
    """Display an error panel."""
    panel = Panel(
        content,
        title=f"❌ {title}",
        border_style="error",
        expand=False,
        padding=(0, 2)
    )
    console.print(panel)


def print_prompt(active_modes: list = None) -> str:
    """Print the distinctive RadSim prompt and capture input.

    Returns:
        The user's string input.
    """
    mode_prefix = ""
    if active_modes:
        mode_tags = " ".join(f"[{m}]" for m in active_modes)
        mode_prefix = f"[accent]{mode_tags}[/accent] "

    prompt = mode_prefix + "[primary]▶[/primary] "
    return console.input(prompt)


def print_teach(message):
    """Print a teaching message in magenta (for Teach Mode)."""
    console.print(f"[accent]  💡 {message}[/accent]")


def print_success(message):
    console.print(f"[success]✓ {message}[/success]")


def print_error(message):
    console.print(f"[error]Error: {message}[/error]")


def print_warning(message):
    console.print(f"[warning]⚠ {message}[/warning]")


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

    def add_task(self, name, status="[warning]⏳ Pending[/warning]", duration="--"):
        """Add a new task to the table."""
        self.tasks[name] = {"status": status, "duration": str(duration)}
        self._update_table()

    def update_task(self, name, status, duration):
        """Update an existing task."""
        if name in self.tasks:
            self.tasks[name] = {"status": status, "duration": str(duration)}
            self._update_table()

    def _update_table(self):
        """Rebuild the table rows."""
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




def print_typewriter(text, delay=0.02, style="info", end="\n"):
    """Animate text being typed character-by-character (Demo/Help mode)."""
    if not supports_color():
        print(text, end=end)
        return

    for char in text:
        console.print(char, end="", style=style)
        time.sleep(delay)
    console.print(end=end)


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


