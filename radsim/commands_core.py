"""Core slash-command handlers."""

import logging
import sys
from typing import Any

from .config import setup_config
from .output import (
    print_block,
    print_help,
    print_info,
    print_labeled_values,
    print_numbered_options,
    print_titled_block,
)

logger = logging.getLogger(__name__)


def _append_input_token_rows(rows: list[tuple[str, str]], usage: dict[str, Any]) -> None:
    """Break input tokens into uncached and cached so caching is visible.

    Providers report total input inclusive of cached reads, so a single
    "input tokens" figure hides whether the prefix cache is working at all.
    """
    input_tokens = usage.get("input_tokens", 0)
    cache_read_tokens = usage.get("cache_read_input_tokens", 0)
    cache_write_tokens = usage.get("cache_write_input_tokens", 0)

    rows.append(("Input tokens:", f"{input_tokens:,}"))
    if cache_read_tokens + cache_write_tokens > input_tokens:
        rows.append(("  Uncached:", "not reported (cached exceeds total input)"))
        rows.append(("  Cache reads:", f"{cache_read_tokens:,}"))
        rows.append(("  Cache writes:", f"{cache_write_tokens:,}"))
        return

    uncached_tokens = input_tokens - cache_read_tokens - cache_write_tokens
    rows.append(("  Uncached:", f"{uncached_tokens:,}"))
    rows.append(("  Cache reads:", f"{cache_read_tokens:,}{_cache_share(cache_read_tokens, input_tokens)}"))
    rows.append(("  Cache writes:", f"{cache_write_tokens:,}"))


def _cache_share(cache_read_tokens: int, input_tokens: int) -> str:
    """Return the cached share of input, or nothing when it is unknowable."""
    if input_tokens <= 0:
        return ""
    return f"  ({cache_read_tokens / input_tokens * 100:.0f}% of input)"


def _append_reported_cost(rows: list[tuple[str, str]], usage: dict[str, Any]) -> None:
    """Append provider spend without presenting partial data as exact."""
    reported_requests = usage.get("reported_cost_requests", 0)
    if not reported_requests:
        return

    request_count = usage.get("request_count", 0)
    reported_cost = usage.get("reported_cost_usd", 0.0)
    if reported_requests == request_count:
        rows.append(("Actual cost:", f"${reported_cost:.4f}  (provider reported)"))
        return

    coverage = f"{reported_requests}/{request_count} requests"
    rows.append(("Reported cost:", f"${reported_cost:.4f}  (partial: {coverage})"))


