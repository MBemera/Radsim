"""Slash command registry and handlers."""

import json
import sys

from .config import setup_config
from .output import print_help, print_info


class CommandRegistry:
    """Registry for slash commands."""

    def __init__(self):
        self.commands = {}
        self._register_defaults()

    def register(self, names, handler, description=""):
        """Register a new command.

        Args:
            names: Command name or list of names (e.g., "/help" or ["/help", "/h"])
            handler: Function taking (agent, args) or (agent) as arguments
            description: Short description for help menu
        """
        if isinstance(names, str):
            names = [names]

        for name in names:
            name = name.lower()
            if not name.startswith("/"):
                name = "/" + name

            self.commands[name] = {
                "handler": handler,
                "description": description,
                "primary": names[0],  # To group aliases in help
            }

    def handle_input(self, user_input, agent):
        """Check if input is a command and execute it.

        Returns:
            bool: True if command was executed, False otherwise
        """
        parts = user_input.strip().split()
        if not parts:
            return False

        cmd_name = parts[0].lower()

        # Check explicit slash commands
        if cmd_name in self.commands:
            return self._execute(cmd_name, agent, parts[1:])

        # Check legacy commands without slash (exit, quit) - strictly for backward compat
        if cmd_name in ["exit", "quit"]:
            return self._execute("/exit", agent, parts[1:])

        return False

    def _execute(self, cmd_name, agent, args):
        """Execute the command handler."""
        handler = self.commands[cmd_name]["handler"]
        try:
            # support both func(agent) and func(agent, args)
            import inspect

            sig = inspect.signature(handler)
            if len(sig.parameters) == 1:
                result = handler(agent)
            else:
                result = handler(agent, args)

            return result is not False  # Return True unless handler explicitly returns False
        except (KeyboardInterrupt, EOFError):
            # Clean exit on Ctrl+C or EOF during any command
            print()
            print("  Cancelled.")
            return True
        except Exception as e:
            print_error(f"Command error: {e}")
            return True

    def _register_defaults(self):
        """Register default RadSim commands."""
        self.register(["/help", "/h", "/?"], self._cmd_help, "Show help and available commands")
        self.register(["/tools"], self._cmd_tools, "List all available tools")
        self.register(["/clear", "/c"], self._cmd_clear, "Clear conversation history")
        self.register(
            ["/config", "/provider", "/swap"], self._cmd_config, "Change provider or API key"
        )
        self.register(["/switch", "/model"], self._cmd_switch, "Quick switch provider/model")
        self.register(["/free"], self._cmd_free, "Switch to free OpenRouter model")
        self.register(["/exit", "/quit", "/q"], self._cmd_exit, "Exit RadSim")
        self.register(
            ["/kill", "/stop", "/abort"], self._cmd_kill, "EMERGENCY: Immediately stop agent"
        )
        self.register(
            ["/new", "/fresh"], self._cmd_new, "Start new conversation with fresh context"
        )
        self.register(["/setup", "/onboarding"], self._cmd_setup, "Re-run the setup wizard")

        # Learning commands
        self.register(
            ["/good", "/+"], self._cmd_good, "Mark last response as good (positive feedback)"
        )
        self.register(["/improve", "/-"], self._cmd_improve, "Mark last response for improvement")
        self.register(["/stats"], self._cmd_stats, "Show learning statistics")
        self.register(["/report"], self._cmd_report, "Export detailed learning report")
        self.register(["/audit"], self._cmd_audit, "Audit learned preferences")
        self.register(["/reset"], self._cmd_reset, "Reset learned data (usage: /reset <category>)")
        self.register(["/preferences", "/prefs"], self._cmd_preferences, "Show learned preferences")

        # Skill configuration
        self.register(
            ["/skill", "/skills"], self._cmd_skill, "Configure custom skills/instructions"
        )
        self.register(["/commands", "/cmds"], self._cmd_commands, "List all available commands")

        # Memory management
        self.register(
            ["/memory", "/mem"], self._cmd_memory, "Manage persistent memory"
        )

        # Mode toggles
        self.register(
            ["/teach", "/t"], self._cmd_teach, "Toggle Teach Me mode (explains while coding)"
        )
        self.register(["/modes"], self._cmd_modes, "List all available modes")
        self.register(
            ["/awake", "/caffeinate"], self._cmd_awake, "Toggle stay-awake mode (macOS)"
        )
        self.register(["/show"], self._cmd_show, "Show last written file content")

        # Self-modification
        self.register(
            ["/selfmod", "/self"], self._cmd_selfmod, "View/edit RadSim source and custom prompt"
        )

        # Telegram
        self.register(
            ["/telegram", "/tg"], self._cmd_telegram, "Configure Telegram notifications"
        )

        # Agent config & self-improvement
        self.register(
            ["/settings", "/set"], self._cmd_settings, "View/change agent settings"
        )
        self.register(
            ["/evolve", "/self-improve"], self._cmd_evolve, "Review self-improvement proposals"
        )

        # Code analysis tools
        self.register(
            ["/complexity", "/cx"], self._cmd_complexity, "Complexity budget & scoring"
        )
        self.register(
            ["/stress", "/adversarial"], self._cmd_stress, "Adversarial code review"
        )
        self.register(
            ["/archaeology", "/arch", "/dead"], self._cmd_archaeology, "Find dead code & zombies"
        )

        # Planning & panning
        self.register(
            ["/plan", "/p"], self._cmd_plan, "Structured plan-confirm-execute workflow"
        )
        self.register(
            ["/panning", "/pan"], self._cmd_panning, "Brain-dump processing & synthesis"
        )

    # --- Default Handlers ---

    def _cmd_help(self, agent):
        print_help()
        # Also print custom skills if any
        # (This is a simplified help, print_help in output.py is hardcoded currently)
        # We might want to dynamically list commands here later

    def _cmd_tools(self, agent):
        from .agent import print_tools_list

        print_tools_list()

    def _cmd_clear(self, agent):
        agent.reset()
        print_info("Conversation cleared.")

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

        # Force kill the current process (cross-platform)
        os._exit(1)

    def _cmd_new(self, agent):
        """Start a completely fresh conversation."""
        agent.reset()
        # Also reset the protection manager to clear rate limits
        if hasattr(agent, "protection"):
            agent.protection.rate_limiter.reset()
            agent.protection.budget_guard.reset()
        # Clear session file history
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

        # Check if we have an API key for this provider
        from .config import PROVIDER_ENV_VARS

        env_config = load_env_file()

        if provider == "vertex":
            # Vertex AI uses project ID + location
            project_id = env_config.get("keys", {}).get("GOOGLE_CLOUD_PROJECT")
            if not project_id or project_id.lower().startswith("paste_your"):
                print("  ⚠ No GOOGLE_CLOUD_PROJECT found. Add it to .env first.")
                return
            location = env_config.get("keys", {}).get(
                "GOOGLE_CLOUD_LOCATION", "us-central1"
            )
            api_key = f"{project_id}:{location}"
        else:
            env_var = PROVIDER_ENV_VARS.get(provider, "RADSIM_API_KEY")
            api_key = env_config.get("keys", {}).get(env_var)

            if not api_key or api_key.lower().startswith("paste_your"):
                print(f"  ⚠ No API key found for {provider}. Add it to .env first.")
                return

        # Select model
        print()
        print("  Select model:")
        models = PROVIDER_MODELS[provider]
        for i, (_, model_name) in enumerate(models, 1):
            print(f"    {i}. {model_name}")
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

        # Update agent configuration
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

        # Switch to cheapest model (Kimi K2.5 - $0.14/$0.28 per 1M tokens)
        agent.update_config("openrouter", api_key, "moonshotai/kimi-k2.5")
        print()
        print("  ✓ Switched to cheapest model: Kimi K2.5")
        print("    ($0.14 input / $0.28 output per 1M tokens)")
        print_header("openrouter", "moonshotai/kimi-k2.5")

    # --- Learning Command Handlers ---

    def _cmd_good(self, agent):
        """Mark last response as good (positive feedback)."""
        from .learning import record_feedback

        last_response = getattr(agent, "_last_response", "")
        if not last_response:
            print_info("No recent response to rate.")
            return

        record_feedback("good", last_response)
        print_info("Thanks! Recorded positive feedback.")

    def _cmd_improve(self, agent):
        """Mark last response for improvement (negative feedback)."""
        from .learning import record_feedback

        last_response = getattr(agent, "_last_response", "")
        if not last_response:
            print_info("No recent response to rate.")
            return

        record_feedback("improve", last_response)
        print_info("Thanks! Will learn from this to improve.")

    def _cmd_stats(self, agent):
        """Show learning statistics summary."""
        from .learning import get_learning_stats

        stats = get_learning_stats()
        summary = stats.get("summary", {})

        print()
        print("  ═══ LEARNING STATISTICS ═══")
        print()
        print(f"  Tasks Completed:    {summary.get('total_tasks_completed', 0)}")
        print(f"  Success Rate:       {summary.get('overall_task_success_rate', 0):.1%}")
        print(f"  Errors Tracked:     {summary.get('total_errors_tracked', 0)}")
        print(f"  Feedback Received:  {summary.get('total_feedback_received', 0)}")
        print(f"  Examples Stored:    {summary.get('total_examples_stored', 0)}")
        print(f"  Tools Tracked:      {summary.get('total_tools_tracked', 0)}")
        print()
        print("  Use /report for full details, /audit to review preferences.")
        print()

    def _cmd_report(self, agent):
        """Export detailed learning report."""
        from .learning import export_learning_report

        report = export_learning_report(format="text")
        print(report)

    def _cmd_audit(self, agent):
        """Audit learned preferences."""
        from .learning import get_analytics

        analytics = get_analytics()
        audit = analytics.audit_learned_preferences()

        print()
        print("  ═══ LEARNED PREFERENCES AUDIT ═══")
        print()

        if not audit:
            print("  No preferences learned yet.")
        else:
            for key, info in audit.items():
                value = info["current_value"]
                print(f"  {key}: {value}")

        print()
        print("  Use /reset preferences to clear all preferences.")
        print()

    def _cmd_reset(self, agent, args=None):
        """Reset learned data or budget for a category."""
        from .learning import reset_learning_category
        from .menu import interactive_menu

        if not args:
            choice = interactive_menu("RESET", [
                ("budget", "Reset token budget"),
                ("preferences", "Reset learned code style & preferences"),
                ("errors", "Reset error patterns"),
                ("examples", "Reset few-shot examples"),
                ("tools", "Reset tool effectiveness data"),
                ("reflections", "Reset task reflections"),
                ("all", "Reset everything"),
            ])
            if choice is None:
                return
            args = [choice]

        category = args[0].lower()

        # Special handling for budget reset
        if category == "budget":
            if hasattr(agent, "protection"):
                agent.protection.reset_all()
                print_info("✓ Token budget reset. Session limits cleared.")
                print_info(f"  Input tokens: 0 / {agent.config.max_session_input_tokens or '∞'}")
                print_info(f"  Output tokens: 0 / {agent.config.max_session_output_tokens or '∞'}")
            else:
                print_info("No budget to reset.")
            return

        # Special handling for 'all' - also reset budget
        if category == "all":
            if hasattr(agent, "protection"):
                agent.protection.reset_all()
                print_info("✓ Token budget reset.")

        result = reset_learning_category(category)

        if result["success"]:
            print_info(result["message"])
        else:
            print_error(result.get("error", "Reset failed"))

    def _cmd_preferences(self, agent):
        """Show learned preferences."""
        from .learning import get_learned_preferences

        prefs = get_learned_preferences()

        print()
        print("  ═══ LEARNED PREFERENCES ═══")
        print()

        style = prefs.get("code_style", {})
        print(f"  Code Indentation:   {style.get('indentation', 4)} spaces")
        print(f"  Naming Convention:  {style.get('naming_convention', 'snake_case')}")
        print(f"  Prefers Comments:   {'Yes' if style.get('prefers_comments') else 'No'}")
        print(f"  Prefers Type Hints: {'Yes' if style.get('prefers_type_hints') else 'No'}")
        print(f"  Verbosity:          {prefs.get('verbosity', 'medium')}")

        preferred_tools = prefs.get("preferred_tools", [])
        if preferred_tools:
            print(f"  Preferred Tools:    {', '.join(preferred_tools[:5])}")

        print()

    def _cmd_settings(self, agent, args=None):
        """View or change agent settings."""
        from .agent_config import get_agent_config_manager
        from .menu import interactive_menu, safe_input

        config_mgr = get_agent_config_manager()

        if not args:
            choice = interactive_menu("SETTINGS", [
                ("view", "View all settings"),
                ("change", "Change a setting"),
                ("security", "Set security level"),
            ])
            if choice is None:
                return

            if choice == "view":
                print(config_mgr.get_config_display())
                return
            elif choice == "change":
                key = safe_input("  Setting key: ")
                if key is None:
                    return
                value = safe_input("  New value: ")
                if value is None:
                    return
                args = [key, value]
            elif choice == "security":
                level = safe_input("  Level (strict/balanced/permissive): ")
                if level is None:
                    return
                args = ["security_level", level]

        # Parse: /settings <key_path> [value]
        key_path = args[0]

        # Special case: security_level preset
        if key_path == "security_level" and len(args) >= 2:
            level = args[1].lower()
            result = config_mgr.set_security_level(level)
            if result["success"]:
                print()
                print(f"  Security level set to: {level.upper()}")
                print(f"  Shell mode: {result['shell_mode']}")
                print("  Tool changes:")
                for tool, enabled in result["tools"].items():
                    status = "ON" if enabled else "OFF"
                    print(f"    {tool:<16} {status}")
                print()
            else:
                print_info(f"Error: {result['error']}")
                print_info(f"Valid levels: {', '.join(result.get('valid_levels', []))}")
            return

        if len(args) < 2:
            # Show single value
            value = config_mgr.get(key_path)
            if value is not None:
                print()
                print(f"  {key_path} = {value}")
                print()
            else:
                print_info(f"Setting not found: {key_path}")
            return

        # Set value: parse the value string
        raw_value = args[1].lower()
        if raw_value in ("true", "on", "yes"):
            value = True
        elif raw_value in ("false", "off", "no"):
            value = False
        elif raw_value.isdigit():
            value = int(raw_value)
        else:
            value = args[1]

        old_value = config_mgr.get(key_path)
        config_mgr.set(key_path, value)
        print()
        print(f"  {key_path}: {old_value} -> {value}")
        print()

    def _cmd_evolve(self, agent, args=None):
        """Review self-improvement proposals."""
        from .agent_config import get_agent_config_manager
        from .learning.self_improver import get_self_improver
        from .menu import interactive_menu

        config_mgr = get_agent_config_manager()
        improver = get_self_improver()

        if not config_mgr.get("self_improvement.enabled", False):
            print()
            print("  Self-improvement is disabled.")
            print("  Enable with: /settings self_improvement.enabled true")
            print()
            return

        if not args:
            choice = interactive_menu("SELF-IMPROVEMENT", [
                ("review", "Review pending proposals"),
                ("analyze", "Analyze & generate new proposals"),
                ("history", "View improvement history"),
                ("stats", "Improvement statistics"),
            ])
            if choice is None:
                return
            args = [choice]

        action = args[0].lower()

        if action == "analyze":
            print()
            print("  Analyzing learning data...")
            new_proposals = improver.analyze_and_propose()
            if new_proposals:
                print(f"  Generated {len(new_proposals)} new proposal(s).")
                for proposal in new_proposals:
                    print(f"    - {proposal['title']}")
            else:
                print("  No new proposals at this time.")
            print()
            return

        if action == "history":
            history = improver.get_history(limit=15)
            print()
            print("  === IMPROVEMENT HISTORY ===")
            print()
            if not history:
                print("  No resolved proposals yet.")
            else:
                for proposal in history:
                    status_icon = {"approved": "+", "rejected": "-", "skipped": "~"}.get(
                        proposal["status"], "?"
                    )
                    resolved = proposal.get("resolved_at", "")[:10]
                    print(f"  [{status_icon}] {proposal['title']}")
                    print(f"      {proposal['status'].upper()} on {resolved}")
            print()
            return

        if action == "stats":
            stats = improver.get_stats()
            print()
            print("  === SELF-IMPROVEMENT STATS ===")
            print()
            print(f"  Total Proposals:  {stats['total_proposals']}")
            print(f"  Pending:          {stats['pending_count']}")
            print(f"  Approved:         {stats['approved_count']}")
            print(f"  Rejected:         {stats['rejected_count']}")
            print(f"  Skipped:          {stats['skipped_count']}")
            print(f"  Approval Rate:    {stats['approval_rate']:.0%}")
            if stats["by_type"]:
                print()
                print("  By Type:")
                for ptype, count in stats["by_type"].items():
                    print(f"    {ptype:<20} {count}")
            print()
            return

        # Default: review pending proposals
        pending = improver.get_pending_proposals()
        if not pending:
            print()
            print("  No pending proposals.")
            print("  Use '/evolve analyze' to generate new proposals from learning data.")
            print()
            return

        print()
        print(f"  === {len(pending)} PENDING PROPOSAL(S) ===")
        print()

        for i, proposal in enumerate(pending, 1):
            print(f"  [{i}] {proposal['title']}")
            print(f"      Type: {proposal['proposal_type']}")
            print(f"      {proposal['description']}")
            print(f"      Reason: {proposal['reason']}")
            print()

            # Ask for decision
            while True:
                try:
                    choice = input("      [a]pprove / [r]eject / [s]kip / [q]uit? ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return

                if choice in ("a", "approve"):
                    result = improver.approve_proposal(proposal["proposal_id"])
                    if result["success"]:
                        print(f"      Applied: {result['message']}")
                    else:
                        print(f"      Failed: {result['error']}")
                    break
                elif choice in ("r", "reject"):
                    improver.reject_proposal(proposal["proposal_id"])
                    print("      Rejected.")
                    break
                elif choice in ("s", "skip"):
                    improver.skip_proposal(proposal["proposal_id"])
                    print("      Skipped.")
                    break
                elif choice in ("q", "quit"):
                    print("      Review paused.")
                    print()
                    return
                else:
                    print("      Please enter a, r, s, or q.")

            print()

        print("  All proposals reviewed.")
        print()

    def _cmd_skill(self, agent, args=None):
        """Configure custom skills/instructions."""
        from .menu import interactive_menu, safe_input
        from .skills import (
            add_skill,
            confirm_and_save_skill,
            learn_skills_from_file,
            list_skills,
            remove_skill,
        )

        if not args:
            choice = interactive_menu("SKILLS", [
                ("add", "Add a custom instruction"),
                ("list", "List active skills"),
                ("remove", "Remove a skill"),
                ("templates", "Show skill templates"),
                ("learn", "Learn skills from a file"),
                ("clear", "Remove all skills"),
            ])
            if choice is None:
                return

            if choice == "add":
                instruction = safe_input("  Instruction: ")
                if instruction is None:
                    return
                args = ["add", instruction]
            elif choice == "remove":
                # Show current list first
                skills = list_skills()
                if skills:
                    print()
                    for i, skill in enumerate(skills, 1):
                        preview = skill["instruction"][:60]
                        if len(skill["instruction"]) > 60:
                            preview += "..."
                        print(f"    {i}. {preview}")
                    print()
                    num = safe_input("  Skill number to remove: ")
                    if num is None:
                        return
                    args = ["remove", num]
                else:
                    print("  No skills configured. Add one with /skill add <instruction>")
                    print()
                    return
            elif choice == "learn":
                path = safe_input("  File path: ")
                if path is None:
                    return
                args = ["learn", path]
            else:
                args = [choice]

        action = args[0].lower()

        if action == "add":
            if len(args) < 2:
                print_info("Usage: /skill add <your instruction>")
                print_info("Example: /skill add Always use TypeScript instead of JavaScript")
                return

            instruction = " ".join(args[1:])
            result = add_skill(instruction)
            if result["success"]:
                print_info(f"✓ Skill added: {instruction[:50]}...")
                print_info("This will be included in future conversations.")
            else:
                print_error(result.get("error", "Failed to add skill"))

        elif action == "list":
            skills = list_skills()
            print()
            print("  ═══ ACTIVE SKILLS ═══")
            print()
            if skills:
                for i, skill in enumerate(skills, 1):
                    print(f"  {i}. {skill['instruction']}")
                    if skill.get("category"):
                        print(f"     Category: {skill['category']}")
                print()
                print(f"  Total: {len(skills)} skill(s)")
            else:
                print("  No skills configured.")
            print()

        elif action == "remove":
            if len(args) < 2:
                print_info("Usage: /skill remove <number>")
                return
            try:
                index = int(args[1]) - 1
                result = remove_skill(index)
                if result["success"]:
                    print_info(f"✓ Removed skill: {result.get('removed', '')[:50]}...")
                else:
                    print_error(result.get("error", "Failed to remove skill"))
            except ValueError:
                print_error("Please provide a valid number")

        elif action == "templates":
            print()
            print("  ═══ SKILL TEMPLATES ═══")
            print()
            print("  Copy and modify these examples:")
            print()
            templates = [
                ("Code Style", "Always use 2-space indentation and single quotes"),
                ("Language", "Prefer TypeScript over JavaScript"),
                ("Framework", "Use React with functional components and hooks"),
                ("Testing", "Always include unit tests with pytest"),
                ("Comments", "Add docstrings to all functions"),
                ("Error Handling", "Use try/except with specific exception types"),
                ("Naming", "Use snake_case for Python, camelCase for JavaScript"),
                ("Brevity", "Keep responses concise, skip explanations unless asked"),
            ]
            for name, example in templates:
                print(f"  {name}:")
                print(f"    /skill add {example}")
                print()

        elif action == "learn":
            if len(args) < 2:
                print_info("Usage: /skill learn <path-to-markdown-file>")
                print_info("Example: /skill learn coding-standards.md")
                return

            file_path = " ".join(args[1:])
            print_info(f"Reading skills from: {file_path}")

            result = learn_skills_from_file(file_path)
            if not result["success"]:
                print_error(result.get("error", "Failed to read file"))
                return

            skills_found = result.get("skills", [])
            duplicates = result.get("duplicates_skipped", 0)

            if not skills_found:
                print_info("No new actionable skills found in this file.")
                if duplicates > 0:
                    print_info(f"  ({duplicates} skill(s) already exist)")
                return

            print()
            print(f"  Found {len(skills_found)} new skill(s)")
            if duplicates > 0:
                print_info(f"  ({duplicates} duplicate(s) skipped)")
            print()

            saved_count = 0
            for i, instruction in enumerate(skills_found, 1):
                print(f"  {i}. {instruction}")
                try:
                    response = input("     Save this skill? [y/n/all/stop]: ").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    print("\n  Cancelled.")
                    break

                if response in ["stop", "s", "q"]:
                    print_info("  Stopped learning.")
                    break

                save_all = response in ["a", "all", "always"]

                if response in ["y", "yes"] or save_all:
                    save_result = confirm_and_save_skill(instruction, source="markdown")
                    if save_result["success"]:
                        print_info("     ✓ Saved")
                        saved_count += 1
                    else:
                        print_error(f"     {save_result.get('error', 'Failed')}")

                    # If "all", save remaining without asking
                    if save_all:
                        for remaining in skills_found[i:]:
                            save_result = confirm_and_save_skill(remaining, source="markdown")
                            if save_result["success"]:
                                print_info(f"     ✓ {remaining[:50]}...")
                                saved_count += 1
                        break
                else:
                    print_info("     Skipped")

                print()

            print()
            print_info(f"  Done! Saved {saved_count} new skill(s).")
            if saved_count > 0:
                print_info("  Skills will apply to all future conversations.")
            print()

        elif action == "clear":
            from .skills import clear_skills

            result = clear_skills()
            if result["success"]:
                print_info("✓ All skills cleared")
            else:
                print_error(result.get("error", "Failed to clear skills"))

        else:
            print_error(f"Unknown action: {action}")
            print_info("Use /skill for help")

    def _cmd_memory(self, agent, args=None):
        """Manage persistent memory (remember/forget/list)."""
        from .memory import Memory
        from .menu import interactive_menu, safe_input

        memory = Memory()

        if not args:
            choice = interactive_menu("MEMORY", [
                ("remember", "Save something to memory"),
                ("forget", "Remove something from memory"),
                ("list", "Show all saved memories"),
            ])
            if choice is None:
                return
            args = [choice]

        action = args[0].lower()

        if action == "remember":
            if len(args) >= 3:
                key = args[1]
                value = " ".join(args[2:])
            elif len(args) == 2:
                key = args[1]
                value = safe_input("  Value: ")
                if value is None:
                    return
            else:
                key = safe_input("  Key (short name): ")
                if key is None:
                    return
                value = safe_input("  Value: ")
                if value is None:
                    return

            memory.set_preference(key.strip(), value.strip())
            print_info(f"Remembered: {key.strip()} = {value.strip()[:60]}")

        elif action == "forget":
            if len(args) >= 2:
                key = args[1]
            else:
                key = safe_input("  Key to forget: ")
                if key is None:
                    return

            all_prefs = memory.get_all_preferences()
            if key.strip() in all_prefs:
                # Remove by setting to None and re-saving
                prefs = memory.get_all_preferences()
                prefs.pop(key.strip(), None)
                memory._preferences = prefs
                memory._save_file(memory._pref_file, prefs)
                print_info(f"Forgotten: {key.strip()}")
            else:
                print_error(f"Key not found: {key.strip()}")

        elif action == "list":
            all_prefs = memory.get_all_preferences()
            if not all_prefs:
                print_info("No memories stored yet. Use /memory remember to add one.")
                return

            print()
            print("  ═══ SAVED MEMORIES ═══")
            print()
            for i, (key, value) in enumerate(all_prefs.items(), 1):
                if key.startswith("_"):
                    continue
                display_value = str(value)[:60]
                print(f"    {i}. {key}: {display_value}")
            print()

        else:
            print_error(f"Unknown action: {action}")
            print_info("Use /memory for options")

    def _cmd_selfmod(self, agent, args=None):
        """View/edit RadSim source and custom prompt."""
        from .config import CUSTOM_PROMPT_FILE, PACKAGE_DIR
        from .menu import interactive_menu

        if not args:
            choice = interactive_menu("SELF-MODIFICATION", [
                ("path", "Show RadSim source directory"),
                ("prompt", "View/edit custom prompt additions"),
                ("list", "List RadSim source files"),
            ])
            if choice is None:
                return
            args = [choice]

        action = args[0].lower()

        if action == "path":
            print()
            print(f"  RadSim source: {PACKAGE_DIR}")
            print(f"  Custom prompt: {CUSTOM_PROMPT_FILE}")
            print()

        elif action == "prompt":
            if CUSTOM_PROMPT_FILE.exists():
                content = CUSTOM_PROMPT_FILE.read_text(encoding="utf-8").strip()
                if content:
                    print()
                    print("  ═══ CUSTOM PROMPT ═══")
                    print()
                    for line in content.splitlines():
                        print(f"    {line}")
                    print()
                else:
                    print_info("Custom prompt file exists but is empty.")
            else:
                print_info("No custom prompt configured yet.")

            print_info("To add custom prompt text, ask the agent to write to:")
            print_info(f"  {CUSTOM_PROMPT_FILE}")

        elif action == "list":
            print()
            print("  ═══ RADSIM SOURCE FILES ═══")
            print()
            source_files = sorted(PACKAGE_DIR.rglob("*.py"))
            for f in source_files:
                relative = f.relative_to(PACKAGE_DIR)
                print(f"    {relative}")
            print()
            print(f"  Total: {len(source_files)} Python files")
            print()

        else:
            print_error(f"Unknown action: {action}")
            print_info("Use /selfmod for options")

    def _cmd_telegram(self, agent, args=None):
        """Configure Telegram bot notifications."""
        from .menu import interactive_menu, safe_input
        from .telegram import (
            is_listening,
            load_telegram_config,
            save_telegram_config,
            send_telegram_message,
            start_listening,
            stop_listening,
        )

        if not args:
            listen_label = "listen off" if is_listening() else "listen on"
            listen_desc = "Stop receiving messages" if is_listening() else "Start receiving messages"
            choice = interactive_menu("TELEGRAM", [
                ("setup", "Configure bot token and chat ID"),
                (listen_label, listen_desc),
                ("test", "Send a test message"),
                ("send", "Send a custom message"),
                ("status", "Check current configuration"),
            ])
            if choice is None:
                return
            args = choice.split()

        action = args[0].lower()

        if action == "setup":
            print()
            print("  ═══ SECURITY WARNING ═══")
            print()
            print("  - Your bot token grants full control of your Telegram bot")
            print("  - Token is stored in ~/.radsim/.env (chmod 600, never committed to git)")
            print("  - Messages are sent over HTTPS but NOT end-to-end encrypted")
            print("  - Anyone with the token can impersonate your bot")
            print("  - Do NOT share your bot token publicly")
            print()
            token = safe_input("  Bot token (from @BotFather): ")
            if token is None:
                return
            chat_id = safe_input("  Chat ID (from @userinfobot): ")
            if chat_id is None:
                return
            try:
                save_telegram_config(token.strip(), chat_id.strip())
            except ValueError as err:
                print_error(str(err))
                return
            print()
            print_info("Telegram configured. Test with: /telegram test")

        elif action == "listen":
            # Toggle or explicit on/off
            if len(args) >= 2:
                toggle = args[1].lower()
            else:
                toggle = "off" if is_listening() else "on"

            if toggle == "on":
                result = start_listening()
                if result["success"]:
                    print()
                    print("  ✓ Telegram listener: ON")
                    print("  Receiving messages from your Telegram bot.")
                    print("  Messages will appear in your RadSim session.")
                    print("  Use /telegram listen off to stop.")
                    print()
                else:
                    print_error(f"Failed to start: {result['error']}")
            elif toggle == "off":
                result = stop_listening()
                print()
                print("  ✓ Telegram listener: OFF")
                print("  No longer receiving Telegram messages.")
                print()
            else:
                print_error("Use: /telegram listen on  or  /telegram listen off")

        elif action == "test":
            result = send_telegram_message("RadSim test - Telegram integration is working.")
            if result["success"]:
                print_info("Test message sent successfully.")
            else:
                print_error(f"Failed: {result['error']}")

        elif action == "send":
            if len(args) >= 2:
                message = " ".join(args[1:])
            else:
                message = safe_input("  Message: ")
                if message is None:
                    return
            result = send_telegram_message(message)
            if result["success"]:
                print_info("Message sent.")
            else:
                print_error(f"Failed: {result['error']}")

        elif action == "status":
            token, chat_id = load_telegram_config()
            print()
            if token:
                masked = token[:8] + "..." + token[-4:] if len(token) > 12 else "***"
                print(f"  Bot Token:  {masked}")
            else:
                print("  Bot Token:  Not configured")
            print(f"  Chat ID:    {chat_id or 'Not configured'}")
            print(f"  Listening:  {'ON' if is_listening() else 'OFF'}")
            print()

        else:
            print_error(f"Unknown action: {action}")
            print_info("Use /telegram for options")

    def _cmd_commands(self, agent):
        """List all available commands."""
        print()
        print("  ═══ ALL COMMANDS ═══")
        print()

        # Group commands by category
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

        for category, cmds in categories.items():
            print(f"  {category}:")
            for cmd, desc in cmds:
                print(f"    {cmd:<18} {desc}")
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

        # Prefer display_content (with teach annotations) over clean content
        content = last_file.get("display_content") or last_file["content"]
        has_teach = last_file.get("display_content") is not None

        print()
        print(f"  Last written file: {last_file['path']}")
        print()
        print_code_content(
            content,
            last_file["path"],
            max_lines=0,  # Show all lines
            collapsed=False,
            highlight_teach=has_teach,
        )
        print()

    # --- Code Analysis Command Handlers ---

    def _cmd_complexity(self, agent, args=None):
        """Complexity budget & analysis."""
        import os

        from .complexity import (
            calculate_file_complexity,
            check_budget,
            format_complexity_report,
            format_file_report,
            load_budget,
            save_budget,
            scan_project_complexity,
        )
        from .menu import interactive_menu, safe_input

        if not args:
            choice = interactive_menu("COMPLEXITY", [
                ("overview", "Score overview"),
                ("budget", "Set budget"),
                ("report", "Full file-by-file report"),
                ("file", "Score a single file"),
            ])
            if choice is None:
                return

            if choice == "overview":
                result = check_budget(os.getcwd())
                budget = result["budget"]
                scan = scan_project_complexity(os.getcwd())
                for line in format_complexity_report(scan, budget):
                    print(line)
                return
            elif choice == "file":
                path = safe_input("  File path: ")
                if path is None:
                    return
                args = [path]
            else:
                args = [choice]

        action = args[0].lower()

        if action == "budget":
            if len(args) < 2:
                current = load_budget()
                if current is not None:
                    print(f"\n  Current complexity budget: {current}")
                else:
                    print("\n  No budget set. Usage: /complexity budget <number>")
                print()
                return

            try:
                budget_value = int(args[1])
            except ValueError:
                print("\n  Budget must be a number. Example: /complexity budget 200")
                print()
                return

            save_budget(budget_value)
            print(f"\n  ✓ Complexity budget set to {budget_value}")

            # Show current status against new budget
            result = check_budget(os.getcwd())
            score = result["score"]
            if result["within_budget"]:
                print(f"  ✅ Currently within budget ({score}/{budget_value})")
            else:
                print(f"  ⚠️  Currently OVER budget ({score}/{budget_value})")
            print()
            return

        if action == "report":
            budget = load_budget()
            scan = scan_project_complexity(os.getcwd())
            for line in format_complexity_report(scan, budget):
                print(line)
            return

        # Assume it's a file path
        file_path = " ".join(args)
        if os.path.isfile(file_path):
            result = calculate_file_complexity(file_path)
            if result:
                for line in format_file_report(result):
                    print(line)
            else:
                print(f"\n  Unsupported file type: {file_path}")
                print()
        else:
            print(f"\n  File not found: {file_path}")
            print("  Usage: /complexity [budget <N> | report | <file>]")
            print()

    def _cmd_stress(self, agent, args=None):
        """Adversarial code review."""
        import os

        from .adversarial import (
            format_stress_report,
            stress_test_directory,
            stress_test_file,
        )
        from .menu import interactive_menu, safe_input

        if not args:
            choice = interactive_menu("ADVERSARIAL REVIEW", [
                ("project", "Scan entire project"),
                ("file", "Stress test a single file"),
            ])
            if choice is None:
                return

            if choice == "project":
                print("\n  Scanning project for vulnerabilities...")
                results = stress_test_directory(os.getcwd())
                for line in format_stress_report(results):
                    print(line)
                return
            elif choice == "file":
                path = safe_input("  File path: ")
                if path is None:
                    return
                args = [path]

        # Single file stress test
        file_path = " ".join(args)
        if os.path.isfile(file_path):
            result = stress_test_file(file_path)
            if result:
                for line in format_stress_report(result):
                    print(line)
            else:
                print(f"\n  Unsupported file type: {file_path}")
                print()
        else:
            print(f"\n  File not found: {file_path}")
            print("  Usage: /stress [<file>]")
            print()

    def _cmd_archaeology(self, agent, args=None):
        """Find dead code & zombies."""
        import os

        from .archaeology import (
            find_zombie_dependencies,
            format_archaeology_report,
            format_deps_report,
            format_imports_report,
            run_full_archaeology,
            scan_unused_imports,
        )
        from .menu import interactive_menu

        if not args:
            choice = interactive_menu("CODE ARCHAEOLOGY", [
                ("full", "Full dead code scan"),
                ("imports", "Unused imports only"),
                ("deps", "Zombie dependencies only"),
                ("clean", "Interactive cleanup (review-only)"),
            ])
            if choice is None:
                return

            if choice == "full":
                print("\n  Excavating codebase...")
                results = run_full_archaeology(os.getcwd())
                for line in format_archaeology_report(results):
                    print(line)
                return
            else:
                args = [choice]

        action = args[0].lower()

        if action == "imports":
            results = scan_unused_imports(os.getcwd())
            for line in format_imports_report(results):
                print(line)
            return

        if action == "deps":
            results = find_zombie_dependencies(os.getcwd())
            for line in format_deps_report(results):
                print(line)
            return

        if action == "clean":
            # Interactive cleanup — review-then-execute
            results = run_full_archaeology(os.getcwd())
            summary = results["summary"]

            total_items = (summary["dead_function_count"] +
                           summary["unused_import_count"] +
                           summary["zombie_dep_count"])

            if total_items == 0:
                print("\n  Nothing to clean up! Codebase is tidy. ✅")
                print()
                return

            # Show report first
            for line in format_archaeology_report(results):
                print(line)

            print("  ⚠️  Cleanup is review-only. No files will be modified.")
            print("  To remove items, edit the files manually after reviewing.")
            print("  This ensures you never accidentally delete needed code.")
            print()
            return

        print(f"\n  Unknown sub-command: {action}")
        print("  Usage: /archaeology [imports | deps | clean]")
        print()

    def _cmd_plan(self, agent, args=None):
        """Structured plan-confirm-execute workflow."""
        from .menu import interactive_menu, safe_input
        from .planner import get_plan_manager

        pm = get_plan_manager()

        if not args:
            # No args: show menu or create plan
            if pm.active_plan:
                choice = interactive_menu("PLAN", [
                    ("show", "Show current plan"),
                    ("approve", "Approve plan for execution"),
                    ("reject", "Reject and discard plan"),
                    ("step", "Execute next step"),
                    ("run", "Execute all remaining steps"),
                    ("status", "Show progress"),
                    ("export", "Export plan to markdown"),
                    ("history", "Show past plans"),
                    ("new", "Create a new plan"),
                ])
            else:
                choice = interactive_menu("PLAN", [
                    ("new", "Create a new plan"),
                    ("history", "Show past plans"),
                ])
            if choice is None:
                return

            if choice == "new":
                desc = safe_input("  Describe what you want to do: ")
                if desc is None:
                    return
                args = [desc]
            else:
                args = [choice]

        action = args[0].lower()

        if action == "show":
            print(pm.show_plan())

        elif action == "approve":
            print(pm.approve_plan())

        elif action == "reject":
            print(pm.reject_plan())

        elif action == "status":
            print(pm.get_status())

        elif action == "history":
            print(pm.get_history())

        elif action == "export":
            print(pm.export_plan())

        elif action == "step":
            if not pm.active_plan:
                print("  No active plan. Use '/plan <description>' to create one.")
                return
            if pm.active_plan.status not in ("approved", "in_progress"):
                print("  Plan must be approved first. Use '/plan approve'.")
                return

            next_step = pm.get_next_step()
            if not next_step:
                print("  ✅ All steps completed!")
                return

            step_index, step = next_step
            print(f"\n  Executing Step {step_index + 1}: {step.description}")
            if step.files:
                print(f"  Files: {', '.join(step.files)}")
            print(f"  Risk: {step.risk.upper()}")
            print()

            # Mark in progress and let agent execute
            pm.mark_step_in_progress(step_index)

            # Send the step as a prompt to the agent
            step_prompt = (
                f"Execute this plan step: {step.description}\n"
                f"Files to modify: {', '.join(step.files) if step.files else 'as needed'}\n"
                f"Risk level: {step.risk}"
            )
            agent.process_message(step_prompt)
            pm.mark_step_complete(step_index)

            print(f"\n  ✓ Step {step_index + 1} completed.")
            print(pm.get_status())

        elif action == "run":
            if not pm.active_plan:
                print("  No active plan. Use '/plan <description>' to create one.")
                return
            if pm.active_plan.status not in ("approved", "in_progress"):
                print("  Plan must be approved first. Use '/plan approve'.")
                return

            while True:
                next_step = pm.get_next_step()
                if not next_step:
                    print("\n  ✅ All steps completed!")
                    break

                step_index, step = next_step
                print(f"\n  ── Step {step_index + 1}/{len(pm.active_plan.steps)}: {step.description}")

                if step.checkpoint:
                    try:
                        confirm = input("  Continue? [y/n]: ").strip().lower()
                    except (KeyboardInterrupt, EOFError):
                        print("\n  Plan execution paused.")
                        return
                    if confirm not in ("y", "yes", ""):
                        print("  Plan execution paused.")
                        return

                pm.mark_step_in_progress(step_index)
                step_prompt = (
                    f"Execute this plan step: {step.description}\n"
                    f"Files to modify: {', '.join(step.files) if step.files else 'as needed'}\n"
                    f"Risk level: {step.risk}"
                )
                agent.process_message(step_prompt)
                pm.mark_step_complete(step_index)
                print(f"  ✓ Step {step_index + 1} completed.")

            print(pm.get_status())

        else:
            # Treat as a plan description (e.g., /plan Add JWT auth)
            description = " ".join(args)
            print(f"\n  Generating plan for: {description}")
            print("  Thinking...")

            # Use the planning prompt to generate a plan via the agent
            from .prompts import PLANNING_SYSTEM_PROMPT

            plan_prompt = (
                f"{PLANNING_SYSTEM_PROMPT}\n\n"
                f"Task: {description}\n\n"
                f"Analyze the current project and generate a structured implementation plan."
            )
            response = agent.process_message(plan_prompt)

            # Fallback: process_message may return None when tool calls consume
            # the return value, but _last_response captures the final text.
            if not response:
                response = getattr(agent, "_last_response", None)

            if response:
                plan = pm.create_plan_from_response(response)
                if plan:
                    print(pm.show_plan())
                else:
                    print("  ⚠ Could not parse plan from response.")
                    print("  The response was displayed above. Try again with a clearer description.")
            else:
                print("  ⚠ No response from agent. Check your API key and provider.")

    def _cmd_panning(self, agent, args=None):
        """Brain-dump processing & synthesis."""
        from .menu import interactive_menu, safe_input
        from .panning import get_panning_session, start_new_session

        session = get_panning_session()

        if not args:
            if session.active:
                choice = interactive_menu("PANNING", [
                    ("end", "End session and generate synthesis"),
                    ("file", "Add a file to the dump"),
                    ("refine", "Refine the last synthesis"),
                    ("bridge", "Bridge to /plan"),
                ])
            else:
                choice = interactive_menu("PANNING", [
                    ("start", "Start a new panning session"),
                    ("text", "Process a one-shot brain dump"),
                    ("file", "Process a text/transcript file"),
                ])
            if choice is None:
                return

            if choice == "text":
                text = safe_input("  Dump your thoughts: ")
                if text is None:
                    return
                args = [text]
            elif choice in ("start", "end", "refine", "bridge"):
                args = [choice]
            elif choice == "file":
                path = safe_input("  File path: ")
                if path is None:
                    return
                args = ["file", path]

        action = args[0].lower() if args else "start"

        if action == "file" and len(args) >= 2:
            path = " ".join(args[1:])
            if not session.active:
                session = start_new_session()
                session.start()
            print(session.process_file(path))
            print("  Type '/panning end' to generate synthesis.")

        elif action == "end":
            if not session.dumps:
                print("  Nothing to synthesise. Dump some thoughts first!")
                return

            print("\n  Synthesising your thoughts...")

            from .prompts import PANNING_SYSTEM_PROMPT

            panning_prompt = (
                f"{PANNING_SYSTEM_PROMPT}\n\n"
                f"Brain dump content:\n\n{session.get_all_dumps()}"
            )
            response = agent.process_message(panning_prompt)

            # Fallback: capture from _last_response if return was None
            if not response:
                response = getattr(agent, "_last_response", None)

            if response:
                synthesis = session.parse_synthesis(response)
                if synthesis:
                    print(synthesis.format_display())
                else:
                    print("  ⚠ Could not parse synthesis. Response displayed above.")
            else:
                print("  ⚠ No response from agent.")

            session.end()

        elif action == "refine":
            synthesis = session.get_latest_synthesis()
            if not synthesis:
                print("  No synthesis to refine. Run '/panning end' first.")
                return

            detail = safe_input("  What to drill into (or press Enter for general): ")
            if detail is None:
                return

            from .prompts import PANNING_SYSTEM_PROMPT

            refine_prompt = (
                f"{PANNING_SYSTEM_PROMPT}\n\n"
                f"Previous synthesis:\n{json.dumps(synthesis.to_dict(), indent=2)}\n\n"
                f"Drill deeper into: {detail or 'all themes'}\n"
                f"Provide a more detailed synthesis."
            )
            response = agent.process_message(refine_prompt)

            # Fallback: capture from _last_response if return was None
            if not response:
                response = getattr(agent, "_last_response", None)

            if response:
                new_synthesis = session.parse_synthesis(response)
                if new_synthesis:
                    print(new_synthesis.format_display())
                else:
                    print("  ⚠ Could not parse refined synthesis.")

        elif action == "bridge":
            synthesis = session.get_latest_synthesis()
            if not synthesis:
                print("  No synthesis to bridge. Run '/panning end' first.")
                return

            plan_desc = synthesis.to_plan_description()
            print(f"\n  Bridging to /plan with: {plan_desc[:80]}...")
            self._cmd_plan(agent, [plan_desc])

        elif action == "start":
            session = start_new_session()
            print(session.start())

        else:
            # Treat as one-shot brain dump text
            if not session.active:
                session = start_new_session()
                session.start()
            session.add_dump(" ".join(args))
            print(f"  ✓ Added to panning session ({len(session.dumps)} dump(s) collected)")
            print("  Keep dumping, or type '/panning end' to synthesise.")

    def get_relevant_commands(self, context: str) -> list:
        """Get commands relevant to a context for hints.

        Args:
            context: What the user is doing (e.g., 'model', 'error', 'code')

        Returns:
            List of (command, description) tuples
        """
        command_hints = {
            "model": [
                ("/switch", "Quick switch model"),
                ("/config", "Full configuration"),
                ("/free", "Use free model"),
            ],
            "error": [
                ("/clear", "Clear and retry"),
                ("/new", "Fresh start"),
            ],
            "slow": [
                ("/switch", "Try faster model"),
                ("/free", "Use free model"),
            ],
            "feedback": [
                ("/good", "Mark as good"),
                ("/improve", "Mark for improvement"),
            ],
            "help": [
                ("/help", "Full help"),
                ("/tools", "Available tools"),
                ("/commands", "All commands"),
            ],
            "code": [
                ("/skill add", "Add coding preference"),
                ("/preferences", "See learned style"),
                ("/complexity", "Check complexity budget"),
                ("/stress", "Adversarial review"),
                ("/archaeology", "Find dead code"),
            ],
            "planning": [
                ("/plan", "Create/manage plans"),
                ("/panning", "Brain-dump processing"),
            ],
        }
        return command_hints.get(context, [])


def print_error(msg):
    # localized import to avoid circular dependency
    from .output import print_error as pe

    pe(msg)
