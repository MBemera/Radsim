"""Interactive and single-shot runtime helpers for the main agent."""

from .commands import CommandRegistry, detect_help_intent
from .output import print_agent_response, print_error, print_warning
from .prompts import get_system_prompt
from .rate_limiter import BudgetExceeded, CircuitBreakerOpen, RateLimitExceeded
from .runtime_context import get_runtime_context


def _run_user_shell_command(command, agent):
    """Run a user-typed `!command` and share the output with the agent.

    The user typed the command themselves, so it runs without a
    confirmation prompt — but it still passes the command policy, so
    catastrophic commands stay blocked at every security level. Output
    is queued into the next message so the model can see what happened.
    """
    import subprocess

    from .output import print_error, print_info
    from .tools.command_policy import get_command_policy

    allowed, reason = get_command_policy().is_command_allowed(command)
    if not allowed:
        print_error(reason)
        return

    try:
        completed = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        print_error("Command timed out after 120s")
        return
    except OSError as error:
        print_error(str(error))
        return

    output = (completed.stdout or "").strip()
    if completed.stderr and completed.stderr.strip():
        output = f"{output}\n{completed.stderr.strip()}" if output else completed.stderr.strip()

    shown_lines = output.splitlines()[:40]
    for line in shown_lines:
        print(f"  {line}")
    hidden_count = len(output.splitlines()) - len(shown_lines)
    if hidden_count > 0:
        print(f"  ... ({hidden_count} more lines)")
    print_info(f"exit {completed.returncode} — output shared with the agent")

    agent._pending_user_context.append(
        f"[User ran shell command: {command}]\n"
        f"[exit code: {completed.returncode}]\n{output[:4000]}"
    )


def run_single_shot(config, prompt, context_file=None):
    """Run a single-shot command and return the result."""
    from .agent import RadSimAgent
    from .extension_loader import get_extension_loader
    from .user_hooks import fire_session_hooks

    agent = RadSimAgent(config, context_file)
    registry = CommandRegistry()
    agent.command_registry = registry
    get_extension_loader(registry).load_approved()
    fire_session_hooks("session_start", provider=config.provider, model=config.model)
    try:
        return agent.process_message(prompt)
    finally:
        fire_session_hooks("session_end", provider=config.provider, model=config.model)


def run_interactive(config, context_file=None):
    """Run the interactive conversation loop."""
    from .agent import RadSimAgent
    from .cli import set_active_agent
    from .keybindings import check_action_hotkey, check_hotkey
    from .memory import load_memory
    from .modes import get_active_modes, toggle_mode
    from .output import (
        print_header,
        print_help,
        print_info,
        print_prompt,
        print_status_bar,
        print_success,
    )

    agent = RadSimAgent(config, context_file)
    registry = CommandRegistry()
    agent.command_registry = registry
    set_active_agent(agent)

    import atexit

    from .user_hooks import fire_session_hooks

    print_header(config.provider, config.model)

    from .extension_loader import get_extension_loader

    extension_results = get_extension_loader(registry).load_approved()
    for result in extension_results:
        if not result.get("success"):
            print_warning(result.get("error", "Extension could not be loaded"))

    # Fire AFTER the banner so hook output lands where the user is
    # looking, not scrolled above the logo.
    fire_session_hooks("session_start", provider=config.provider, model=config.model)
    # atexit covers every way the loop can end: /exit, Ctrl+C, or a crash.
    atexit.register(fire_session_hooks, "session_end", config.provider, config.model)

    memory_result = load_memory(memory_type="preference")
    user_name = None
    if memory_result["success"] and memory_result.get("data"):
        data = memory_result["data"]
        user_name = data.get("name") or data.get("username") or data.get("user")
        if user_name:
            print_info(f"Welcome back, {user_name}!")

    memory = get_runtime_context().get_memory()

    # agents.md is injected via the system prompt (get_system_prompt),
    # so it is NOT loaded into the message history here — doing both
    # sent the same content twice on every request.

    # Track how many sessions this project has seen (only for projects
    # that already opted into project memory — no directory scattering)
    if memory.project_mem.radsim_dir.exists():
        project_info = memory.project_mem.data.setdefault("project", {})
        project_info["session_count"] = project_info.get("session_count", 0) + 1
        memory.project_mem._save_json(memory.project_mem.json_file, memory.project_mem.data)

    if memory.session_mem.is_expired():
        print_info("Started new session (previous session expired).")
        import datetime

        memory.session_mem.data = {
            "started_at": datetime.datetime.now().isoformat(),
            "last_active": datetime.datetime.now().isoformat(),
            "active_task": "",
            "conversation_summary": "",
        }
        memory.session_mem.update_activity()
    else:
        active_task = memory.session_mem.data.get("active_task")
        if active_task:
            print_info(f"Resumed session. Active Task: {active_task}")
            memory.session_mem.update_activity()

    agent.start_telegram_processor()

    while True:
        try:
            active_modes = get_active_modes()
            user_input = print_prompt(active_modes, registry=registry)
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input.strip():
            continue

        stripped_input = user_input.strip()
        if stripped_input.startswith("!") and len(stripped_input) > 1:
            _run_user_shell_command(stripped_input[1:].strip(), agent)
            continue

        action = check_action_hotkey(user_input.strip())
        if action == "show_code":
            from .output import print_all_session_code

            print_all_session_code()
            continue

        hotkey_mode = check_hotkey(user_input.strip())
        if hotkey_mode:
            is_active, message = toggle_mode(hotkey_mode)
            if is_active:
                print_success(f"{message} - teaching in ALL responses enabled")
            else:
                print_success(message)
            agent.system_prompt = get_system_prompt()
            continue

        if registry.handle_input(user_input, agent):
            agent.system_prompt = get_system_prompt()
            continue

        help_topic = detect_help_intent(user_input)
        if help_topic:
            print_help(topic=help_topic)
            continue

        try:
            if user_name and len(agent.messages) == 0:
                agent.messages.append(
                    {"role": "user", "content": f"[System: The user's name is {user_name}]"}
                )

            with agent._processing_lock:
                response = agent.process_message(user_input)

            try:
                get_runtime_context().get_memory().session_mem.update_activity()
            except Exception:
                pass

            if not config.stream:
                print_agent_response(response)

            print_status_bar(
                config.model,
                agent.usage_stats["input_tokens"],
                agent.usage_stats["output_tokens"],
            )

        except RateLimitExceeded as error:
            print_error(f"\nEMERGENCY STOP LOOP PROTECTION: {error}")
            print_warning("The AI was making too many consecutive calls. Try a simpler request.")
        except CircuitBreakerOpen as error:
            print_error(f"\nEMERGENCY STOP ERROR PROTECTION: {error}")
            print_warning("Too many consecutive errors. Please wait before retrying.")
        except BudgetExceeded as error:
            print_error(f"\nEMERGENCY STOP BUDGET PROTECTION: {error}")
            print_warning("Session token limit reached. Start a new session with 'radsim'.")
        except Exception as error:
            print_error(str(error))


