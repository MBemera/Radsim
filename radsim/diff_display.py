"""Unified diff display with colors for RadSim.

RadSim Principle: Radical Simplicity - Clear, obvious code.
"""

import difflib
import logging
import sys

logger = logging.getLogger(__name__)

# ANSI color codes for diff display
DIFF_COLORS = {
    "reset": "\033[0m",
    "red": "\033[91m",  # Bright red text
    "green": "\033[92m",  # Bright green text
    "gray": "\033[90m",
    "cyan": "\033[96m",  # Bright cyan
    "bold": "\033[1m",
    "dim": "\033[2m",
    "bg_red": "\033[48;5;52m",  # Dark red background
    "bg_green": "\033[48;5;22m",  # Dark green background
    "red_bold": "\033[1;91m",  # Bold bright red
    "green_bold": "\033[1;92m",  # Bold bright green
}


def supports_color():
    """Check if terminal supports colors."""
    if not hasattr(sys.stdout, "isatty"):
        return False
    if not sys.stdout.isatty():
        return False
    return True


def colorize(text, color):
    """Apply color to text if terminal supports it.

    Args:
        text: Text to colorize
        color: Color name from DIFF_COLORS

    Returns:
        Colorized string or plain text if no color support
    """
    if not supports_color():
        return text
    return f"{DIFF_COLORS.get(color, '')}{text}{DIFF_COLORS['reset']}"


def count_changes(old_lines, new_lines):
    """Count additions and deletions between two line lists.

    Args:
        old_lines: Original content as list of lines
        new_lines: New content as list of lines

    Returns:
        Tuple of (additions, deletions)
    """
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))

    additions = 0
    deletions = 0

    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1

    return additions, deletions


def format_diff_header(filename, additions, deletions):
    """Format the diff header with filename and change counts.

    Args:
        filename: Name of file being diffed
        additions: Number of lines added
        deletions: Number of lines deleted

    Returns:
        Formatted header string
    """
    if filename:
        file_part = colorize(filename, "cyan")
    else:
        file_part = colorize("(unnamed)", "gray")

    add_part = colorize(f"+{additions}", "green")
    del_part = colorize(f"-{deletions}", "red")

    header_line = f"  {file_part}  {add_part}  {del_part}"
    separator = colorize("─" * 60, "dim")

    return f"\n{separator}\n{header_line}\n{separator}"


def format_diff_line(line, line_number=None):
    """Format a single diff line with appropriate colors.

    Args:
        line: The diff line to format
        line_number: Optional line number to display

    Returns:
        Formatted line string
    """
    # Build line number gutter
    if line_number is not None:
        gutter = colorize(f"{line_number:4} ", "dim")
    else:
        gutter = colorize("     ", "dim")

    # Determine line type and color
    if line.startswith("+++") or line.startswith("---"):
        # File headers - skip or dim
        return colorize(gutter + line, "dim")

    elif line.startswith("@@"):
        # Hunk headers - show location info
        return colorize(gutter + line, "cyan")

    elif line.startswith("+"):
        # Added line - bright green with dark green background
        content = line[1:]  # Remove the + prefix
        prefix = colorize("+ ", "green_bold")
        text = (
            f"{DIFF_COLORS['bg_green']}{DIFF_COLORS['green']}{content}{DIFF_COLORS['reset']}"
            if supports_color()
            else content
        )
        return gutter + prefix + text

    elif line.startswith("-"):
        # Removed line - bright red with dark red background
        content = line[1:]  # Remove the - prefix
        prefix = colorize("- ", "red_bold")
        text = (
            f"{DIFF_COLORS['bg_red']}{DIFF_COLORS['red']}{content}{DIFF_COLORS['reset']}"
            if supports_color()
            else content
        )
        return gutter + prefix + text

    else:
        # Context line - gray
        return gutter + colorize("  " + line, "gray")


def show_diff(old_content, new_content, filename=None):
    """Display unified diff with colors.

    Generates a colored unified diff between old and new content.
    Shows removed lines in red and added lines in green.

    Args:
        old_content: Original file content as string
        new_content: New file content as string
        filename: Optional filename to show in header

    Returns:
        The formatted diff string (empty string if no changes)
    """
    # Handle empty inputs
    if old_content is None:
        old_content = ""
    if new_content is None:
        new_content = ""

    # Split into lines
    old_lines = old_content.splitlines(keepends=False)
    new_lines = new_content.splitlines(keepends=False)

    # Check if there are any differences
    if old_lines == new_lines:
        return ""

    # Count changes for header
    additions, deletions = count_changes(old_lines, new_lines)

    # Generate unified diff
    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="original",
            tofile="modified",
            lineterm="",
        )
    )

    if not diff_lines:
        return ""

    # Build output
    output_parts = []

    # Add header
    header = format_diff_header(filename, additions, deletions)
    output_parts.append(header)

    # Track line numbers for context
    old_line_num = 0
    new_line_num = 0

    for line in diff_lines:
        # Parse hunk headers for line numbers
        if line.startswith("@@"):
            # Extract line numbers from hunk header
            # Format: @@ -start,count +start,count @@
            try:
                parts = line.split(" ")
                old_part = parts[1]  # -start,count
                new_part = parts[2]  # +start,count

                old_start = int(old_part.split(",")[0].lstrip("-"))
                new_start = int(new_part.split(",")[0].lstrip("+"))

                old_line_num = old_start
                new_line_num = new_start
            except (IndexError, ValueError):
                logger.debug(f"Failed to parse diff hunk header: {line}")

            output_parts.append(format_diff_line(line))

        elif line.startswith("---") or line.startswith("+++"):
            # Skip file header lines (we show our own header)
            continue

        elif line.startswith("-"):
            # Deleted line - show old line number
            output_parts.append(format_diff_line(line, old_line_num))
            old_line_num += 1

        elif line.startswith("+"):
            # Added line - show new line number
            output_parts.append(format_diff_line(line, new_line_num))
            new_line_num += 1

        else:
            # Context line - increment both
            output_parts.append(format_diff_line(line, new_line_num))
            old_line_num += 1
            new_line_num += 1

    # Add closing separator
    output_parts.append(colorize("─" * 60, "dim"))
    output_parts.append("")

    return "\n".join(output_parts)


def get_diff_summary(old_content, new_content):
    """Get a brief summary of changes without full diff.

    Args:
        old_content: Original file content
        new_content: New file content

    Returns:
        Summary string like "+5 lines, -2 lines"
    """
    if old_content is None:
        old_content = ""
    if new_content is None:
        new_content = ""

    old_lines = old_content.splitlines(keepends=False)
    new_lines = new_content.splitlines(keepends=False)

    if old_lines == new_lines:
        return "No changes"

    additions, deletions = count_changes(old_lines, new_lines)

    parts = []
    if additions > 0:
        parts.append(colorize(f"+{additions} lines", "green"))
    if deletions > 0:
        parts.append(colorize(f"-{deletions} lines", "red"))

    if not parts:
        return "No changes"

    return ", ".join(parts)
