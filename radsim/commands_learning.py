"""Learning, customization, and integration slash-command handlers."""

from .output import print_error, print_info
from .runtime_context import get_runtime_context


class LearningCommandHandlersMixin:
    """Handlers for learning, memory, skills, and Telegram commands."""

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
            choice = interactive_menu(
                "RESET",
                [
                    ("budget", "Reset token budget"),
                    ("preferences", "Reset learned code style & preferences"),
                    ("errors", "Reset error patterns"),
                    ("examples", "Reset few-shot examples"),
                    ("tools", "Reset tool effectiveness data"),
                    ("reflections", "Reset task reflections"),
                    ("all", "Reset everything"),
                ],
            )
            if choice is None:
                return
            args = [choice]

        category = args[0].lower()

        if category == "budget":
            if hasattr(agent, "protection"):
                agent.protection.reset_all()
                print_info("ok Token budget reset. Session limits cleared.")
                print_info(f"  Input tokens: 0 / {agent.config.max_session_input_tokens or '∞'}")
                print_info(
                    f"  Output tokens: 0 / {agent.config.max_session_output_tokens or '∞'}"
                )
            else:
                print_info("No budget to reset.")
            return

        if category == "all" and hasattr(agent, "protection"):
            agent.protection.reset_all()
            print_info("ok Token budget reset.")

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

    def _cmd_trust(self, agent, args=None):
        """View or reset learned confirmation trust."""
        from .trust_bandit import get_trust_bandit

        args = args or []
        bandit = get_trust_bandit()

        if not args:
            self._print_trust_stats(agent, bandit)
            return

        command = args[0].lower()
        if command == "reset":
            self._reset_trust_stats(bandit, args)
            return

        if command in ("low", "medium", "high"):
            agent.config.trust_mode = command
            print_info(f"Trust mode set to {command}.")
            return

        print_error("Usage: /trust, /trust reset [tool], /trust low, /trust medium")

    def _print_trust_stats(self, agent, bandit):
        """Print trust-bandit stats."""
        stats = bandit.get_stats()
        mode = getattr(agent.config, "trust_mode", "medium")

        print()
        print("  Trust bandit")
        print(f"  Mode: {mode}")
        print()

        if not stats:
            print_info("No trust data yet. Learning starts after 5 confirms per action.")
            return

        for entry in stats:
            signature = entry["signature"]
            if len(signature) > 52:
                signature = signature[:49] + "..."
            print(
                f"  {entry['tool']:<16} {signature:<52} "
                f"trust={entry['trust']:.2f} n={entry['observations']}"
            )
        print()

    def _reset_trust_stats(self, bandit, args):
        """Reset trust data from the /trust command."""
        if len(args) > 1:
            tool_name = args[1]
            bandit.reset(tool_name=tool_name)
            print_info(f"Reset trust for {tool_name}.")
            return

        bandit.reset()
        print_info("Reset all trust.")

    def _cmd_settings(self, agent, args=None):
        """View or change agent settings."""
        from .agent_config import get_agent_config_manager
        from .menu import interactive_menu, safe_input

        config_mgr = get_agent_config_manager()

        if not args:
            choice = interactive_menu(
                "SETTINGS",
                [
                    ("view", "View all settings"),
                    ("change", "Change a setting"),
                    ("security", "Set security level"),
                ],
            )
            if choice is None:
                return

            if choice == "view":
                print(config_mgr.get_config_display())
                return
            if choice == "change":
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

        key_path = args[0]

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
            value = config_mgr.get(key_path)
            if value is not None:
                print()
                print(f"  {key_path} = {value}")
                print()
            else:
                print_info(f"Setting not found: {key_path}")
            return

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
            choice = interactive_menu(
                "SELF-IMPROVEMENT",
                [
                    ("review", "Review pending proposals"),
                    ("analyze", "Analyze & generate new proposals"),
                    ("history", "View improvement history"),
                    ("stats", "Improvement statistics"),
                ],
            )
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
                for proposal_type, count in stats["by_type"].items():
                    print(f"    {proposal_type:<20} {count}")
            print()
            return

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

        for index, proposal in enumerate(pending, 1):
            print(f"  [{index}] {proposal['title']}")
            print(f"      Type: {proposal['proposal_type']}")
            print(f"      {proposal['description']}")
            print(f"      Reason: {proposal['reason']}")
            print()

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
                if choice in ("r", "reject"):
                    improver.reject_proposal(proposal["proposal_id"])
                    print("      Rejected.")
                    break
                if choice in ("s", "skip"):
                    improver.skip_proposal(proposal["proposal_id"])
                    print("      Skipped.")
                    break
                if choice in ("q", "quit"):
                    print("      Review paused.")
                    print()
                    return
                print("      Please enter a, r, s, or q.")

            print()

        print("  All proposals reviewed.")
        print()

    def _cmd_skill(self, agent, args=None):
        """Configure custom skills/instructions."""
        from .menu import interactive_menu, safe_input
        from .skills import (
            add_skill,
            clear_skills,
            confirm_and_save_skill,
            learn_skills_from_file,
            list_skills,
            remove_skill,
        )

        if not args:
            choice = interactive_menu(
                "SKILLS",
                [
                    ("add", "Add a custom instruction"),
                    ("list", "List active skills"),
                    ("remove", "Remove a skill"),
                    ("templates", "Show skill templates"),
                    ("learn", "Learn skills from a file"),
                    ("clear", "Remove all skills"),
                ],
            )
            if choice is None:
                return

            if choice == "add":
                instruction = safe_input("  Instruction: ")
                if instruction is None:
                    return
                args = ["add", instruction]
            elif choice == "remove":
                skills = list_skills()
                if skills:
                    print()
                    for index, skill in enumerate(skills, 1):
                        preview = skill["instruction"][:60]
                        if len(skill["instruction"]) > 60:
                            preview += "..."
                        print(f"    {index}. {preview}")
                    print()
                    number = safe_input("  Skill number to remove: ")
                    if number is None:
                        return
                    args = ["remove", number]
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
                print_info(f"ok Skill added: {instruction[:50]}...")
                print_info("This will be included in future conversations.")
            else:
                print_error(result.get("error", "Failed to add skill"))
            return

        if action == "list":
            skills = list_skills()
            print()
            print("  ═══ ACTIVE SKILLS ═══")
            print()
            if skills:
                for index, skill in enumerate(skills, 1):
                    print(f"  {index}. {skill['instruction']}")
                    if skill.get("category"):
                        print(f"     Category: {skill['category']}")
                print()
                print(f"  Total: {len(skills)} skill(s)")
            else:
                print("  No skills configured.")
            print()
            return

        if action == "remove":
            if len(args) < 2:
                print_info("Usage: /skill remove <number>")
                return
            try:
                index = int(args[1]) - 1
            except ValueError:
                print_error("Please provide a valid number")
                return

            result = remove_skill(index)
            if result["success"]:
                print_info(f"ok Removed skill: {result.get('removed', '')[:50]}...")
            else:
                print_error(result.get("error", "Failed to remove skill"))
            return

        if action == "templates":
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
            return

        if action == "learn":
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
            for index, instruction in enumerate(skills_found, 1):
                print(f"  {index}. {instruction}")
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
                        print_info("     ok Saved")
                        saved_count += 1
                    else:
                        print_error(f"     {save_result.get('error', 'Failed')}")

                    if save_all:
                        for remaining in skills_found[index:]:
                            save_result = confirm_and_save_skill(remaining, source="markdown")
                            if save_result["success"]:
                                print_info(f"     ok {remaining[:50]}...")
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
            return

        if action == "clear":
            result = clear_skills()
            if result["success"]:
                print_info("ok All skills cleared")
            else:
                print_error(result.get("error", "Failed to clear skills"))
            return

        print_error(f"Unknown action: {action}")
        print_info("Use /skill for help")

    def _cmd_memory(self, agent, args=None):
        """Manage persistent memory (view/edit/forget/export)."""
        import os
        import subprocess
        import zipfile
        from datetime import datetime

        from .menu import interactive_menu, safe_input

        memory = get_runtime_context().get_memory()

        if not args:
            choice = interactive_menu(
                "MEMORY",
                [
                    ("view", "Dump current global/project memory status"),
                    ("edit", "Open memory files in default editor"),
                    ("forget", "Clear specific contexts or keys"),
                    ("export", "Zip and export current memory context"),
                ],
            )
            if choice is None:
                return
            args = [choice]

        action = args[0].lower()

        if action == "view":
            print("\n  ═══ GLOBAL MEMORY ═══")
            prefs = memory.global_mem.data.get("preferences", {})
            if prefs:
                for key, value in prefs.items():
                    print(f"  • {key}: {value}")
            else:
                print("  No global preferences set.")

            patterns = memory.global_mem.data.get("learned_patterns", [])
            if patterns:
                print("\n  ═══ LEARNED PATTERNS ═══")
                for pattern in patterns[-5:]:
                    if isinstance(pattern, dict):
                        print(
                            f"  • [{pattern.get('confidence', 'medium')}] {pattern.get('pattern')}"
                        )
                    else:
                        print(f"  • {pattern}")

            print("\n  ═══ PROJECT MEMORY ═══")
            print(
                f"  Active Project: {memory.project_mem.data.get('project', {}).get('name', 'Unknown')}"
            )
            decisions = memory.project_mem.data.get("decisions", [])
            if decisions:
                print(f"  Recent Decisions ({len(decisions)} total):")
                for decision in decisions[-3:]:
                    print(
                        f"  • {decision.get('decision')} "
                        f"(Rationale: {decision.get('rationale', 'none')})"
                    )
            print()
            return

        if action == "edit":
            choice = interactive_menu(
                "EDIT MEMORY",
                [
                    ("project", "Edit agents.md (Project Context)"),
                    ("global", "Edit global_memory.json (Expert only)"),
                ],
            )
            if choice:
                editor = os.environ.get("EDITOR", "nano")
                try:
                    target_file = (
                        memory.project_mem.agents_file
                        if choice == "project"
                        else memory.global_mem.file_path
                    )
                    subprocess.call([editor, str(target_file)])
                    print_info("Memory file updated. Reloading memory system.")
                    memory.global_mem.data = memory.global_mem._load_json(memory.global_mem.file_path)
                    memory.project_mem.data = memory.project_mem._load_json(
                        memory.project_mem.json_file
                    )
                except Exception as error:
                    print_error(f"Could not open editor: {error}")
            return

        if action == "forget":
            choice = interactive_menu(
                "FORGET MEMORY",
                [
                    ("preference", "Forget a global preference"),
                    ("project", "Clear entire project memory"),
                ],
            )
            if choice == "preference":
                key = safe_input("  Key to forget: ")
                if key:
                    preferences = memory.global_mem.data.get("preferences", {})
                    if key in preferences:
                        del preferences[key]
                        memory.global_mem._save_json(memory.global_mem.file_path, memory.global_mem.data)
                        print_info(f"Forgotten preference: {key}")
                    else:
                        print_error(f"Key not found: {key}")
            elif choice == "project":
                confirm = safe_input("  Are you sure you want to clear this project's memory? [y/N]: ")
                if confirm and confirm.lower() in ("y", "yes"):
                    memory.clear_context(memory.project_mem.project_dir.name)
                    print_info(f"Cleared project memory for: {memory.project_mem.project_dir.name}")
            return

        if action == "export":
            export_name = f"radsim_memory_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            try:
                with zipfile.ZipFile(export_name, "w") as zip_file:
                    if memory.global_mem.file_path.exists():
                        zip_file.write(memory.global_mem.file_path, "global_memory.json")
                    if memory.project_mem.json_file.exists():
                        zip_file.write(memory.project_mem.json_file, "project/memory.json")
                    if memory.project_mem.agents_file.exists():
                        zip_file.write(memory.project_mem.agents_file, "project/agents.md")
                print_info(f"Memory exported successfully to {export_name}")
            except Exception as error:
                print_error(f"Failed to export memory: {error}")
            return

        print_error(f"Unknown action: {action}")
        print_info("Use /memory for options")

    def _cmd_selfmod(self, agent, args=None):
        """View/edit RadSim source and custom prompt."""
        from .config import CUSTOM_PROMPT_FILE, PACKAGE_DIR
        from .menu import interactive_menu

        if not args:
            choice = interactive_menu(
                "SELF-MODIFICATION",
                [
                    ("path", "Show RadSim source directory"),
                    ("prompt", "View/edit custom prompt additions"),
                    ("list", "List RadSim source files"),
                ],
            )
            if choice is None:
                return
            args = [choice]

        action = args[0].lower()

        if action == "path":
            print()
            print(f"  RadSim source: {PACKAGE_DIR}")
            print(f"  Custom prompt: {CUSTOM_PROMPT_FILE}")
            print()
            return

        if action == "prompt":
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
            return

        if action == "list":
            print()
            print("  ═══ RADSIM SOURCE FILES ═══")
            print()
            source_files = sorted(PACKAGE_DIR.rglob("*.py"))
            for source_file in source_files:
                relative = source_file.relative_to(PACKAGE_DIR)
                print(f"    {relative}")
            print()
            print(f"  Total: {len(source_files)} Python files")
            print()
            return

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
            listen_desc = (
                "Stop receiving messages" if is_listening() else "Start receiving messages"
            )
            choice = interactive_menu(
                "TELEGRAM",
                [
                    ("setup", "Configure bot token and chat ID"),
                    (listen_label, listen_desc),
                    ("test", "Send a test message"),
                    ("send", "Send a custom message"),
                    ("status", "Check current configuration"),
                ],
            )
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
            except ValueError as error:
                print_error(str(error))
                return
            print()
            print_info("Telegram configured. Test with: /telegram test")
            return

        if action == "listen":
            toggle = args[1].lower() if len(args) >= 2 else ("off" if is_listening() else "on")

            if toggle == "on":
                result = start_listening()
                if result["success"]:
                    print()
                    print("  ok Telegram listener: ON")
                    print("  Receiving messages from your Telegram bot.")
                    print("  Messages will appear in your RadSim session.")
                    print("  Use /telegram listen off to stop.")
                    print()
                else:
                    print_error(f"Failed to start: {result['error']}")
            elif toggle == "off":
                stop_listening()
                print()
                print("  ok Telegram listener: OFF")
                print("  No longer receiving Telegram messages.")
                print()
            else:
                print_error("Use: /telegram listen on  or  /telegram listen off")
            return

        if action == "test":
            result = send_telegram_message("RadSim test - Telegram integration is working.")
            if result["success"]:
                print_info("Test message sent successfully.")
            else:
                print_error(f"Failed: {result['error']}")
            return

        if action == "send":
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
            return

        if action == "status":
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
            return

        print_error(f"Unknown action: {action}")
        print_info("Use /telegram for options")
