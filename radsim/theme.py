"""Theme and font profile management for RadSim UI.

Persists user's palette and glyph preferences to ~/.radsim/settings.json
alongside provider/model/rate-limit settings.
"""

import json
import logging

from .config import CONFIG_DIR, SETTINGS_FILE, load_settings_file
from .terminal import supports_color

logger = logging.getLogger(__name__)


PALETTES = {
    "classic": {
        "label": "Classic (saturated cyan/magenta)",
        "description": "The original RadSim palette.",
        "colors": {
            "primary": "#00D4AA",
            "accent": "#E040FB",
            "success": "#00C853",
            "warning": "#FFD600",
            "error": "#FF1744",
            "muted": "#78909C",
            "subtle": "#263238",
        },
    },
    "soft-neon": {
        "label": "Soft Neon (sky + violet)",
        "description": "Modern pastel palette, easy on the eyes.",
        "colors": {
            "primary": "#7DD3FC",
            "accent": "#A78BFA",
            "success": "#86EFAC",
            "warning": "#FDE68A",
            "error": "#FCA5A5",
            "muted": "#64748B",
            "subtle": "#1E293B",
        },
    },
    "tokyo-night": {
        "label": "Tokyo Night (cool, muted)",
        "description": "Popular dark editor palette.",
        "colors": {
            "primary": "#7AA2F7",
            "accent": "#BB9AF7",
            "success": "#9ECE6A",
            "warning": "#E0AF68",
            "error": "#F7768E",
            "muted": "#565F89",
            "subtle": "#24283B",
        },
    },
    "warm-terminal": {
        "label": "Warm Terminal (amber + teal)",
        "description": "Retro-modern, distinctive.",
        "colors": {
            "primary": "#5EEAD4",
            "accent": "#FCD34D",
            "success": "#A3E635",
            "warning": "#FB923C",
            "error": "#F87171",
            "muted": "#78716C",
            "subtle": "#292524",
        },
    },
    "mono-mint": {
        "label": "Monochrome Mint (minimal)",
        "description": "Minimal green with pink accent.",
        "colors": {
            "primary": "#34D399",
            "accent": "#F472B6",
            "success": "#6EE7B7",
            "warning": "#FBBF24",
            "error": "#EF4444",
            "muted": "#6B7280",
            "subtle": "#1F2937",
        },
    },
}

DEFAULT_PALETTE = "soft-neon"


FONT_PROFILES = {
    "nerd": {
        "label": "Nerd Font (extra glyphs)",
        "description": "Requires a Nerd Font patched terminal font.",
        "glyphs": {
            "prompt": "\uf0a9",
            "arrow": "\uf054",
            "branch": "\ue0a0",
            "bullet": "\uf444",
            "divider": "\uf460",
            "diff_add": "+",
            "diff_del": "\u2212",
            "ellipsis": "\u2026",
        },
    },
    "unicode": {
        "label": "Unicode (modern terminals)",
        "description": "Clean glyphs that work in most modern terminals.",
        "glyphs": {
            "prompt": "▶",
            "arrow": "❯",
            "branch": "⎇",
            "bullet": "●",
            "divider": "·",
            "diff_add": "+",
            "diff_del": "\u2212",
            "ellipsis": "\u2026",
        },
    },
    "ascii": {
        "label": "ASCII (maximum compatibility)",
        "description": "Pure ASCII — safe in any terminal, no Unicode required.",
        "glyphs": {
            "prompt": ">",
            "arrow": ">",
            "branch": "|",
            "bullet": "-",
            "divider": "|",
            "diff_add": "+",
            "diff_del": "-",
            "ellipsis": "...",
        },
    },
}

DEFAULT_FONT_PROFILE = "unicode"
ANIMATION_LEVELS = ("full", "subtle", "off")
DEFAULT_ANIMATION_LEVEL = "subtle"

TOOL_CATEGORY_COLORS = {
    "read": "primary",
    "list": "primary",
    "grep": "primary",
    "write": "accent",
    "edit": "accent",
    "shell": "warning",
    "run": "warning",
    "git": "accent",
    "web": "primary",
}

