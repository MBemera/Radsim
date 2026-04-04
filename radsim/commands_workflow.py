"""Workflow, planning, analysis, and background slash-command handlers."""

import json

from .output import print_error, print_info, print_success
from .runtime_context import get_runtime_context


class WorkflowCommandHandlersMixin:
    """Handlers for planning, analysis, background work, and MCP."""

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
                for line in format_complexity_report(scan, budget):
                    print(line)
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
                for line in format_stress_report(results):
                    print(line)
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
                for line in format_archaeology_report(results):
                    print(line)
                return
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
            results = run_full_archaeology(os.getcwd())
            summary = results["summary"]
            total_items = (
                summary["dead_function_count"]
                + summary["unused_import_count"]
                + summary["zombie_dep_count"]
            )

            if total_items == 0:
                print("\n  Nothing to clean up! Codebase is tidy. ✅")
                print()
                return

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
                print("  ✅ All steps completed!")
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

            print(f"\n  ✓ Step {step_index + 1} completed.")
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
                    print("\n  ✅ All steps completed!")
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

                print(f"  ✓ Step {step_index + 1} completed.")

            print(plan_manager.get_status())
            return

        description = " ".join(args)
        print(f"\n  Generating plan for: {description}")
        print("  Thinking...")

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
            print(session.process_file(path))
            print("  Type '/panning end' to generate synthesis.")
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
                    print("  ⚠ Could not parse synthesis. Response displayed above.")
            else:
                print("  ⚠ No response from agent.")

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
                    print("  ⚠ Could not parse refined synthesis.")
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
        print(f"  ✓ Added to panning session ({len(session.dumps)} dump(s) collected)")
        print("  Keep dumping, or type '/panning end' to synthesise.")

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

            print()
            print("  ═══ BACKGROUND JOBS ═══")
            print()
            for job in jobs:
                status_icon = {
                    "running": "\033[33m...\033[0m",
                    "completed": "\033[32m ok\033[0m",
                    "failed": "\033[31m xx\033[0m",
                    "cancelled": "\033[2m --\033[0m",
                }.get(job.status.value, " ? ")
                duration = f"{job.duration:.1f}s"
                print(f"  [{status_icon}] #{job.job_id}  {job.model}  ({duration})")
                print(f"        {job.description[:80]}")
                if job.sub_tasks:
                    for index, sub_task in enumerate(job.sub_tasks, 1):
                        print(f"        {index}. {sub_task[:70]}")
                print()
            print("  /bg <id> — view results  |  /bg cancel <id>  |  /bg clear")
            print()
            return

        action = args[0].lower()

        if action == "clear":
            removed = manager.clear_finished()
            print_info(f"Cleared {removed} finished job(s).")
            return

        if action == "cancel" and len(args) >= 2:
            try:
                job_id = int(args[1])
            except ValueError:
                print_error("Usage: /bg cancel <id>")
                return

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

        print()
        print(f"  ═══ BACKGROUND JOB #{job.job_id} ═══")
        print()

        status_display = {
            "running": "\033[33mRUNNING\033[0m",
            "completed": "\033[32mCOMPLETED\033[0m",
            "failed": "\033[31mFAILED\033[0m",
            "cancelled": "\033[2mCANCELLED\033[0m",
        }.get(job.status.value, job.status.value)
        print(f"  Status:   {status_display}")
        print(f"  Model:    {job.model}")
        print(f"  Tier:     {job.tier}")
        print(f"  Duration: {job.duration:.1f}s")
        if job.input_tokens or job.output_tokens:
            print(f"  Tokens:   {job.input_tokens} in / {job.output_tokens} out")
        started = time_module.strftime("%H:%M:%S", time_module.localtime(job.started_at))
        print(f"  Started:  {started}")
        print(f"  Task:     {job.description}")

        if job.sub_tasks:
            print()
            print("  ─── Sub-tasks ───")
            for index, sub_task in enumerate(job.sub_tasks, 1):
                print(f"    {index}. {sub_task}")

        print()

        if job.error:
            print_error(f"Error: {job.error}")
        elif job.result_content:
            print("  ─── Output ───")
            print()
            for line in job.result_content.splitlines():
                print(f"  {line}")
            print()
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
            jobs = list_jobs()
            if not jobs:
                print_info("No scheduled jobs. Use '/job add' to create one.")
                return

            print()
            print("  ═══ SCHEDULED JOBS ═══")
            print()
            for job in jobs:
                status_icon = "\033[32m✓\033[0m" if job.enabled else "\033[33m⏸\033[0m"
                schedule_desc = describe_schedule(job.schedule)
                if job.is_radsim_task:
                    command_display = f'radsim "{job.command[:50]}"'
                else:
                    command_display = job.command[:60]
                print(f"  [{status_icon}] #{job.job_id}  {schedule_desc:<18} {command_display}")
                if job.last_run:
                    last = job.last_run[:19].replace("T", " ")
                    print(f"        last run: {last}")
            print()
            print("  /job add | /job remove <id> | /job pause <id> | /job resume <id> | /job run <id>")
            print()
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

            job = add_job(schedule, command, description, is_radsim_task)
            schedule_desc = describe_schedule(job.schedule)
            print_success(f"Job #{job.job_id} created: {schedule_desc} — {description}")
            return

        if action in ("remove", "rm", "delete", "del"):
            if len(args) < 2:
                print_error("Usage: /job remove <id>")
                return
            try:
                job_id = int(args[1])
            except ValueError:
                print_error("Job ID must be a number.")
                return

            if remove_job(job_id):
                print_success(f"Job #{job_id} removed.")
            else:
                print_error(f"Job #{job_id} not found.")
            return

        if action in ("pause", "disable"):
            if len(args) < 2:
                print_error("Usage: /job pause <id>")
                return
            try:
                job_id = int(args[1])
            except ValueError:
                print_error("Job ID must be a number.")
                return

            if disable_job(job_id):
                print_success(f"Job #{job_id} paused (removed from crontab).")
            else:
                print_error(f"Job #{job_id} not found.")
            return

        if action in ("resume", "enable"):
            if len(args) < 2:
                print_error("Usage: /job resume <id>")
                return
            try:
                job_id = int(args[1])
            except ValueError:
                print_error("Job ID must be a number.")
                return

            if enable_job(job_id):
                print_success(f"Job #{job_id} resumed (added back to crontab).")
            else:
                print_error(f"Job #{job_id} not found.")
            return

        if action == "run":
            if len(args) < 2:
                print_error("Usage: /job run <id>")
                return
            try:
                job_id = int(args[1])
            except ValueError:
                print_error("Job ID must be a number.")
                return

            print_info(f"Running job #{job_id}...")
            success, output = run_job_now(job_id)
            if success:
                print_success(f"Job #{job_id} completed.")
            else:
                print_error(f"Job #{job_id} failed.")
            print()
            for line in output.splitlines()[:20]:
                print(f"  {line}")
            print()
            return

        print_error(f"Unknown subcommand: '{action}'")
        print_info("Usage: /job [list | add | remove <id> | pause <id> | resume <id> | run <id>]")

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
            if len(args) < 2:
                print_error("Usage: /mcp connect <server-name>")
                return
            name = args[1]
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
            if len(args) < 2:
                print_error("Usage: /mcp disconnect <server-name>")
                return
            name = args[1]
            manager.disconnect(name)
            print_success(f"Disconnected from '{name}'")
            return

        if subcommand == "add":
            self._mcp_add_interactive(manager)
            return

        if subcommand == "remove":
            if len(args) < 2:
                print_error("Usage: /mcp remove <server-name>")
                return
            name = args[1]
            if manager.remove_server_config(name):
                print_success(f"Removed server '{name}'")
            else:
                print_error(f"No server named '{name}'")
            return

        print_error(f"Unknown subcommand: '{subcommand}'")
        print_info("Usage: /mcp [status | list | connect <name> | disconnect <name> | add | remove <name>]")

    def _mcp_status(self, manager):
        """Show MCP server connection status."""
        statuses = manager.get_connection_status()
        if not statuses:
            print_info("No MCP servers configured. Use /mcp add to add one.")
            return

        print(f"\n MCP Servers ({len(statuses)}):")
        print("-" * 50)
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
            print(f"  {status['name']} ({status['transport']}{auto}): {state}{tools}")
        print()

    def _mcp_list(self, manager):
        """Show all tools from connected MCP servers."""
        tools = manager.get_connected_tool_list()
        if not tools:
            print_info("No MCP tools available. Connect a server first with /mcp connect <name>.")
            return

        print(f"\n MCP Tools ({len(tools)}):")
        print("-" * 50)
        current_server = None
        for tool in tools:
            if tool["server"] != current_server:
                current_server = tool["server"]
                print(f"\n  {current_server}:")
            description = f" — {tool['description']}" if tool["description"] else ""
            print(f"    {tool['namespaced']}{description}")
        print()

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
