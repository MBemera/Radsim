"""Core slash-command handlers."""

import os
import sys

from .config import setup_config
from .output import print_error, print_help, print_info, print_warning


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
        print("  🛑 EMERGENCY STOP")
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

    def _cmd_reload(self, agent, args=None):
        """Reload runtime state.

        Forms:
          /reload            -> auto (restart if required, else soft)
          /reload auto       -> auto
          /reload soft       -> clear runtime caches only
          /reload restart    -> re-exec the process
          /reload hard       -> alias of restart
        """
        mode = (args[0].lower() if args else "auto")

        if mode not in {"auto", "soft", "restart", "hard"}:
            print_error(
                "Unknown /reload mode. Use: /reload [auto|soft|restart|hard]"
            )
            return

        if mode == "auto":
            mode = "restart" if getattr(agent, "_restart_required", False) else "soft"

        if mode == "soft":
            _reload_soft(agent)
            return

        _reload_restart(agent)

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
        from .config import PROVIDER_MODELS, load_env_file
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
                print("  ⚠ No GOOGLE_CLOUD_PROJECT found. Add it to .env first.")
                return
            location = env_config.get("keys", {}).get("GOOGLE_CLOUD_LOCATION", "us-central1")
            api_key = f"{project_id}:{location}"
        else:
            env_var = PROVIDER_ENV_VARS.get(provider, "RADSIM_API_KEY")
            api_key = env_config.get("keys", {}).get(env_var)

            if not api_key or api_key.lower().startswith("paste_your"):
                print(f"  ⚠ No API key found for {provider}. Add it to .env first.")
                return

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

        agent.update_config(provider, api_key, model)
        print()
        print(f"  ✓ Switched to {provider} / {model}")
        print_header(provider, model)

    def _cmd_free(self, agent):
        """Instantly switch to cheapest OpenRouter model (Kimi K2.5)."""
        from .config import load_env_file
        from .output import print_header

        env_config = load_env_file()
        api_key = env_config.get("keys", {}).get("OPENROUTER_API_KEY")

        if not api_key or api_key.lower().startswith("paste_your"):
            print("  ⚠ No OpenRouter API key found. Add OPENROUTER_API_KEY to .env")
            print("  Get key at: https://openrouter.ai/keys")
            return

        agent.update_config("openrouter", api_key, "moonshotai/kimi-k2.5")
        print()
        print("  ✓ Switched to cheapest model: Kimi K2.5")
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
        print(f"  ✓ Rate limit set to: {RATE_LIMIT_TIERS[selected_tier]['label']}")
        print(f"    {new_max} API calls per turn (saved for future sessions)")

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
            print("  ✓ " + message)
            print("  The agent will now teach in EVERY response — text and code.")
            print("  🎓 annotations explain HOW and WHY in all responses.")
            print("  Code annotations appear as inline magenta comments.")
            print("  Use /teach again to turn off.")
        else:
            print("  ✓ " + message)
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
            print("  ✓ " + message)
            print("  macOS sleep prevention is active (display, idle, system).")
            print("  Your Mac will stay awake while RadSim is running.")
            print("  Use /awake again to turn off.")
        else:
            print("  ✓ " + message)
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


def _reload_soft(agent):
    """Clear runtime caches so the next turn rebuilds prompt fragments."""
    if hasattr(agent, "refresh_runtime_state"):
        agent.refresh_runtime_state()

    if getattr(agent, "_restart_required", False):
        reason = getattr(agent, "_restart_reason", None) or "core Python source changed"
        print_warning(
            "Soft reload done, but a restart is still required "
            f"({reason}). Run /reload restart to apply Python source changes."
        )
        return

    print_info(
        "Runtime caches cleared. Updated prompt, skills, memory, and custom "
        "instructions will apply on the next turn."
    )


def _reload_restart(agent):
    """Re-exec the current RadSim process cleanly."""
    if hasattr(agent, "refresh_runtime_state"):
        agent.refresh_runtime_state()

    print_info("Restarting RadSim...")
    sys.stdout.flush()
    sys.stderr.flush()

    python = sys.executable
    argv = [python] + sys.argv
    os.execv(python, argv)