TOOL_VERBS = {
    "read_file": "read",
    "read_many_files": "read",
    "todo_read": "read",
    "list_directory": "list",
    "glob_files": "list",
    "grep_search": "grep",
    "search_files": "grep",
    "find_definition": "grep",
    "find_references": "grep",
    "write_file": "write",
    "todo_write": "write",
    "replace_in_file": "edit",
    "rename_file": "edit",
    "delete_file": "edit",
    "multi_edit": "edit",
    "batch_replace": "edit",
    "apply_patch": "edit",
    "run_shell_command": "shell",
    "run_tests": "run",
    "lint_code": "run",
    "format_code": "run",
    "type_check": "run",
    "git_status": "git",
    "git_diff": "git",
    "git_log": "git",
    "git_branch": "git",
    "git_add": "git",
    "git_commit": "git",
    "git_checkout": "git",
    "git_stash": "git",
    "web_fetch": "web",
    "browser_open": "web",
    "browser_click": "web",
    "browser_type": "web",
    "browser_screenshot": "web",
}


RECOMMENDED_FONTS = [
    ("JetBrains Mono Nerd Font", "Free. Coding-optimized. Widest glyph coverage."),
    ("Geist Mono Nerd Font", "Vercel. Minimal. Excellent at small sizes."),
    ("Iosevka Nerd Font", "Condensed. Space-efficient."),
    ("Monaspace Argon / Neon", "GitHub. Variable-width stylistic sets."),
    ("Berkeley Mono", "Paid. Distinctive. Premium feel."),
]


def load_active_palette_name():
    settings = load_settings_file()
    name = settings.get("theme_palette", DEFAULT_PALETTE)
    if name not in PALETTES:
        return DEFAULT_PALETTE
    return name


def load_active_palette():
    return PALETTES[load_active_palette_name()]


def load_active_font_profile_name():
    settings = load_settings_file()
    name = settings.get("theme_font_profile", DEFAULT_FONT_PROFILE)
    if name not in FONT_PROFILES:
        return DEFAULT_FONT_PROFILE
    return name


def load_active_font_profile():
    return FONT_PROFILES[load_active_font_profile_name()]


def load_active_animation_level():
    if not supports_color():
        return "off"

    settings = load_settings_file()
    level = settings.get("animation_level", DEFAULT_ANIMATION_LEVEL)
    if level not in ANIMATION_LEVELS:
        return DEFAULT_ANIMATION_LEVEL
    return level


def save_palette_selection(palette_name):
    if palette_name not in PALETTES:
        raise ValueError(f"Unknown palette: {palette_name}")
    _update_settings({"theme_palette": palette_name})


def save_font_profile_selection(profile_name):
    if profile_name not in FONT_PROFILES:
        raise ValueError(f"Unknown font profile: {profile_name}")
    _update_settings({"theme_font_profile": profile_name})


def save_animation_level(level):
    if level not in ANIMATION_LEVELS:
        raise ValueError(f"Unknown animation level: {level}")
    _update_settings({"animation_level": level})


def _update_settings(patch):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    settings = load_settings_file()
    settings.update(patch)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2))


def glyph(name):
    """Return the glyph for the active font profile, or '?' if unknown."""
    return load_active_font_profile()["glyphs"].get(name, "?")


def tool_category(tool_name):
    """Return a display verb and palette color for a tool name."""
    if tool_name in TOOL_VERBS:
        verb = TOOL_VERBS[tool_name]
        return verb, TOOL_CATEGORY_COLORS.get(verb, "muted")

    if tool_name.startswith("git_"):
        return "git", TOOL_CATEGORY_COLORS["git"]

    if tool_name.startswith("browser_"):
        return "web", TOOL_CATEGORY_COLORS["web"]

    return tool_name, "muted"


def apply_to_console(console):
    """Push the active palette onto an existing rich Console's theme stack.

    Called by /theme after the user changes selection so the new palette
    takes effect without restarting RadSim.
    """
    from rich.theme import Theme

    palette = load_active_palette()["colors"]
    new_theme = Theme(
        {
            "primary": palette["primary"],
            "accent": palette["accent"],
            "success": palette["success"],
            "warning": palette["warning"],
            "error": palette["error"],
            "muted": palette["muted"],
            "subtle": palette["subtle"],
            "info": palette["primary"],
            "prompt": palette["primary"],
        }
    )
    console.push_theme(new_theme)