def _append_estimated_cost(
    rows: list[tuple[str, str]],
    usage: dict[str, Any],
    model: str,
    provider: str | None,
) -> None:
    """Append a cache-aware catalogue estimate with explicit provenance."""
    from .config import get_model_pricing
    from .pricing import describe_pricing_source, estimate_usage_cost

    pricing = get_model_pricing(model, provider)
    if pricing is None:
        rows.append(("Est. cost:", "n/a (no pricing data for this model)"))
        return
    estimate = estimate_usage_cost(usage, pricing)
    if estimate.total_usd is None:
        rows.append(("Est. cost:", f"n/a ({estimate.unavailable_reason})"))
        return
    cache_cost = estimate.cache_read_usd + estimate.cache_write_usd
    source = describe_pricing_source(pricing)
    rows.append(("Est. cost:", f"${estimate.total_usd:.4f}  (catalogue estimate)"))
    rows.append(("  Uncached in:", f"${estimate.uncached_input_usd:.4f}"))
    rows.append(("  Cached in:", f"${cache_cost:.4f}"))
    rows.append(("  Output:", f"${estimate.output_usd:.4f}"))
    rows.append(("  Pricing:", source))


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

    def _cmd_prompt_stats(self, agent):
        """Show runtime prompt size by layer."""
        from .prompts import get_prompt_stats

        stats = get_prompt_stats()
        lines = [
            "  Prompt Stats",
            f"  Total: {stats['total_chars']:,} chars (~{stats['approx_tokens']:,} tokens)",
            "",
        ]
        lines.extend(
            f"  - {layer['name']:<18} {layer['chars']:>7,} chars  "
            f"~{layer['approx_tokens']:>6,} tokens"
            for layer in stats["layers"]
        )
        print_block(lines)

    def _cmd_clear(self, agent):
        """Clear the conversation and reset session state for a fresh start."""
        from .background import reset_job_manager
        from .output import clear_session_files
        from .todo import reset_tracker

        agent.reset()
        reset_tracker()
        reset_job_manager()
        # The subagent provider/model selection is user configuration, not
        # session state, so /clear leaves it alone.
        agent._injected_job_ids = set()
        if hasattr(agent, "protection"):
            agent.protection.rate_limiter.reset()
            agent.protection.budget_guard.reset()
        clear_session_files()
        print_info("Fresh start: conversation, tasks, background jobs, and limits reset.")

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

        print_block(("  EMERGENCY STOP", "  Terminating all agent operations immediately..."))
        os._exit(1)

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

    def _cmd_login(self, agent, args=None):
        """Log in to a provider from inside the REPL.

        Usage:
          /login                → pick from a numbered menu
          /login <provider>     → API-key wizard for that provider
        """
        from . import login as login_module
        from .login import PROVIDERS

        provider = (args[0].lower() if args else "").strip()
        if not provider:
            keys = list(PROVIDERS)
            print_numbered_options("Log in - Select provider:", [PROVIDERS[name]["label"] for name in keys])
            try:
                choice = input(f"  Enter 1-{len(keys)}: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n  Cancelled.")
                return
            try:
                provider = keys[int(choice) - 1]
            except (ValueError, IndexError):
                print("  Invalid choice.")
                return

        if provider not in PROVIDERS:
            lines = (f"  Unknown provider: {provider}", f"  Choices: {', '.join(PROVIDERS)}")
            print_block(lines, blank_before=False, blank_after=False)
            return

        login_module.run_login(provider)

        # If the user just configured a different provider, hot-swap to it.
        from .config import load_env_file

        env_config = load_env_file()
        new_keys = env_config.get("keys", {})
        env_var = PROVIDERS[provider]["env_var"]
        if env_var and new_keys.get(env_var):
            agent.update_config(provider, new_keys[env_var], None)

    def _cmd_logout(self, agent, args=None):
        """Remove a provider's API key and any cached OAuth tokens."""
        from . import login as login_module
        from .login import PROVIDERS

        provider = (args[0].lower() if args else "").strip()
        if not provider:
            keys = list(PROVIDERS)
            print_numbered_options("Log out - Select provider:", [PROVIDERS[name]["label"] for name in keys])
            try:
                choice = input(f"  Enter 1-{len(keys)}: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n  Cancelled.")
                return
            try:
                provider = keys[int(choice) - 1]
            except (ValueError, IndexError):
                print("  Invalid choice.")
                return

        if provider not in PROVIDERS:
            print(f"  Unknown provider: {provider}")
            return

        login_module.run_logout(provider)

    def _cmd_switch(self, agent, args=None):
        """Quick switch provider/model without full setup."""
        from .config import (
            PROVIDER_MODELS,
            _maybe_prompt_reasoning_effort,
            _select_openrouter_model,
            load_env_file,
        )
        from .output import print_header

        print_numbered_options("Quick Switch - Select provider:", ("OpenRouter", "GPT-5 (OpenAI)", "Claude (Anthropic)"))

        try:
            choice = input("  Enter 1-3: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Cancelled.")
            return

        provider_map = {"1": "openrouter", "2": "openai", "3": "claude"}
        provider = provider_map.get(choice)

        if not provider:
            print("  Invalid choice.")
            return

        from .config import PROVIDER_ENV_VARS

        env_config = load_env_file()

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
            models = PROVIDER_MODELS[provider]
            print_numbered_options("Select model:", [model_name for _, model_name in models])

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
        print_block((f"  ok Switched to {provider} / {model}",), blank_after=False)
        print_header(provider, model)

    CHEAPEST_OPENROUTER_MODEL = "deepseek/deepseek-v4-flash"

    def _cmd_free(self, agent):
        """Instantly switch to the cheapest OpenRouter model."""
        from .config import get_model_pricing, load_env_file
        from .output import print_header

        env_config = load_env_file()
        api_key = env_config.get("keys", {}).get("OPENROUTER_API_KEY")

        if not api_key or api_key.lower().startswith("paste_your"):
            lines = (
                "  warning: No OpenRouter API key found. Add OPENROUTER_API_KEY to .env",
                "  Get key at: https://openrouter.ai/keys",
            )
            print_block(lines, blank_before=False, blank_after=False)
            return

        model = self.CHEAPEST_OPENROUTER_MODEL
        agent.update_config("openrouter", api_key, model)

        pricing = get_model_pricing(model, "openrouter")
        lines = [f"  ok Switched to cheapest model: {model}"]
        if pricing:
            lines.append(
                f"    (${pricing.input_per_million_usd} input / "
                f"${pricing.output_per_million_usd} output per 1M tokens)"
            )
        print_block(lines, blank_after=False)
        print_header("openrouter", model)

    def _cmd_ratelimit(self, agent, args=None):
        """Set API call limit per turn (rate limiting tier)."""
        from .config import (
            DEFAULT_RATE_LIMIT_TIER,
            RATE_LIMIT_TIERS,
            load_settings_file,
            save_rate_limit_tier,
        )

        current_tier = load_settings_file().get("rate_limit_tier", DEFAULT_RATE_LIMIT_TIER)

        tier_keys = list(RATE_LIMIT_TIERS.keys())
        print_numbered_options(
            "Rate Limit - API calls allowed per turn:",
            [
                f"{RATE_LIMIT_TIERS[key]['label']} - {RATE_LIMIT_TIERS[key]['description']}"
                f"{' (current)' if key == current_tier else ''}"
                for key in tier_keys
            ],
        )

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

        lines = (
            f"  ok Rate limit set to: {RATE_LIMIT_TIERS[selected_tier]['label']}",
            f"    {new_max} API calls per turn (saved for future sessions)",
        )
        print_block(lines, blank_after=False)

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

        print_numbered_options(
            "UI Palette:",
            [
                (
                    f"{PALETTES[key]['label']}{' (current)' if key == current else ''}",
                    PALETTES[key]["description"],
                    _render_palette_swatch(PALETTES[key]["colors"]),
                )
                for key in palette_keys
            ],
            blank_between=True,
        )

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

        lines = (f"  ok Palette set to: {PALETTES[selected_key]['label']}", "    (saved — applies now and on future launches)")
        print_block(lines, blank_after=False)

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

        def describe_font_profile(key):
            profile = FONT_PROFILES[key]
            glyphs = profile["glyphs"]
            sample = (
                f"{glyphs['prompt']} prompt  {glyphs['diff_add']} add  "
                f"{glyphs['diff_del']} del  {glyphs['ellipsis']} ellipsis"
            )
            marker = " (current)" if key == current else ""
            return f"{profile['label']}{marker}", profile["description"], f"Sample: {sample}"

        print_numbered_options(
            "Font / Glyph Profile:",
            [describe_font_profile(key) for key in profile_keys],
            introduction=(
                "  (This controls which text glyphs RadSim uses — your terminal",
                "   font controls how they render.)",
            ),
            blank_between=True,
        )

        try:
            raw = input(f"  Enter 1-{len(profile_keys)} (f=recommended fonts): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n  Cancelled.")
            return

        if raw == "f":
            font_lines = [line for name, desc in RECOMMENDED_FONTS for line in (f"    • {name}", f"      {desc}")]
            lines = (
                "  Recommended terminal fonts:", "", *font_lines, "",
                "  Install one and set it in your terminal preferences,",
                "  then run /font again and pick the 'Nerd Font' profile.",
            )
            print_block(lines, blank_after=False)
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

        lines = (f"  ok Font profile set to: {FONT_PROFILES[selected_key]['label']}", "    (saved — applies on future launches)")
        print_block(lines, blank_after=False)

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

        print_numbered_options(
            "Animation Level:",
            [
                (
                    f"{level}{' (current)' if level == current else ''}",
                    descriptions[level],
                )
                for level in ANIMATION_LEVELS
            ],
        )

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

        lines = (f"  ok Animation level set to: {selected_level}", "    (saved — applies now and on future launches)")
        print_block(lines, blank_after=False)

    def _cmd_teach(self, agent):
        """Toggle Teach Me mode."""
        from .modes import toggle_mode

        is_active, message = toggle_mode("teach")
        if is_active:
            lines = (
                "  ok " + message,
                "  The agent will now teach in EVERY response — text and code.",
                "  [teach] annotations explain HOW and WHY in all responses.",
                "  Code annotations appear as inline magenta comments.",
                "  Use /teach again to turn off.",
            )
        else:
            lines = ("  ok " + message, "  Back to normal execution mode.")
        print_block(lines)

    def _cmd_awake(self, agent):
        """Toggle stay-awake mode (caffeinate)."""
        import platform

        from .modes import toggle_mode

        if platform.system() != "Darwin":
            print_info("Awake mode is only available on macOS.")
            return

        is_active, message = toggle_mode("awake")
        if is_active:
            lines = (
                "  ok " + message,
                "  macOS sleep prevention is active (display, idle, system).",
                "  Your Mac will stay awake while RadSim is running.",
                "  Use /awake again to turn off.",
            )
        else:
            lines = ("  ok " + message, "  macOS can now sleep normally.")
        print_block(lines)

    def _cmd_modes(self, agent):
        """List all available modes."""
        from .modes import get_mode_manager

        manager = get_mode_manager()
        modes = manager.get_all_modes()
        active = manager.get_active_modes()

        mode_lines = [
            f"  {mode.name:<12}  {'ON ' if mode.name in active else 'OFF':<8}  "
            f"{mode.shortcut:<14}  {mode.description}"
            for mode in modes
        ]
        print_titled_block(
            "AVAILABLE MODES",
            ("  Mode          Status    Shortcut        Description", "  " + "─" * 60, *mode_lines),
            footer=("  Toggle with: /teach or Shift+T (in supported terminals)",),
        )

    def _cmd_show(self, agent, args=None):
        """Show the last written file content."""
        from .output import get_last_written_file, print_code_content

        last_file = get_last_written_file()
        if not last_file.get("content"):
            lines = (
                "  No file has been written yet this session.",
                "  Use /show after the agent writes a file to see its content.",
                "  Or type S to see all session files.",
            )
            print_block(lines)
            return

        content = last_file.get("display_content") or last_file["content"]
        has_teach = last_file.get("display_content") is not None

        print_block((f"  Last written file: {last_file['path']}",))
        print_code_content(
            content,
            last_file["path"],
            max_lines=0,
            collapsed=False,
            highlight_teach=has_teach,
        )
        print()

    def _cmd_usage(self, agent):
        """Show session token usage and estimated cost."""
        usage = agent.usage_stats
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        model = agent.config.model

        rows = [("Model:", model)]
        _append_input_token_rows(rows, usage)
        rows.extend(
            [
                ("Output tokens:", f"{output_tokens:,}"),
                ("Reasoning:", f"{usage.get('reasoning_output_tokens', 0):,}"),
                ("Total tokens:", f"{input_tokens + output_tokens:,}"),
            ]
        )
        _append_reported_cost(rows, usage)
        _append_estimated_cost(
            rows,
            usage,
            model,
            getattr(agent.config, "provider", None),
        )
        print_labeled_values(rows, label_width=16)

    def _cmd_copy(self, agent, args=None):
        """Copy the last response, code block, or written file to the clipboard."""
        from .output import get_last_written_file

        target = args[0].lower() if args else "response"
        if target == "code":
            text = _extract_last_code_block(getattr(agent, "_last_response", ""))
            label = "last code block"
        elif target == "file":
            text = (get_last_written_file() or {}).get("content", "")
            label = "last written file"
        else:
            text = getattr(agent, "_last_response", "")
            label = "last response"

        if not text:
            print_info(f"Nothing to copy — no {label} yet.")
            return

        copied, error = _copy_to_clipboard(text)
        if copied:
            print_info(f"Copied {label} to clipboard ({len(text):,} characters).")
        else:
            from .output import print_error

            print_error(f"Clipboard copy failed: {error}")

    def _cmd_export(self, agent, args=None):
        """Export the conversation to a markdown file in the project."""
        import time as time_module

        from .output import print_error
        from .tools.validation import validate_path

        filename = (
            args[0] if args else f"radsim-conversation-{time_module.strftime('%Y%m%d-%H%M%S')}.md"
        )
        if not filename.endswith(".md"):
            filename += ".md"

        is_safe, path, error = validate_path(filename)
        if not is_safe:
            print_error(error)
            return
        if path.exists():
            print_error(f"{filename} already exists — pass a different name.")
            return

        markdown = _conversation_to_markdown(agent.messages, agent.config.model)
        if not markdown:
            print_info("Nothing to export yet.")
            return

        path.write_text(markdown)
        print_info(f"Exported {len(agent.messages)} messages to {path.name}")

    def _cmd_undo(self, agent, args=None):
        """Restore files to their state before the last agent change."""
        from .output import print_error, print_success, print_warning
        from .safety import ask_confirmation
        from .undo import list_checkpoints, undo_last

        if args and args[0].lower() == "list":
            checkpoints = list_checkpoints()
            if not checkpoints:
                print()
                print_info("No checkpoints recorded yet.")
                return
            print_block(f"  {line}" for line in checkpoints)
            print_info("/undo restores the most recent checkpoint.")
            return

        checkpoints = list_checkpoints()
        if not checkpoints:
            print_info("Nothing to undo — no checkpoints recorded yet.")
            return

        print_info(f"Will restore: {checkpoints[-1]}")
        if ask_confirmation("  Undo this change?") != "yes":
            print_info("Cancelled.")
            return

        result = undo_last()
        if not result["success"]:
            print_error(result["error"])
            return
        for restored_path in result["restored"]:
            print_success(f"Restored: {restored_path}")
        for deleted_path in result["deleted"]:
            print_success(f"Removed (did not exist before): {deleted_path}")
        for skipped in result["skipped"]:
            print_warning(f"Skipped: {skipped}")
        if result["restored"] or result["deleted"]:
            from .trust_bandit_integration import record_matched_revert

            record_matched_revert(result.get("trust_decision_id"), config=agent.config)
        try:
            from .agent_config import get_agent_config_manager
            from .learning import record_revert

            if get_agent_config_manager().get("learning.enabled", True):
                record_revert(
                    summary=(
                        f"User reverted {result.get('tool') or 'the last change'} "
                        f"from {result.get('time') or 'an earlier task'}"
                    )
                )
        except Exception:
            logger.debug("Recording the revert for learning failed", exc_info=True)


