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

    def _cmd_stats(self, agent, args=None):
        """Show learning statistics, or a deeper view via a subaction."""
        views = {
            "report": self._cmd_report,
            "audit": self._cmd_audit,
            "prefs": self._cmd_preferences,
            "preferences": self._cmd_preferences,
            "prompt": self._cmd_prompt_stats,
        }
        if args:
            view = views.get(args[0].lower())
            if view is None:
                print_info("Usage: /stats [report|audit|prefs|prompt]")
                return
            view(agent)
            return

        self._show_learning_summary()

    def _show_learning_summary(self):
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

    def _confirm_security_off(self, safe_input):
        """Warn about disabling security and require typed confirmation."""
        from .agent_config import SECURITY_OFF_WARNING_LINES

        print()
        for line in SECURITY_OFF_WARNING_LINES:
            print_error(f"  {line}")
        print()
        response = safe_input("  Type 'off' to confirm, anything else to cancel: ")
        return response is not None and response.strip().lower() == "off"

    def _security_settings_menu(self, config_mgr):
        """Pick a security preset by number or customize individual switches."""
        from .menu import interactive_menu

        current = config_mgr.get("security_level", "balanced")
        choice = interactive_menu(
            f"SECURITY (current: {current.upper()})",
            [
                ("restrictive", "Restrictive — read-only command whitelist"),
                ("balanced", "Balanced — prompts for every command (default)"),
                ("permissive", "Permissive — prompts, deploy enabled"),
                ("off", "Off — no prompts (catastrophic still blocked)"),
                ("customize", "Customize individual switches"),
            ],
        )
        if choice is None:
            return
        if choice == "customize":
            self._customize_security_switches(config_mgr)
            return
        self._apply_security_level(config_mgr, choice)

    def _apply_security_level(self, config_mgr, level):
        """Validate a preset choice, gate "off" behind a warning, and apply."""
        from .agent_config import SECURITY_LEVEL_NUMBERS
        from .menu import safe_input

        level = str(level).strip().lower()
        level = SECURITY_LEVEL_NUMBERS.get(level, level)
        if level == "off" and not self._confirm_security_off(safe_input):
            print_info("Security level unchanged.")
            return

        result = config_mgr.set_security_level(level)
        if not result["success"]:
            print_info(f"Error: {result['error']}")
            print_info(f"Valid levels: 1-4 or {', '.join(result.get('valid_levels', []))}")
            return

        print()
        print(f"  Security level set to: {level.upper()}")
        print(f"  Shell mode: {result['shell_mode']}")
        print("  Tool changes:")
        for tool, enabled in result["tools"].items():
            status = "ON" if enabled else "OFF"
            print(f"    {tool:<16} {status}")
        if level == "off":
            print()
            print("  Destructive commands now run without confirmation.")
            print("  Restore with: /settings security_level balanced")
        print()

    def _customize_security_switches(self, config_mgr):
        """Toggle individual security switches and persist the result."""
        from .agent_config import SECURITY_OFF_WARNING_LINES
        from .menu import toggle_menu

        switches = config_mgr.get_security_switches()
        footer = ("Catastrophic commands (rm -rf /, mkfs) stay blocked regardless.",)
        states = toggle_menu("SECURITY SWITCHES", switches, footer_lines=footer)
        if states is None:
            print_info("No changes saved.")
            return

        changed = config_mgr.apply_security_switches(states)
        if not changed:
            print_info("No changes.")
            return

        print()
        print("  Saved. Changed switches:")
        for key in changed:
            status = "ON" if states[key] else "OFF"
            print(f"    {key:<28} {status}")
        if not config_mgr.destructive_confirmation_enabled():
            print()
            for line in SECURITY_OFF_WARNING_LINES:
                print_error(f"  {line}")
        print()

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
                self._security_settings_menu(config_mgr)
                return

        key_path = args[0]

        if key_path == "security" and len(args) == 1:
            self._security_settings_menu(config_mgr)
            return

        if key_path == "security_level" and len(args) >= 2:
            self._apply_security_level(config_mgr, args[1])
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
        if not args:
            args = self._prompt_skill_action()
            if args is None:
                return

        action = args[0].lower()
        handlers = {
            "add": self._skill_add,
            "list": self._skill_list,
            "remove": self._skill_remove,
            "templates": self._skill_templates,
            "learn": self._skill_learn,
            "clear": self._skill_clear,
        }
        handler = handlers.get(action)
        if handler is None:
            print_error(f"Unknown action: {action}")
            print_info("Use /skill for help")
            return
        handler(args[1:])

    def _prompt_skill_action(self):
        """Show the skills menu and return the equivalent command args."""
        from .menu import interactive_menu, safe_input
        from .skills import list_skills

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
            return None

        if choice == "add":
            instruction = safe_input("  Instruction: ")
            return None if instruction is None else ["add", instruction]

        if choice == "remove":
            skills = list_skills()
            if not skills:
                print("  No skills configured. Add one with /skill add <instruction>")
                print()
                return None
            print()
            for index, skill in enumerate(skills, 1):
                preview = skill["instruction"][:60]
                if len(skill["instruction"]) > 60:
                    preview += "..."
                print(f"    {index}. {preview}")
            print()
            number = safe_input("  Skill number to remove: ")
            return None if number is None else ["remove", number]

        if choice == "learn":
            path = safe_input("  File path: ")
            return None if path is None else ["learn", path]

        return [choice]

    def _skill_add(self, args):
        """Add one custom instruction."""
        from .skills import add_skill

        if not args:
            print_info("Usage: /skill add <your instruction>")
            print_info("Example: /skill add Always use TypeScript instead of JavaScript")
            return

        instruction = " ".join(args)
        result = add_skill(instruction)
        if result["success"]:
            print_info(f"ok Skill added: {instruction[:50]}...")
            print_info("This will be included in future conversations.")
        else:
            print_error(result.get("error", "Failed to add skill"))

    def _skill_list(self, args):
        """Print all active skills."""
        from .skills import list_skills

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

    def _skill_remove(self, args):
        """Remove one skill, offering a picker when no number is given."""
        from .menu import interactive_menu
        from .skills import list_skills, remove_skill

        if args:
            try:
                index = int(args[0]) - 1
            except ValueError:
                print_error("Please provide a valid number")
                return
        else:
            skills = list_skills()
            if not skills:
                print_info("No skills configured. Use /skill add to create one.")
                return
            choice = interactive_menu(
                "REMOVE WHICH SKILL?",
                [
                    (str(number), skill["instruction"][:60])
                    for number, skill in enumerate(skills, 1)
                ],
            )
            if choice is None:
                return
            index = int(choice) - 1

        result = remove_skill(index)
        if result["success"]:
            print_info(f"ok Removed skill: {result.get('removed', '')[:50]}...")
        else:
            print_error(result.get("error", "Failed to remove skill"))

    def _skill_templates(self, args):
        """Print example instructions users can copy."""
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
        print()
        print("  ═══ SKILL TEMPLATES ═══")
        print()
        print("  Copy and modify these examples:")
        print()
        for name, example in templates:
            print(f"  {name}:")
            print(f"    /skill add {example}")
            print()

    def _skill_learn(self, args):
        """Extract skills from a markdown file and review them one by one."""
        from .skills import learn_skills_from_file

        if not args:
            print_info("Usage: /skill learn <path-to-markdown-file>")
            print_info("Example: /skill learn coding-standards.md")
            return

        file_path = " ".join(args)
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

        saved_count = self._review_learned_skills(skills_found)

        print()
        print_info(f"  Done! Saved {saved_count} new skill(s).")
        if saved_count > 0:
            print_info("  Skills will apply to all future conversations.")
        print()

    def _review_learned_skills(self, skills_found):
        """Ask the user about each extracted skill and save approved ones."""
        from .skills import confirm_and_save_skill

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

        return saved_count

    def _skill_clear(self, args):
        """Remove every configured skill."""
        from .skills import clear_skills

        result = clear_skills()
        if result["success"]:
            print_info("ok All skills cleared")
        else:
            print_error(result.get("error", "Failed to clear skills"))

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
                    if choice == "project":
                        # Explicit user action — create the .radsim
                        # scaffolding (skeleton agents.md) if missing
                        memory.project_mem.ensure_initialized()
                        target_file = memory.project_mem.agents_file
                    else:
                        target_file = memory.global_mem.file_path
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

    def _cmd_hook(self, agent, args=None):
        """Create and manage lifecycle hooks."""
        if not args:
            args = self._prompt_hook_action()
            if args is None:
                return

        action = args[0].lower()
        handlers = {
            "list": self._hook_list,
            "add": self._hook_add,
            "toggle": self._hook_toggle,
            "remove": self._hook_remove,
            "on": lambda rest: self._hook_set_enabled(rest, True),
            "off": lambda rest: self._hook_set_enabled(rest, False),
        }
        handler = handlers.get(action)
        if handler is None:
            print_error(f"Unknown action: {action}")
            print_info("Usage: /hook [list | add | toggle | remove | on | off]")
            return
        handler(args[1:])

    def _prompt_hook_action(self):
        """Show the hooks menu and return the equivalent command args."""
        from .menu import interactive_menu

        choice = interactive_menu(
            "HOOKS",
            [
                ("list", "Show configured hooks"),
                ("add", "Create a new hook"),
                ("toggle", "Switch hooks on/off"),
                ("remove", "Delete a hook"),
            ],
        )
        if choice is None:
            return None
        return [choice]

    def _pick_hook_name(self, title):
        """Let the user pick one hook by menu; None when cancelled or empty."""
        from .menu import interactive_menu
        from .user_hooks import load_user_hooks

        hooks = load_user_hooks()
        if not hooks:
            print_info("No hooks configured. Use /hook add to create one.")
            return None
        return interactive_menu(
            title,
            [(hook.name, f"{hook.event} — {hook.command[:50]}") for hook in hooks],
        )

    def _hook_list(self, args):
        """Show every configured hook and how to use them."""
        from .user_hooks import HOOKS_FILE, load_user_hooks

        hooks = load_user_hooks()
        print()
        if not hooks:
            print_info("No hooks configured. Use /hook add to create one.")
            return
        for hook in hooks:
            state = "on " if hook.enabled else "off"
            print(f"  [{state}] {hook.name}  ({hook.event}, matcher: {hook.matcher})")
            print(f"        {hook.command}")
        print()
        print_info(f"Stored in {HOOKS_FILE}")
        print_info("/hook toggle switches hooks on/off; /hook remove deletes one.")

    def _hook_toggle(self, args):
        """Arrow-key on/off switches for every hook, like /settings security."""
        from .menu import toggle_menu
        from .user_hooks import load_user_hooks, set_user_hook_enabled

        hooks = load_user_hooks()
        if not hooks:
            print_info("No hooks configured. Use /hook add to create one.")
            return

        items = [
            {
                "key": hook.name,
                "label": f"{hook.name} ({hook.event}: {hook.command[:40]})",
                "value": hook.enabled,
            }
            for hook in hooks
        ]
        states = toggle_menu("HOOKS ON/OFF", items)
        if states is None:
            print_info("Cancelled.")
            return

        changed = 0
        for hook in hooks:
            new_state = states.get(hook.name, hook.enabled)
            if new_state != hook.enabled:
                set_user_hook_enabled(hook.name, new_state)
                changed += 1
        print_info(f"{changed} hook(s) updated." if changed else "No changes.")

    def _hook_add(self, args):
        """Add a hook: /hook add <name> <event> <matcher> <command...> or interactive."""
        from .user_hooks import DEFAULT_TIMEOUT_SECONDS, VALID_EVENTS, add_user_hook

        if len(args) >= 4:
            name, event, matcher = args[0], args[1], args[2]
            command = " ".join(args[3:])
        else:
            fields = self._prompt_hook_fields(VALID_EVENTS)
            if fields is None:
                print_info("Cancelled.")
                return
            name, event, matcher, command = fields

        from .safety import ask_confirmation

        print()
        print_info(f"Hook '{name}' will run on {event} (matcher: {matcher}):")
        print(f"    {command}")
        if ask_confirmation("  Save this hook?") != "yes":
            print_info("Cancelled.")
            return

        result = add_user_hook(name, event, matcher, command, DEFAULT_TIMEOUT_SECONDS)
        if result["success"]:
            print_info(f"Hook '{name}' saved.")
        else:
            print_error(result["error"])

    def _prompt_hook_fields(self, valid_events):
        """Interactively collect hook fields; None cancels."""
        from .menu import interactive_menu, safe_input
        from .user_hooks import TOOL_EVENTS

        event = interactive_menu(
            "HOOK EVENT",
            [(event, f"Fires on {event.replace('_', ' ')}") for event in valid_events],
        )
        if event is None:
            return None
        name = safe_input("  Hook name (letters, digits, - _): ")
        if not name:
            return None
        if event in TOOL_EVENTS:
            matcher = safe_input("  Tool matcher (glob, e.g. run_shell_command or git_* or *): ")
            if matcher is None:
                return None
        else:
            matcher = "*"  # session events fire unconditionally
        command = safe_input("  Shell command to run: ")
        if not command:
            return None
        return name.strip(), event, (matcher.strip() or "*"), command.strip()

    def _hook_remove(self, args):
        """Delete a hook, offering a picker when no name is given."""
        from .user_hooks import remove_user_hook

        name = args[0] if args else self._pick_hook_name("REMOVE WHICH HOOK?")
        if not name:
            return
        result = remove_user_hook(name)
        if result["success"]:
            print_info(f"Hook '{name}' removed.")
        else:
            print_error(result["error"])

    def _hook_set_enabled(self, args, enabled):
        """Toggle a hook on or off, offering a picker when no name is given."""
        from .user_hooks import set_user_hook_enabled

        action = "TURN ON" if enabled else "TURN OFF"
        name = args[0] if args else self._pick_hook_name(f"{action} WHICH HOOK?")
        if not name:
            return
        result = set_user_hook_enabled(name, enabled)
        if result["success"]:
            print_info(f"Hook '{name}' is now {'enabled' if enabled else 'disabled'}.")
        else:
            print_error(result["error"])
