"""Workflow, planning, analysis, and background slash-command handlers."""

import json

from .output import print_block, print_error, print_info, print_success, print_titled_block
from .runtime_context import get_runtime_context


class WorkflowCommandHandlersMixin:
    """Handlers for planning, analysis, background work, and MCP."""

    @staticmethod
    def _try_job_operation(operation, *arguments):
        """Run one jobs API call and display scheduler failures safely."""
        try:
            return True, operation(*arguments)
        except Exception as error:
            print_error(f"Job operation failed: {error}")
            return False, None

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
            choice = interactive_menu(
                "COMPLEXITY",
                [
                    ("overview", "Score overview"),
                    ("budget", "Set budget"),
                    ("report", "Full file-by-file report"),
                    ("file", "Score a single file"),
                ],
            )
            if choice is None:
                return

            if choice == "overview":
                result = check_budget(os.getcwd())
                budget = result["budget"]
                scan = scan_project_complexity(os.getcwd())
                print_block(format_complexity_report(scan, budget), blank_before=False, blank_after=False)
                return
            if choice == "file":
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
                    message = f"  Current complexity budget: {current}"
                else:
                    message = "  No budget set. Usage: /complexity budget <number>"
                print_block((message,))
                return

            try:
                budget_value = int(args[1])
            except ValueError:
                print_block(("  Budget must be a number. Example: /complexity budget 200",))
                return

            save_budget(budget_value)
            print(f"\n  ok Complexity budget set to {budget_value}")

            result = check_budget(os.getcwd())
            score = result["score"]
            if result["within_budget"]:
                print(f"  ok Currently within budget ({score}/{budget_value})")
            else:
                print(f"  warning: Currently OVER budget ({score}/{budget_value})")
            print()
            return

        if action == "report":
            budget = load_budget()
            scan = scan_project_complexity(os.getcwd())
            print_block(format_complexity_report(scan, budget), blank_before=False, blank_after=False)
            return

        file_path = " ".join(args)
        if os.path.isfile(file_path):
            result = calculate_file_complexity(file_path)
            if result:
                print_block(format_file_report(result), blank_before=False, blank_after=False)
            else:
                print_block((f"  Unsupported file type: {file_path}",))
        else:
            print_block((f"  File not found: {file_path}", "  Usage: /complexity [budget <N> | report | <file>]"))

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
            choice = interactive_menu(
                "ADVERSARIAL REVIEW",
                [
                    ("project", "Scan entire project"),
                    ("file", "Stress test a single file"),
                ],
            )
            if choice is None:
                return

            if choice == "project":
                print("\n  Scanning project for vulnerabilities...")
                results = stress_test_directory(os.getcwd())
                print_block(format_stress_report(results), blank_before=False, blank_after=False)
                return

            if choice == "file":
                path = safe_input("  File path: ")
                if path is None:
                    return
                args = [path]

        file_path = " ".join(args)
        if os.path.isfile(file_path):
            result = stress_test_file(file_path)
            if result:
                print_block(format_stress_report(result), blank_before=False, blank_after=False)
            else:
                print_block((f"  Unsupported file type: {file_path}",))
        else:
            print_block((f"  File not found: {file_path}", "  Usage: /stress [<file>]"))

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
            choice = interactive_menu(
                "CODE ARCHAEOLOGY",
                [
                    ("full", "Full dead code scan"),
                    ("imports", "Unused imports only"),
                    ("deps", "Zombie dependencies only"),
                    ("clean", "Interactive cleanup (review-only)"),
                ],
            )
            if choice is None:
                return

            if choice == "full":
                print("\n  Excavating codebase...")
                results = run_full_archaeology(os.getcwd())
                print_block(format_archaeology_report(results), blank_before=False, blank_after=False)
                return
            args = [choice]

        action = args[0].lower()

        if action == "imports":
            results = scan_unused_imports(os.getcwd())
            print_block(format_imports_report(results), blank_before=False, blank_after=False)
            return

        if action == "deps":
            results = find_zombie_dependencies(os.getcwd())
            print_block(format_deps_report(results), blank_before=False, blank_after=False)
            return

        if action == "clean":
            results = run_full_archaeology(os.getcwd())
            summary = results["summary"]
            total_items = (
                summary["dead_function_count"]
                + summary["unused_import_count"]
                + summary["zombie_dep_count"]
            )

            if total_items == 0:
                print_block(("  Nothing to clean up. Codebase is tidy.",))
                return

            print_block(format_archaeology_report(results), blank_before=False, blank_after=False)
            warning_lines = (
                "  warning: Cleanup is review-only. No files will be modified.",
                "  To remove items, edit the files manually after reviewing.",
                "  This ensures you never accidentally delete needed code.",
            )
            print_block(warning_lines, blank_before=False)
            return

        print_block((f"  Unknown sub-command: {action}", "  Usage: /archaeology [imports | deps | clean]"))

    def _cmd_plan(self, agent, args=None):
        """Structured plan-confirm-execute workflow."""
        from .menu import interactive_menu, safe_input
        from .planner import get_plan_manager

        plan_manager = get_plan_manager()

        if not args:
            if plan_manager.active_plan:
                choice = interactive_menu(
                    "PLAN",
                    [
                        ("show", "Show current plan"),
                        ("approve", "Approve plan for execution"),
                        ("reject", "Reject and discard plan"),
                        ("step", "Execute next step"),
                        ("run", "Execute all remaining steps"),
                        ("status", "Show progress"),
                        ("export", "Export plan to markdown"),
                        ("history", "Show past plans"),
                        ("new", "Create a new plan"),
                    ],
                )
            else:
                choice = interactive_menu(
                    "PLAN",
                    [
                        ("new", "Create a new plan"),
                        ("history", "Show past plans"),
                    ],
                )
            if choice is None:
                return

            if choice == "new":
                description = safe_input("  Describe what you want to do: ")
                if description is None:
                    return
                args = [description]
            else:
                args = [choice]

        action = args[0].lower()

        if action == "show":
            print(plan_manager.show_plan())
            return

        if action == "approve":
            print(plan_manager.approve_plan())
            return

        if action == "reject":
            print(plan_manager.reject_plan())
            return

        if action == "status":
            print(plan_manager.get_status())
            return

        if action == "history":
            print(plan_manager.get_history())
            return

        if action == "export":
            print(plan_manager.export_plan())
            return

        if action == "step":
            if not plan_manager.active_plan:
                print("  No active plan. Use '/plan <description>' to create one.")
                return
            if plan_manager.active_plan.status not in ("approved", "in_progress"):
                print("  Plan must be approved first. Use '/plan approve'.")
                return

            next_step = plan_manager.get_next_step()
            if not next_step:
                print("  ok All steps completed!")
                return

            step_index, step = next_step
            print(f"\n  Executing Step {step_index + 1}: {step.description}")
            if step.files:
                print(f"  Files: {', '.join(step.files)}")
            print(f"  Risk: {step.risk.upper()}")
            print()

            plan_manager.mark_step_in_progress(step_index)
            step_prompt = (
                f"Execute this plan step: {step.description}\n"
                f"Files to modify: {', '.join(step.files) if step.files else 'as needed'}\n"
                f"Risk level: {step.risk}"
            )
            agent.process_message(step_prompt)
            plan_manager.mark_step_complete(step_index)

            try:
                get_runtime_context().get_memory().project_mem.record_decision(
                    f"Completed plan step: {step.description}"
                )
            except Exception:
                pass

            print(f"\n  ok Step {step_index + 1} completed.")
            print(plan_manager.get_status())
            return

        if action == "run":
            if not plan_manager.active_plan:
                print("  No active plan. Use '/plan <description>' to create one.")
                return
            if plan_manager.active_plan.status not in ("approved", "in_progress"):
                print("  Plan must be approved first. Use '/plan approve'.")
                return

            while True:
                next_step = plan_manager.get_next_step()
                if not next_step:
                    print("\n  ok All steps completed!")
                    break

                step_index, step = next_step
                print(f"\n  ── Step {step_index + 1}/{len(plan_manager.active_plan.steps)}: {step.description}")

                if step.checkpoint:
                    try:
                        confirm = input("  Continue? [y/n]: ").strip().lower()
                    except (KeyboardInterrupt, EOFError):
                        print("\n  Plan execution paused.")
                        return
                    if confirm not in ("y", "yes", ""):
                        print("  Plan execution paused.")
                        return

                plan_manager.mark_step_in_progress(step_index)
                step_prompt = (
                    f"Execute this plan step: {step.description}\n"
                    f"Files to modify: {', '.join(step.files) if step.files else 'as needed'}\n"
                    f"Risk level: {step.risk}"
                )
                agent.process_message(step_prompt)
                plan_manager.mark_step_complete(step_index)

                try:
                    get_runtime_context().get_memory().project_mem.record_decision(
                        f"Completed plan step: {step.description}"
                    )
                except Exception:
                    pass

                print(f"  ok Step {step_index + 1} completed.")

            print(plan_manager.get_status())
            return

        description = " ".join(args)
        print_block((f"  Generating plan for: {description}", "  Thinking..."), blank_after=False)

        from .prompts import PLANNING_SYSTEM_PROMPT

        plan_prompt = (
            f"{PLANNING_SYSTEM_PROMPT}\n\n"
            f"Task: {description}\n\n"
            f"Analyze the current project and generate a structured implementation plan."
        )
        response = agent.process_message(plan_prompt)

        if not response:
            response = getattr(agent, "_last_response", None)

        if response:
            plan = plan_manager.create_plan_from_response(response)
            if plan:
                print(plan_manager.show_plan())
            else:
                lines = (
                    "  warning: Could not parse plan from response.",
                    "  The response was displayed above. Try again with a clearer description.",
                )
                print_block(lines, blank_before=False, blank_after=False)
        else:
            print("  warning: No response from agent. Check your API key and provider.")

    def _cmd_panning(self, agent, args=None):
        """Brain-dump processing & synthesis."""
        from .menu import interactive_menu, safe_input
        from .panning import get_panning_session, start_new_session

        session = get_panning_session()

        if not args:
            if session.active:
                choice = interactive_menu(
                    "PANNING",
                    [
                        ("end", "End session and generate synthesis"),
                        ("file", "Add a file to the dump"),
                        ("refine", "Refine the last synthesis"),
                        ("bridge", "Bridge to /plan"),
                    ],
                )
            else:
                choice = interactive_menu(
                    "PANNING",
                    [
                        ("start", "Start a new panning session"),
                        ("text", "Process a one-shot brain dump"),
                        ("file", "Process a text/transcript file"),
                    ],
                )
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
            lines = (session.process_file(path), "  Type '/panning end' to generate synthesis.")
            print_block(lines, blank_before=False, blank_after=False)
            return

        if action == "end":
            if not session.dumps:
                print("  Nothing to synthesise. Dump some thoughts first!")
                return

            print("\n  Synthesising your thoughts...")

            from .prompts import PANNING_SYSTEM_PROMPT

            panning_prompt = (
                f"{PANNING_SYSTEM_PROMPT}\n\nBrain dump content:\n\n{session.get_all_dumps()}"
            )
            response = agent.process_message(panning_prompt)

            if not response:
                response = getattr(agent, "_last_response", None)

            if response:
                synthesis = session.parse_synthesis(response)
                if synthesis:
                    print(synthesis.format_display())
                else:
                    print("  warning: Could not parse synthesis. Response displayed above.")
            else:
                print("  warning: No response from agent.")

            session.end()
            return

        if action == "refine":
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

            if not response:
                response = getattr(agent, "_last_response", None)

            if response:
                new_synthesis = session.parse_synthesis(response)
                if new_synthesis:
                    print(new_synthesis.format_display())
                else:
                    print("  warning: Could not parse refined synthesis.")
            return

        if action == "bridge":
            synthesis = session.get_latest_synthesis()
            if not synthesis:
                print("  No synthesis to bridge. Run '/panning end' first.")
                return

            plan_description = synthesis.to_plan_description()
            print(f"\n  Bridging to /plan with: {plan_description[:80]}...")
            self._cmd_plan(agent, [plan_description])
            return

        if action == "start":
            session = start_new_session()
            print(session.start())
            return

        if not session.active:
            session = start_new_session()
            session.start()
        session.add_dump(" ".join(args))
        lines = (
            f"  ok Added to panning session ({len(session.dumps)} dump(s) collected)",
            "  Keep dumping, or type '/panning end' to synthesise.",
        )
        print_block(lines, blank_before=False, blank_after=False)

    def _cmd_subagent(self, agent, args=None):
        """Manage the persistent sub-agent model and instruction profiles."""
        parts = list(args) if args else self._prompt_subagent_action()
        if not parts:
            return

        action = parts[0].lower()
        argument = " ".join(parts[1:]).strip()

        actions = {
            "status": lambda: self._subagent_status(agent),
            "model": lambda: self._subagent_choose_model(agent),
            "profiles": lambda: self._subagent_list_profiles(),
            "create": lambda: self._subagent_create_profile(),
            "show": lambda: self._subagent_show_profile(argument),
            "edit": lambda: self._subagent_edit_profile(argument),
            "delete": lambda: self._subagent_delete_profile(argument),
            "run": lambda: self._subagent_run(agent, argument),
        }

        handler = actions.get(action)
        if handler is None:
            print_error(f"Unknown /subagent action '{action}'")
            print_info("Actions: status, model, profiles, create, show, edit, delete, run")
            return
        handler()

    def _prompt_subagent_action(self):
        """Show the sub-agent menu and return the equivalent command args."""
        from .menu import interactive_menu

        choice = interactive_menu(
            "SUB-AGENTS",
            [
                ("status", "Show the saved model and profiles"),
                ("model", "Choose and save the sub-agent model"),
                ("profiles", "List profiles and their limits"),
                ("run", "Run one task under a profile"),
                ("create", "Create a custom instruction profile"),
                ("show", "Show one custom profile"),
                ("edit", "Edit a custom profile's instructions"),
                ("delete", "Delete a custom profile"),
            ],
        )
        if choice is None:
            return None
        return [choice]

    def _pick_custom_profile(self, title):
        """Let the user pick one custom profile by menu.

        Returns None when there are none or the user cancels, so every caller
        works with no typed argument at all.
        """
        from .menu import interactive_menu
        from .sub_agent_profiles import load_custom_profiles

        profiles = load_custom_profiles()
        if not profiles:
            print_info("No custom profiles yet. Use /subagent create to add one.")
            return None

        return interactive_menu(
            title,
            [
                (profile["id"], f"{profile['name']} (extends {profile['base_profile']})")
                for profile in profiles
            ],
        )

    def _pick_run_profile(self):
        """Let the user pick the profile one /subagent run task will use.

        Returns:
            The delegation arguments for the chosen profile, or None when
            cancelled. Custom profiles resolve through ``custom_profile`` so
            their locked base profile still decides permissions.
        """
        from .menu import interactive_menu
        from .sub_agent_profiles import CAPABILITY_PROFILES, load_custom_profiles

        options = [
            (f"profile:{name}", profile["description"])
            for name, profile in sorted(CAPABILITY_PROFILES.items())
        ]
        options.extend(
            (f"custom:{profile['id']}", f"{profile['name']} (extends {profile['base_profile']})")
            for profile in load_custom_profiles()
        )

        choice = interactive_menu("SUB-AGENT PROFILE", options)
        if choice is None:
            return None

        kind, _separator, value = choice.partition(":")
        return {"custom_profile": value} if kind == "custom" else {"profile": value}

    def _subagent_status(self, agent):
        """Show the saved sub-agent selection and available profiles."""
        from .agent_config import get_agent_config_manager
        from .sub_agent_profiles import describe_profiles, load_custom_profiles

        config_manager = get_agent_config_manager()
        provider, model = config_manager.get_subagent_selection()

        lines = ["  Sub-agent settings", ""]
        if provider and model:
            lines.append(f"  Model:      {provider} / {model}")
        else:
            lines.append("  Model:      not selected — run /subagent model")
        lines.extend(
            (
                f"  Streaming:  {'on' if config_manager.get('subagents.stream_output', True) else 'off'}",
                f"  Parallel:   up to {config_manager.get('subagents.max_parallel', 3)} at a time",
                f"  Iterations: {config_manager.get('subagents.max_iterations', 10)} per task",
                "",
                "  This selection is separate from your main model and survives",
                "  /clear, restarts, and /switch.",
                "",
                "  Built-in profiles",
                "",
            )
        )
        lines.extend(
            f"    {row['name']:<10} {row['description']}" for row in describe_profiles()
        )

        custom = load_custom_profiles()
        if custom:
            lines.extend(("", "  Custom profiles", ""))
            lines.extend(
                f"    {profile['id']:<16} extends {profile['base_profile']}" for profile in custom
            )

        print_block(lines)

    def _subagent_choose_model(self, agent):
        """Select and persist the sub-agent provider and model."""
        provider, model = agent._prompt_subagent_model()
        if not provider or not model:
            print_info("Sub-agent model unchanged.")

    def _subagent_list_profiles(self):
        """List built-in and custom profiles with their boundaries."""
        from .sub_agent_profiles import describe_profiles, load_custom_profiles

        lines = ["  Built-in capability profiles", ""]
        for row in describe_profiles():
            limits = [
                f"{row['tool_count']} tools",
                "background ok" if row["background"] else "foreground only",
                "can edit files" if row["mutation"] else "read-only",
                "network" if row["network"] else "no network",
            ]
            lines.append(f"    {row['name']:<10} {row['description']}")
            lines.append(f"    {'':<10} {' · '.join(limits)}")

        custom = load_custom_profiles()
        lines.extend(("", "  Custom instruction profiles", ""))
        if custom:
            lines.extend(
                f"    {profile['id']:<16} {profile['name']} (extends {profile['base_profile']})"
                for profile in custom
            )
        else:
            lines.append("    none — create one with /subagent create")

        print_block(lines)

    def _subagent_create_profile(self):
        """Create a custom instruction profile on top of a locked base profile."""
        from .menu import interactive_menu, safe_input
        from .sub_agent_profiles import CAPABILITY_PROFILES, save_custom_profile

        profile_id = safe_input("  Profile id (lowercase, e.g. api-reviewer): ")
        if not profile_id:
            print_info("Cancelled.")
            return

        name = safe_input("  Display name: ")
        if not name:
            print_info("Cancelled.")
            return

        base_options = [
            (profile_name, profile["description"])
            for profile_name, profile in sorted(CAPABILITY_PROFILES.items())
        ]
        base_profile = interactive_menu("BASE CAPABILITY PROFILE", base_options)
        if base_profile is None:
            print_info("Cancelled.")
            return

        print_info("Instructions refine how the sub-agent works. They cannot add tools.")
        instructions = safe_input("  Instructions: ")
        if not instructions:
            print_info("Cancelled.")
            return

        result = save_custom_profile(profile_id.strip().lower(), name, base_profile, instructions)
        if not result.get("success"):
            print_error(result.get("error", "Could not save profile"))
            return

        verb = "updated" if result.get("replaced") else "created"
        print_success(f"Profile '{result['profile']['id']}' {verb} (extends {base_profile})")

    def _subagent_show_profile(self, profile_id):
        """Show one custom profile and the boundary it inherits."""
        from .sub_agent_profiles import get_custom_profile, get_profile

        profile_id = profile_id or self._pick_custom_profile("SHOW CUSTOM PROFILE")
        if not profile_id:
            return

        profile = get_custom_profile(profile_id)
        if profile is None:
            print_error(f"No custom profile named '{profile_id}'")
            return

        base = get_profile(profile["base_profile"])
        print_block(
            [
                f"  Profile: {profile['id']}",
                "",
                f"  Name:          {profile['name']}",
                f"  Base profile:  {profile['base_profile']} — {base['description']}",
                f"  Background:    {'allowed' if base['allows_background'] else 'not allowed'}",
                f"  File changes:  {'allowed' if base['allows_mutation'] else 'not allowed'}",
                f"  Network:       {'allowed' if base['allows_network'] else 'not allowed'}",
                f"  Tools:         {len(base['tools'])} from the base allowlist",
                "",
                "  Instructions",
                "",
                *(f"    {line}" for line in profile["instructions"].splitlines()),
                "",
                "  Instructions cannot widen the base profile.",
            ]
        )

    def _subagent_edit_profile(self, profile_id):
        """Edit a custom profile's instructions without changing its model."""
        from .menu import safe_input
        from .sub_agent_profiles import get_custom_profile, save_custom_profile

        profile_id = profile_id or self._pick_custom_profile("EDIT CUSTOM PROFILE")
        if not profile_id:
            return

        profile = get_custom_profile(profile_id)
        if profile is None:
            print_error(f"No custom profile named '{profile_id}'")
            return

        print_info(f"Current instructions: {profile['instructions']}")
        instructions = safe_input("  New instructions: ")
        if not instructions:
            print_info("Cancelled — profile unchanged.")
            return

        result = save_custom_profile(
            profile["id"], profile["name"], profile["base_profile"], instructions
        )
        if not result.get("success"):
            print_error(result.get("error", "Could not save profile"))
            return
        print_success(f"Profile '{profile['id']}' updated")

    def _subagent_delete_profile(self, profile_id):
        """Delete a custom profile after an explicit confirmation."""
        from .safety import confirm_action
        from .sub_agent_profiles import delete_custom_profile, get_custom_profile

        profile_id = profile_id or self._pick_custom_profile("DELETE CUSTOM PROFILE")
        if not profile_id:
            return

        if get_custom_profile(profile_id) is None:
            print_error(f"No custom profile named '{profile_id}'")
            return

        if not confirm_action(f"Delete custom sub-agent profile '{profile_id}'?", config=None):
            print_info("Cancelled — profile kept.")
            return

        result = delete_custom_profile(profile_id)
        if not result.get("success"):
            print_error(result.get("error", "Could not delete profile"))
            return
        print_success(f"Profile '{profile_id}' deleted")

    def _subagent_run(self, agent, argument):
        """Run one explicit sub-agent task using the saved model."""
        from .menu import safe_input

        parts = argument.split(maxsplit=1)
        if parts:
            profile_arguments = {"profile": parts[0]}
        else:
            profile_arguments = self._pick_run_profile()
            if profile_arguments is None:
                return

        task_description = parts[1] if len(parts) > 1 else safe_input("  Task for the sub-agent: ")
        if not task_description:
            print_info("Cancelled — no task given.")
            return

        result = agent._handle_delegate_task(
            {
                "task_description": task_description,
                "background": False,
                **profile_arguments,
            }
        )
        if not result.get("success"):
            print_error(result.get("error", "Sub-agent task failed"))
            return
        print_block(["  Sub-agent result (untrusted evidence)", "", *(
            f"  {line}" for line in str(result.get("content", "")).splitlines()
        )])

    def _cmd_background(self, agent, args=None):
        """View and manage background sub-agent jobs."""
        import time as time_module

        from .background import get_job_manager

        manager = get_job_manager()
        jobs = manager.list_jobs()

        if not args:
            if not jobs:
                print_info("No background jobs.")
                return

            job_lines = []
            for job_index, job in enumerate(jobs):
                status_icon = {
                    "running": "\033[33m...\033[0m",
                    "completed": "\033[32m ok\033[0m",
                    "failed": "\033[31m xx\033[0m",
                    "cancelled": "\033[2m --\033[0m",
                }.get(job.status.value, " ? ")
                duration = f"{job.duration:.1f}s"
                job_lines.extend(
                    (
                        f"  [{status_icon}] #{job.job_id}  {job.model}  ({duration})",
                        f"        {job.description[:80]}",
                    )
                )
                if job.sub_tasks:
                    job_lines.extend(
                        f"        {index}. {sub_task[:70]}"
                        for index, sub_task in enumerate(job.sub_tasks, 1)
                    )
                if job_index < len(jobs) - 1:
                    job_lines.append("")
            print_titled_block(
                "BACKGROUND JOBS",
                job_lines,
                footer=("  /bg <id> — view results  |  /bg cancel <id>  |  /bg clear",),
            )
            return

        action = args[0].lower()

        if action == "clear":
            removed = manager.clear_finished()
            print_info(f"Cleared {removed} finished job(s).")
            return

        if action == "cancel":
            if len(args) >= 2:
                try:
                    job_id = int(args[1])
                except ValueError:
                    print_error("Job ID must be a number.")
                    return
            else:
                from .background import JobStatus
                from .menu import interactive_menu

                running = [job for job in jobs if job.status == JobStatus.RUNNING]
                if not running:
                    print_info("No running jobs to cancel.")
                    return
                choice = interactive_menu(
                    "CANCEL WHICH JOB?",
                    [(str(job.job_id), job.description[:60]) for job in running],
                )
                if choice is None:
                    return
                job_id = int(choice)

            if manager.cancel_job(job_id):
                print_success(f"Job #{job_id} cancelled.")
            else:
                print_error(f"Job #{job_id} not found or not running.")
            return

        try:
            job_id = int(action)
        except ValueError:
            print_error("Usage: /bg [<id> | cancel <id> | clear]")
            return

        job = manager.get_job(job_id)
        if not job:
            print_error(f"Job #{job_id} not found.")
            return

        status_display = {
            "running": "\033[33mRUNNING\033[0m",
            "completed": "\033[32mCOMPLETED\033[0m",
            "failed": "\033[31mFAILED\033[0m",
            "cancelled": "\033[2mCANCELLED\033[0m",
        }.get(job.status.value, job.status.value)
        detail_rows = [
            ("Status:", status_display),
            ("Model:", f"{job.provider}/{job.model}" if job.provider else job.model),
            ("Profile:", job.profile),
            ("Duration:", f"{job.duration:.1f}s"),
        ]
        if job.input_tokens or job.output_tokens:
            detail_rows.append(("Tokens:", f"{job.input_tokens} in / {job.output_tokens} out"))
        started = time_module.strftime("%H:%M:%S", time_module.localtime(job.started_at))
        detail_rows.extend((("Started:", started), ("Task:", job.description)))
        detail_lines = [f"  {label:<10}{value}" for label, value in detail_rows]

        if job.sub_tasks:
            detail_lines.extend(
                (
                    "",
                    "  ─── Sub-tasks ───",
                    *(f"    {index}. {sub_task}" for index, sub_task in enumerate(job.sub_tasks, 1)),
                )
            )
        print_titled_block(f"BACKGROUND JOB #{job.job_id}", detail_lines)

        if job.error:
            print_error(f"Error: {job.error}")
        elif job.result_content:
            print_block(
                ("  ─── Output ───", "", *(f"  {line}" for line in job.result_content.splitlines())),
                blank_before=False,
            )
        elif job.status.value == "running":
            print_info("Still running...")
        else:
            print_info("No output.")

    def _cmd_job(self, agent, args=None):
        """Manage scheduled cron jobs."""
        from .jobs import (
            add_job,
            describe_schedule,
            disable_job,
            enable_job,
            list_jobs,
            remove_job,
            resolve_schedule,
            run_job_now,
        )
        from .menu import interactive_menu, safe_input

        if not args:
            args = ["list"]

        action = args[0].lower()

        if action in ("list", "ls"):
            operation_succeeded, jobs = self._try_job_operation(list_jobs)
            if not operation_succeeded:
                return
            if not jobs:
                print_info("No scheduled jobs. Use '/job add' to create one.")
                return

            job_lines = []
            for job in jobs:
                status_icon = "\033[32mok\033[0m" if job.enabled else "\033[33m⏸\033[0m"
                schedule_desc = describe_schedule(job.schedule)
                if job.is_radsim_task:
                    command_display = f'radsim "{job.command[:50]}"'
                else:
                    command_display = job.command[:60]
                job_lines.append(
                    f"  [{status_icon}] #{job.job_id}  {schedule_desc:<18} {command_display}"
                )
                if job.last_run:
                    last = job.last_run[:19].replace("T", " ")
                    job_lines.append(f"        last run: {last}")
            print_titled_block(
                "SCHEDULED JOBS",
                job_lines,
                footer=(
                    "  /job add | /job remove <id> | /job pause <id> | "
                    "/job resume <id> | /job run <id>",
                ),
            )
            return

        if action == "add":
            job_type = interactive_menu(
                "JOB TYPE",
                [
                    ("radsim", "RadSim task (e.g., 'run pytest and report results')"),
                    ("shell", "Shell command (e.g., 'backup_db.sh')"),
                ],
            )
            if job_type is None:
                return

            is_radsim_task = job_type == "radsim"
            command = safe_input("  Task for RadSim to run: " if is_radsim_task else "  Shell command: ")
            if not command:
                return

            schedule_choice = interactive_menu(
                "SCHEDULE",
                [
                    ("hourly", "Every hour (at :00)"),
                    ("daily", "Daily at 9:00 AM"),
                    ("weekdays", "Weekdays at 9:00 AM"),
                    ("weekly", "Weekly on Monday at 9:00 AM"),
                    ("monthly", "Monthly on the 1st at 9:00 AM"),
                    ("custom", "Custom cron expression or time"),
                ],
            )
            if schedule_choice is None:
                return

            if schedule_choice == "custom":
                print_info("Enter a cron expression (e.g., '0 9 * * *')")
                print_info("  Or use presets: 'daily @14:30', 'weekdays @8:00'")
                schedule_input = safe_input("  Schedule: ")
                if not schedule_input:
                    return
            else:
                schedule_input = schedule_choice

            schedule = resolve_schedule(schedule_input)
            if not schedule:
                print_error(f"Invalid schedule: '{schedule_input}'")
                return

            description = safe_input("  Short description: ")
            if not description:
                description = command[:50]

            operation_succeeded, job = self._try_job_operation(
                add_job,
                schedule,
                command,
                description,
                is_radsim_task,
            )
            if not operation_succeeded:
                return
            schedule_desc = describe_schedule(job.schedule)
            print_success(f"Job #{job.job_id} created: {schedule_desc} — {description}")
            return

        if action in ("remove", "rm", "delete", "del"):
            job_id = self._resolve_job_id(args, list_jobs, describe_schedule, "REMOVE WHICH JOB?")
            if job_id is None:
                return
            operation_succeeded, removed = self._try_job_operation(remove_job, job_id)
            if not operation_succeeded:
                return
            if removed:
                print_success(f"Job #{job_id} removed.")
            else:
                print_error(f"Job #{job_id} not found.")
            return

        if action in ("pause", "disable"):
            job_id = self._resolve_job_id(args, list_jobs, describe_schedule, "PAUSE WHICH JOB?")
            if job_id is None:
                return
            operation_succeeded, disabled = self._try_job_operation(disable_job, job_id)
            if not operation_succeeded:
                return
            if disabled:
                print_success(f"Job #{job_id} paused (removed from crontab).")
            else:
                print_error(f"Job #{job_id} not found.")
            return

        if action in ("resume", "enable"):
            job_id = self._resolve_job_id(args, list_jobs, describe_schedule, "RESUME WHICH JOB?")
            if job_id is None:
                return
            operation_succeeded, enabled = self._try_job_operation(enable_job, job_id)
            if not operation_succeeded:
                return
            if enabled:
                print_success(f"Job #{job_id} resumed (added back to crontab).")
            else:
                print_error(f"Job #{job_id} not found.")
            return

        if action == "run":
            job_id = self._resolve_job_id(args, list_jobs, describe_schedule, "RUN WHICH JOB NOW?")
            if job_id is None:
                return
            print_info(f"Running job #{job_id}...")
            operation_succeeded, run_result = self._try_job_operation(run_job_now, job_id)
            if not operation_succeeded:
                return
            success, output = run_result
            if success:
                print_success(f"Job #{job_id} completed.")
            else:
                print_error(f"Job #{job_id} failed.")
            print_block(f"  {line}" for line in output.splitlines()[:20])
            return

        print_error(f"Unknown subcommand: '{action}'")
        print_info("Usage: /job [list | add | remove | pause | resume | run]")

    def _resolve_job_id(self, args, list_jobs, describe_schedule, picker_title):
        """Resolve a job id from args, or show a picker when none was typed.

        Returns the integer job id, or None to abort (bad input, no jobs,
        or the user cancelled the picker).
        """
        from .menu import interactive_menu

        if len(args) >= 2:
            try:
                return int(args[1])
            except ValueError:
                print_error("Job ID must be a number.")
                return None

        operation_succeeded, jobs = self._try_job_operation(list_jobs)
        if not operation_succeeded:
            return None
        if not jobs:
            print_info("No scheduled jobs. Use '/job add' to create one.")
            return None

        options = [
            (
                str(job.job_id),
                f"{describe_schedule(job.schedule)} — {job.command[:45]}"
                + ("" if job.enabled else " (paused)"),
            )
            for job in jobs
        ]
        choice = interactive_menu(picker_title, options)
        if choice is None:
            return None
        return int(choice)

    def _cmd_mcp(self, agent, args=None):
        """Manage MCP (Model Context Protocol) server connections."""
        from .mcp_client import get_mcp_manager, is_mcp_sdk_installed
        from .menu import safe_input

        if not is_mcp_sdk_installed():
            print_info("MCP requires the MCP SDK which is not currently installed.")
            answer = safe_input("  Install now? (pip install mcp) [Y/n]: ")
            if answer is None or answer.lower() in ("n", "no"):
                print_info("You can install later with: pip install radsimcli[mcp]")
                return

            import subprocess
            import sys

            print_info("Installing MCP SDK...")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "mcp>=1.0.0"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print_error(f"Installation failed: {result.stderr.strip()}")
                return
            print_success("MCP SDK installed successfully!")
            print_info("Run /mcp again to get started.")
            return

        manager = get_mcp_manager()

        if not args:
            self._mcp_status(manager)
            return

        subcommand = args[0].lower()

        if subcommand == "status":
            self._mcp_status(manager)
            return

        if subcommand == "list":
            self._mcp_list(manager)
            return

        if subcommand == "connect":
            name = args[1] if len(args) >= 2 else self._pick_mcp_server(manager, "CONNECT WHICH SERVER?")
            if not name:
                return
            print_info(f"Connecting to '{name}'...")
            if manager.connect(name):
                connection = manager._connections.get(name)
                tool_count = len(connection.tools) if connection else 0
                print_success(f"Connected to '{name}' ({tool_count} tools)")
            else:
                connection = manager._connections.get(name)
                error = connection.error if connection else "Unknown error"
                print_error(f"Failed to connect to '{name}': {error}")
            return

        if subcommand == "disconnect":
            name = args[1] if len(args) >= 2 else self._pick_mcp_server(manager, "DISCONNECT WHICH SERVER?")
            if not name:
                return
            manager.disconnect(name)
            print_success(f"Disconnected from '{name}'")
            return

        if subcommand == "add":
            self._mcp_add_interactive(manager)
            return

        if subcommand == "remove":
            name = args[1] if len(args) >= 2 else self._pick_mcp_server(manager, "REMOVE WHICH SERVER?")
            if not name:
                return
            if manager.remove_server_config(name):
                print_success(f"Removed server '{name}'")
            else:
                print_error(f"No server named '{name}'")
            return

        print_error(f"Unknown subcommand: '{subcommand}'")
        print_info("Usage: /mcp [status | list | connect | disconnect | add | remove]")

    def _pick_mcp_server(self, manager, picker_title):
        """Let the user pick a configured MCP server; None if none/cancelled."""
        from .menu import interactive_menu

        configs = manager.get_server_configs()
        if not configs:
            print_info("No MCP servers configured. Use /mcp add to add one.")
            return None
        choice = interactive_menu(
            picker_title,
            [(name, config.transport) for name, config in configs.items()],
        )
        return choice

    def _mcp_status(self, manager):
        """Show MCP server connection status."""
        statuses = manager.get_connection_status()
        if not statuses:
            print_info("No MCP servers configured. Use /mcp add to add one.")
            return

        status_lines = [f" MCP Servers ({len(statuses)}):", "-" * 50]
        for status in statuses:
            if status["connected"]:
                state = "connected"
                tools = f" ({status['tool_count']} tools)"
            elif status["error"]:
                state = "ERROR"
                tools = f" — {status['error']}"
            else:
                state = "disconnected"
                tools = ""

            auto = " [auto]" if status["auto_connect"] else ""
            status_lines.append(
                f"  {status['name']} ({status['transport']}{auto}): {state}{tools}"
            )
        print_block(status_lines)

    def _mcp_list(self, manager):
        """Show all tools from connected MCP servers."""
        tools = manager.get_connected_tool_list()
        if not tools:
            print_info("No MCP tools available. Connect a server first with /mcp connect <name>.")
            return

        tool_lines = [f" MCP Tools ({len(tools)}):", "-" * 50]
        current_server = None
        for tool in tools:
            if tool["server"] != current_server:
                current_server = tool["server"]
                tool_lines.extend(("", f"  {current_server}:"))
            description = f" — {tool['description']}" if tool["description"] else ""
            tool_lines.append(f"    {tool['namespaced']}{description}")
        print_block(tool_lines)

    def _mcp_add_interactive(self, manager):
        """Guided MCP server addition."""
        from .mcp_client import MCPServerConfig
        from .menu import interactive_menu, safe_input

        print_info("Add a new MCP server")
        print()

        name = safe_input("  Server name: ")
        if not name:
            return

        transport = interactive_menu(
            "Transport",
            [
                ("stdio", "Local process (command + args)"),
                ("sse", "Server-Sent Events (remote URL)"),
                ("streamable_http", "Streamable HTTP (remote URL)"),
            ],
        )
        if not transport:
            return

        config = MCPServerConfig(name=name, transport=transport)

        if transport == "stdio":
            command = safe_input("  Command (e.g. npx, python): ")
            if not command:
                return
            config.command = command

            args_string = safe_input("  Args (space-separated, or empty): ")
            if args_string:
                config.args = args_string.split()
        else:
            url = safe_input("  Server URL: ")
            if not url:
                return
            config.url = url

        auto_string = safe_input("  Auto-connect on startup? [Y/n]: ")
        config.auto_connect = auto_string.lower() not in ("n", "no") if auto_string else True

        manager.add_server_config(config)
        print_success(f"Server '{name}' added to ~/.radsim/mcp.json")

        connect_now = safe_input("  Connect now? [Y/n]: ")
        if not connect_now or connect_now.lower() not in ("n", "no"):
            print_info(f"Connecting to '{name}'...")
            if manager.connect(name):
                connection = manager._connections.get(name)
                tool_count = len(connection.tools) if connection else 0
                print_success(f"Connected ({tool_count} tools)")
            else:
                connection = manager._connections.get(name)
                error = connection.error if connection else "Unknown error"
                print_error(f"Connection failed: {error}")