def _extract_last_code_block(text):
    """Return the contents of the last fenced code block in a response."""
    import re

    blocks = re.findall(r"```[^\n]*\n(.*?)```", text or "", re.DOTALL)
    return blocks[-1].strip() if blocks else ""


def _copy_to_clipboard(text):
    """Copy text using the platform clipboard tool.

    Returns:
        Tuple of (success, error_message).
    """
    import platform
    import shutil
    import subprocess

    system = platform.system()
    if system == "Darwin":
        command = ["pbcopy"]
    elif system == "Windows":
        command = ["clip"]
    elif shutil.which("xclip"):
        command = ["xclip", "-selection", "clipboard"]
    elif shutil.which("xsel"):
        command = ["xsel", "--clipboard", "--input"]
    else:
        return False, "No clipboard tool found (install xclip or xsel)"

    try:
        subprocess.run(command, input=text.encode("utf-8"), check=True, timeout=10)
        return True, None
    except (subprocess.SubprocessError, OSError) as error:
        return False, str(error)


def _conversation_to_markdown(messages, model):
    """Render the internal message history as readable markdown."""
    import time as time_module

    if not messages:
        return ""

    lines = [
        "# RadSim Conversation",
        f"*Exported {time_module.strftime('%Y-%m-%d %H:%M:%S')} — model: {model}*",
        "",
    ]
    for message in messages:
        role = message.get("role", "unknown").capitalize()
        content = message.get("content", "")
        rendered = _message_content_to_markdown(content)
        if rendered:
            lines.extend([f"## {role}", "", rendered, ""])
    return "\n".join(lines)


def _message_content_to_markdown(content):
    """Flatten one message's content blocks to markdown text."""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")
        if block_type == "text":
            parts.append(block.get("text", "").strip())
        elif block_type == "tool_use":
            parts.append(f"*[tool call: {block.get('name', 'unknown')}]*")
        elif block_type == "tool_result":
            parts.append("*[tool result omitted]*")
        elif block_type == "image":
            parts.append("*[image attached]*")
    return "\n\n".join(part for part in parts if part)


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

    print_block(("  Preview — same tool-call list rendered in each palette:",))
    for _key, palette in PALETTES.items():
        colors = palette["colors"]
        lines = (f"    {palette['label']}", f"    {_render_palette_swatch(colors)}")
        print_block(lines, blank_before=False, blank_after=False)
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
