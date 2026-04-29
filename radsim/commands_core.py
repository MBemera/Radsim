"""Core slash-command handlers."""

import sys

from .config import setup_config
from .output import print_help, print_info


class CoreCommandHandlersMixin:
    """Handlers for core session, configuration, and mode commands."""

    def _cmd_help(self, agent, args=None):
        if args:
            topic = " ".join(args).strip().lower().lstrip("/")
            print_help(topic=topic)
        else:
            print_help()

    def _cmd_tools(self, agent):
        from .agent import print_tools_list

        print_tools_list()

    def _cmd_clear(self, agent):
        agent.reset()
        from .background import reset_job_manager
        from .todo import reset_tracker

        reset_tracker()
        reset_job_manager()
        agent._session_capable_model = None
        print_info("Conversation, task tracker, and background jobs cleared.")

    def _cmd_config(self, agent):
        from .output import print_header

        api_key, provider, model = setup_config(first_time=False)
        if api_key and provider and model:
            agent.update_config(provider, api_key, model)
            print_header(provider, model)

    def _cmd_exit(self, agent):
        print("Goodbye!")
        sys.exit(0)

    def _cmd_kill(self, agent):
        """EMERGENCY: Immediately terminate the agent and all operations."""
        import os

        print()
        print("  EMERGENCY STOP")
        print("  Terminating all agent operations immediately...")
        print()
        os._exit(1)

    def _cmd_new(self, agent):
        """Start a completely fresh conversation."""
        agent.reset()
        if hasattr(agent, "protection"):
            agent.protection.rate_limiter.reset()
            agent.protection.budget_guard.reset()

        from .output import clear_session_files

        clear_session_files()
        print_info("Started new conversation with fresh context.")

    def _cmd_setup(self, agent):
        """Re-run the setup wizard."""
        from .onboarding import run_onboarding
        from .output import print_header

        api_key, provider, model = run_onboarding()
        if api_key and provider and model:
            agent.update_config(provider, api_key, model)
            print_header(provider, model)
        else:
            print_info("Setup cancelled or incomplete.")

    def _cmd_switch(self, agent, args=None):
        """Quick switch provider/model without full setup."""
        from .config import (
            PROVIDER_MODELS,
            _maybe_prompt_reasoning_effort,
            _select_openrouter_model,
            load_env_file,
        )
        from .output import print_header

        print()
        print("  Quick Switch - Select provider:")
        print("    1. Claude (Anthropic)")
        print("    2. GPT-5 (OpenAI)")
        print("    3. Gemini (Google)")
        print("    4. Vertex AI (Google Cloud)")
        print("    5. OpenRouter")
        print()

        try:
            choice = input("  Enter 1-5: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Cancelled.")
            return

        provider_map = {
            "1": "claude",
            "2": "openai",
            "3": "gemini",
            "4": "vertex",
            "5": "openrouter",
        }
        provider = provider_map.get(choice)

        if not provider:
            print("  Invalid choice.")
            return

        from .config import PROVIDER_ENV_VARS

        env_config = load_env_file()

        if provider == "vertex":
            project_id = env_config.get("keys", {}).get("GOOGLE_CLOUD_PROJECT")
            if not project_id or project_id.lower().startswith("paste_your"):
                print("  warning: No GOOGLE_CLOUD_PROJECT found. Add it to .env first.")
                return
            location = env_config.get("keys", {}).get("GOOGLE_CLOUD_LOCATION", "us-central1")
            api_key = f"{project_id}:{location}"
        else:
            env_var = PROVIDER_ENV_VARS.get(provider, "RADSIM_API_KEY")
            api_key = env_config.get("keys", {}).get(env_var)

            if not api_key or api_key.lower().startswith("paste_your"):
                print(f"  warning: No API key found for {provider}. Add it to .env first.")
                return

        if provider == "openrouter":
            model = _select_openrouter_model()
            if not model:
                print("\n  Cancelled.")
                return
        else:
            print()
            print("  Select model:")
            models = PROVIDER_MODELS[provider]
            for index, (_, model_name) in enumerate(models, 1):
                print(f"    {index}. {model_name}")
            print()

            try:
                model_choice = input(f"  Enter 1-{len(models)} [1]: ").strip() or "1"
            except (KeyboardInterrupt, EOFError):
                print("\n  Cancelled.")
                return

            try:
                model_index = int(model_choice) - 1
                if 0 <= model_index < len(models):
                    model = models[model_index][0]
                else:
                    model = models[0][0]
            except ValueError:
                model = models[0][0]

        _maybe_prompt_reasoning_effort(provider, model)

        agent.update_config(provider, api_key, model)
        print()
        print(f"  ok Switched to {provider} / {model}")
        print_header(provider, model)

    def _cmd_free(self, agent):
        """Instantly switch to cheapest OpenRouter model (Kimi K2.5)."""
        from .config import load_env_file
        from .output import print_header

        env_config = load_env_file()
        api_key = env_config.get("keys", {}).get("OPENROUTER_API_KEY")

        if not api_key or api_key.lower().startswith("paste_your"):
            print("  warning: No OpenRouter API key found. Add OPENROUTER_API_KEY to .env")
            print("  Get key at: https://openrouter.ai/keys")
            return

        agent.update_config("openrouter", api_key, "moonshotai/kimi-k2.5")
        print()
        print("  ok Switched to cheapest model: Kimi K2.5")
        print("    ($0.14 input / $0.28 output per 1M tokens)")
        print_header("openrouter", "moonshotai/kimi-k2.5")

    def _cmd_ratelimit(self, agent, args=None):
        """Set API call limit per turn (rate limiting tier)."""
        from .config import (
            DEFAULT_RATE_LIMIT_TIER,
            RATE_LIMIT_TIERS,
            load_settings_file,
            save_rate_limit_tier,
        )

        current_tier = load_settings_file().get("rate_limit_tier", DEFAULT_RATE_LIMIT_TIER)

        print()
        print("  Rate Limit - API calls allowed per turn:")
        print()

        tier_keys = list(RATE_LIMIT_TIERS.keys())
        for index, key in enumerate(tier_keys, 1):
            tier = RATE_LIMIT_TIERS[key]
            marker = " (current)" if key == current_tier else ""
            print(f"    {index}. {tier['label']} - {tier['description']}{marker}")
        print()

        try:
            choice = input(f"  Enter 1-{len(tier_keys)}: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Cancelled.")
            return

        try:
            index = int(choice) - 1
            if 0 <= index < len(tier_keys):
                selected_tier = tier_keys[index]
            else:
                print("  Invalid choice.")
                return
        except ValueError:
            print("  Invalid choice.")
            return

        save_rate_limit_tier(selected_tier)

        new_max = RATE_LIMIT_TIERS[selected_tier]["max_calls"]
        agent.protection.rate_limiter.max_calls_per_turn = new_max
        agent.config.max_api_calls_per_turn = new_max

        print()
        print(f"  ok Rate limit set to: {RATE_LIMIT_TIERS[selected_tier]['label']}")
        print(f"    {new_max} API calls per turn (saved for future sessions)")

    def _cmd_theme(self, agent, args=None):
        """Pick and persist the UI color palette."""
        from . import ui
        from .theme import (
            PALETTES,
            load_active_palette_name,
            save_palette_selection,
        )

        current = load_active_palette_name()
        palette_keys = list(PALETTES.keys())

        print()
        print("  UI Palette:")
        print()
        for index, key in enumerate(palette_keys, 1):
            palette = PALETTES[key]
            marker = " (current)" if key == current else ""
            print(f"    {index}. {palette['label']}{marker}")
            print(f"       {palette['description']}")
            print(f"       {_render_palette_swatch(palette['colors'])}")
            print()

        try:
            raw = input(f"  Enter 1-{len(palette_keys)} (p=preview tool calls): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n  Cancelled.")
            return

        if raw == "p":
            _preview_all_palettes()
            return

        try:
            index = int(raw) - 1
            if not 0 <= index < len(palette_keys):
                print("  Invalid choice.")
                return
            selected_key = palette_keys[index]
        except ValueError:
            print("  Invalid choice.")
            return

        save_palette_selection(selected_key)
        ui.reload_theme()

        print()
        print(f"  ok Palette set to: {PALETTES[selected_key]['label']}")
        print("    (saved — applies now and on future launches)")

    def _cmd_font(self, agent, args=None):
        """Pick and persist the font/glyph profile."""
        from .theme import (
            FONT_PROFILES,
            RECOMMENDED_FONTS,
            load_active_font_profile_name,
            save_font_profile_selection,
        )

        current = load_active_font_profile_name()
        profile_keys = list(FONT_PROFILES.keys())

        print()
        print("  Font / Glyph Profile:")
        print("  (This controls which text glyphs RadSim uses — your terminal")
        print("   font controls how they render.)")
        print()
        for index, key in enumerate(profile_keys, 1):
            profile = FONT_PROFILES[key]
            marker = " (current)" if key == current else ""
            glyphs = profile["glyphs"]
            sample = (
                f"{glyphs['prompt']} prompt  "
                f"{glyphs['diff_add']} add  "
                f"{glyphs['diff_del']} del  "
                f"{glyphs['ellipsis']} ellipsis"
            )
            print(f"    {index}. {profile['label']}{marker}")
            print(f"       {profile['description']}")
            print(f"       Sample: {sample}")
            print()

        try:
            raw = input(f"  Enter 1-{len(profile_keys)} (f=recommended fonts): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n  Cancelled.")
            return

        if raw == "f":
            print()
            print("  Recommended terminal fonts:")
            print()
            for name, desc in RECOMMENDED_FONTS:
                print(f"    • {name}")
                print(f"      {desc}")
            print()
            print("  Install one and set it in your terminal preferences,")
            print("  then run /font again and pick the 'Nerd Font' profile.")
            return

        try:
            index = int(raw) - 1
            if not 0 <= index < len(profile_keys):
                print("  Invalid choice.")
                return
            selected_key = profile_keys[index]
        except ValueError:
            print("  Invalid choice.")
            return

        save_font_profile_selection(selected_key)

        print()
        print(f"  ok Font profile set to: {FONT_PROFILES[selected_key]['label']}")
        print("    (saved — applies on future launches)")

    def _cmd_animations(self, agent, args=None):
        """Pick and persist the animation level."""
        from .theme import (
            ANIMATION_LEVELS,
            load_active_animation_level,
            save_animation_level,
        )

        current = load_active_animation_level()
        descriptions = {
            "full": "Animated spinner + in-place tool updates",
            "subtle": "Static spinner label + in-place tool updates",
            "off": "No spinner output, final tool line only",
        }

        print()
        print("  Animation Level:")
        print()
        for index, level in enumerate(ANIMATION_LEVELS, 1):
            marker = " (current)" if level == current else ""
            print(f"    {index}. {level}{marker}")
            print(f"       {descriptions[level]}")
        print()

        try:
            raw = input(f"  Enter 1-{len(ANIMATION_LEVELS)} [2 = subtle]: ").strip() or "2"
        except (KeyboardInterrupt, EOFError):
            print("\n  Cancelled.")
            return

        try:
            index = int(raw) - 1
            if not 0 <= index < len(ANIMATION_LEVELS):
                print("  Invalid choice.")
                return
            selected_level = ANIMATION_LEVELS[index]
        except ValueError:
            print("  Invalid choice.")
            return

        save_animation_level(selected_level)

        print()
        print(f"  ok Animation level set to: {selected_level}")
        print("    (saved — applies now and on future launches)")

    def _cmd_commands(self, agent):
        """List all available commands."""
        print()
        print("  ═══ ALL COMMANDS ═══")
        print()

        categories = {
            "Navigation": [
                ("/help", "Show help menu"),
                ("/tools", "List available tools"),
                ("/commands", "This list"),
            ],
            "Provider/Model": [
                ("/switch", "Quick switch provider/model"),
                ("/config", "Full configuration setup"),
                ("/free", "Switch to free model"),
            ],
            "Appearance": [
                ("/theme", "Pick UI color palette"),
                ("/font", "Pick font / glyph profile"),
                ("/animations", "Set animation level"),
            ],
            "Conversation": [
                ("/clear", "Clear conversation history"),
                ("/new", "Fresh conversation + reset limits"),
            ],
            "Learning & Feedback": [
                ("/good, /+", "Mark response as good"),
                ("/improve, /-", "Mark for improvement"),
                ("/stats", "Learning statistics"),
                ("/report", "Full learning report"),
                ("/preferences", "Show learned preferences"),
                ("/trust", "Show learned confirmation trust"),
                ("/trust reset", "Reset learned confirmation trust"),
                ("/audit", "Audit what was learned"),
                ("/reset <cat>", "Reset learning data"),
            ],
            "Customization": [
                ("/skill add <text>", "Add custom instruction"),
                ("/skill list", "List active skills"),
                ("/skill remove <n>", "Remove a skill"),
                ("/skill templates", "Show skill examples"),
            ],
            "Memory": [
                ("/memory remember", "Save to persistent memory"),
                ("/memory forget", "Remove from memory"),
                ("/memory list", "Show all memories"),
            ],
            "Self-Modification": [
                ("/selfmod path", "Show source directory"),
                ("/selfmod prompt", "View custom prompt"),
                ("/selfmod list", "List source files"),
            ],
            "Agent Config": [
                ("/settings", "View/change agent settings"),
                ("/settings <key> <val>", "Toggle a setting"),
                ("/settings security_level", "Set security preset"),
                ("/evolve", "Review self-improvement proposals"),
                ("/evolve analyze", "Generate new proposals"),
                ("/evolve history", "View past decisions"),
                ("/evolve stats", "Improvement statistics"),
            ],
            "Modes": [
                ("/teach, /t", "Toggle Teach Me mode"),
                ("/awake", "Toggle stay-awake (macOS)"),
                ("/modes", "List all modes"),
            ],
            "Notifications": [
                ("/telegram setup", "Configure Telegram bot"),
                ("/telegram listen", "Toggle receive on/off"),
                ("/telegram test", "Send a test message"),
                ("/telegram send", "Send a message"),
                ("/telegram status", "Check configuration"),
            ],
            "Code Analysis": [
                ("/complexity", "Complexity budget & scoring"),
                ("/complexity budget <N>", "Set complexity budget"),
                ("/stress", "Adversarial code review"),
                ("/stress <file>", "Stress test a single file"),
                ("/archaeology", "Find dead code & zombies"),
                ("/archaeology clean", "Interactive cleanup"),
            ],
            "Session": [
                ("/exit, /quit", "Exit RadSim"),
                ("/kill, /stop", "EMERGENCY: Kill agent immediately"),
                ("/reset budget", "Reset token budget limits"),
                ("/setup", "Re-run setup wizard"),
            ],
        }

        for category, commands in categories.items():
            print(f"  {category}:")
            for command, description in commands:
                print(f"    {command:<18} {description}")
            print()

    def _cmd_teach(self, agent):
        """Toggle Teach Me mode."""
        from .modes import toggle_mode

        is_active, message = toggle_mode("teach")
        print()
        if is_active:
            print("  ok " + message)
            print("  The agent will now teach in EVERY response — text and code.")
            print("  [teach] annotations explain HOW and WHY in all responses.")
            print("  Code annotations appear as inline magenta comments.")
            print("  Use /teach again to turn off.")
        else:
            print("  ok " + message)
            print("  Back to normal execution mode.")
        print()

    def _cmd_awake(self, agent):
        """Toggle stay-awake mode (caffeinate)."""
        import platform

        from .modes import toggle_mode

        if platform.system() != "Darwin":
            print_info("Awake mode is only available on macOS.")
            return

        is_active, message = toggle_mode("awake")
        print()
        if is_active:
            print("  ok " + message)
            print("  macOS sleep prevention is active (display, idle, system).")
            print("  Your Mac will stay awake while RadSim is running.")
            print("  Use /awake again to turn off.")
        else:
            print("  ok " + message)
            print("  macOS can now sleep normally.")
        print()

    def _cmd_modes(self, agent):
        """List all available modes."""
        from .modes import get_mode_manager

        manager = get_mode_manager()
        modes = manager.get_all_modes()
        active = manager.get_active_modes()

        print()
        print("  ═══ AVAILABLE MODES ═══")
        print()
        print("  Mode          Status    Shortcut        Description")
        print("  " + "─" * 60)

        for mode in modes:
            status = "ON " if mode.name in active else "OFF"
            print(f"  {mode.name:<12}  {status:<8}  {mode.shortcut:<14}  {mode.description}")

        print()
        print("  Toggle with: /teach or Shift+T (in supported terminals)")
        print()

    def _cmd_show(self, agent, args=None):
        """Show the last written file content."""
        from .output import get_last_written_file, print_code_content

        last_file = get_last_written_file()
        if not last_file.get("content"):
            print()
            print("  No file has been written yet this session.")
            print("  Use /show after the agent writes a file to see its content.")
            print("  Or type S to see all session files.")
            print()
            return

        content = last_file.get("display_content") or last_file["content"]
        has_teach = last_file.get("display_content") is not None

        print()
        print(f"  Last written file: {last_file['path']}")
        print()
        print_code_content(
            content,
            last_file["path"],
            max_lines=0,
            collapsed=False,
            highlight_teach=has_teach,
        )
        print()