TOOL_CATEGORIES = {
    "File Operations": [
        "read_file",
        "read_many_files",
        "write_file",
        "replace_in_file",
        "rename_file",
        "delete_file",
        "multi_edit",
        "batch_replace",
        "apply_patch",
    ],
    "Directory": ["list_directory", "create_directory"],
    "Search": ["glob_files", "grep_search", "search_files"],
    "Code Intelligence": ["find_definition", "find_references", "repo_map", "analyze_code"],
    "Shell & System": ["run_shell_command", "install_system_tool", "run_docker"],
    "Web & Browser": [
        "web_fetch",
        "browser_open",
        "browser_click",
        "browser_type",
        "browser_screenshot",
    ],
    "Git (Read)": ["git_status", "git_diff", "git_log", "git_branch"],
    "Git (Write)": ["git_add", "git_commit", "git_checkout", "git_stash"],
    "Testing & Validation": [
        "run_tests",
        "lint_code",
        "format_code",
        "type_check",
        "generate_tests",
    ],
    "Dependencies & Setup": [
        "list_dependencies",
        "add_dependency",
        "remove_dependency",
        "npm_install",
        "pip_install",
        "init_project",
        "get_project_info",
    ],
    "Task Planning": [
        "plan_task",
        "save_context",
        "load_context",
        "todo_read",
        "todo_write",
    ],
    "Sub-Agents & Scheduling": [
        "delegate_task",
        "submit_completion",
        "schedule_task",
        "list_schedules",
    ],
    "Skills & Memory": [
        "add_skill",
        "remove_skill",
        "list_skills",
        "save_memory",
        "load_memory",
        "forget_memory",
    ],
    "Custom Tools": ["add_tool", "list_custom_tools", "remove_tool"],
    "Integrations": ["send_telegram", "database_query", "deploy", "refactor_code"],
}


def print_tools_list():
    """Print every available tool, grouped by category.

    Category membership is validated against TOOL_DEFINITIONS so removed
    tools disappear automatically and any new tool still shows up (under
    "Other" until it is placed in a category).
    """
    from .tools import TOOL_DEFINITIONS

    available = {tool["name"] for tool in TOOL_DEFINITIONS}

    print(f"\n Available Tools ({len(available)} total):")
    print("-" * 50)

    categorized = set()
    for category, tools in TOOL_CATEGORIES.items():
        existing = [tool for tool in tools if tool in available]
        categorized.update(existing)
        if existing:
            print(f"\n  {category}:")
            for tool in existing:
                print(f"    - {tool}")

    uncategorized = sorted(available - categorized)
    if uncategorized:
        print("\n  Other:")
        for tool in uncategorized:
            print(f"    - {tool}")

    try:
        from .mcp_client import get_mcp_manager

        manager = get_mcp_manager()
        mcp_tools = manager.get_connected_tool_list()
        if mcp_tools:
            tools_by_server = {}
            for tool in mcp_tools:
                tools_by_server.setdefault(tool["server"], []).append(tool)
            for server, server_tools in tools_by_server.items():
                print(f"\n  MCP: {server}:")
                for tool in server_tools:
                    description = f" — {tool['description']}" if tool["description"] else ""
                    print(f"    - {tool['namespaced']}{description}")
    except ImportError:
        pass

    print()