def _hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _bg_swatch(hex_color, width=4):
    """Return a true-color background swatch string."""
    r, g, b = _hex_to_rgb(hex_color)
    return f"\033[48;2;{r};{g};{b}m{' ' * width}\033[0m"


def _render_palette_swatch(colors):
    """One-line swatch showing all 7 palette colors."""
    order = ["primary", "accent", "success", "warning", "error", "muted", "subtle"]
    return "".join(_bg_swatch(colors[name]) for name in order)


def _preview_all_palettes():
    """Print a tool-call sample rendered in every palette for comparison."""
    from .theme import PALETTES

    print()
    print("  Preview — same tool-call list rendered in each palette:")
    print()
    for _key, palette in PALETTES.items():
        colors = palette["colors"]
        print(f"    {palette['label']}")
        print(f"    {_render_palette_swatch(colors)}")
        _print_sample_tool_calls(colors)
        print()


def _print_sample_tool_calls(colors):
    """Print a few mock tool-call lines in the given palette."""
    from .terminal import supports_color
    from .theme import glyph

    if not supports_color():
        print("      (colors not supported in this terminal)")
        return

    def fg(hex_color):
        r, g, b = _hex_to_rgb(hex_color)
        return f"\033[38;2;{r};{g};{b}m"

    reset = "\033[0m"
    dim = "\033[2m"

    rows = [
        (colors["primary"], "read", "src/auth.py", f"142 lines{dim}    34ms{reset}"),
        (colors["primary"], "grep", '"TODO" in radsim/**', f"8 matches{dim}    12ms{reset}"),
        (
            colors["accent"],
            "write",
            "src/auth.py",
            f"{fg(colors['success'])}{glyph('diff_add')}24{reset} {fg(colors['error'])}{glyph('diff_del')}7{reset}",
        ),
        (
            colors["warning"],
            "shell",
            "pytest tests/auth",
            f"exit 0{dim}       2.1s{reset}",
        ),
    ]
    for color_hex, verb, argument, result in rows:
        tag = f"[{verb}]"
        padding = " " * max(10 - len(tag), 1)
        line = (
            f"      {fg(colors['muted'])}[{reset}"
            f"{fg(color_hex)}{verb}{reset}"
            f"{fg(colors['muted'])}]{padding}{reset}"
            f"{fg(colors['muted'])}{argument:<34}{reset}"
            f"{result}"
        )
        print(line)
