"""Interactive and single-shot runtime helpers for the main agent."""

from .commands import CommandRegistry, detect_help_intent
from .output import print_agent_response, print_error, print_warning
from .prompts import get_system_prompt
from .rate_limiter import BudgetExceeded, CircuitBreakerOpen, RateLimitExceeded
from .runtime_context import get_runtime_context


def run_single_shot(config, prompt, context_file=None):
    """Run a single-shot command and return the result."""
    from .agent import RadSimAgent

    agent = RadSimAgent(config, context_file)
    return agent.process_message(prompt)


def run_interactive(config, context_file=None):
    """Run the interactive conversation loop."""
    from .agent import RadSimAgent
    from .cli import set_active_agent
    from .keybindings import check_action_hotkey, check_hotkey
    from .memory import load_memory
    from .modes import get_active_modes, toggle_mode
    from .output import print_header, print_help, print_info, print_prompt, print_status_bar

    agent = RadSimAgent(config, context_file)
    registry = CommandRegistry()
    set_active_agent(agent)

    print_header(config.provider, config.model)

    memory_result = load_memory(memory_type="preference")
    user_name = None
    if memory_result["success"] and memory_result.get("data"):
        data = memory_result["data"]
        user_name = data.get("name") or data.get("username") or data.get("user")
        if user_name:
            print_info(f"Welcome back, {user_name}!")

    memory = get_runtime_context().get_memory()
    agents_md_path = memory.project_mem.agents_file

    if agents_md_path.exists() and not context_file:
        agent.load_initial_context(str(agents_md_path))

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
            user_input = print_prompt(active_modes)
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input.strip():
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
                print_info(f"✓ {message} - teaching in ALL responses enabled")
            else:
                print_info(f"✓ {message}")
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
            print_error(f"\n🛑 LOOP PROTECTION: {error}")
            print_warning("The AI was making too many consecutive calls. Try a simpler request.")
        except CircuitBreakerOpen as error:
            print_error(f"\n🛑 ERROR PROTECTION: {error}")
            print_warning("Too many consecutive errors. Please wait before retrying.")
        except BudgetExceeded as error:
            print_error(f"\n🛑 BUDGET PROTECTION: {error}")
            print_warning("Session token limit reached. Start a new session with 'radsim'.")
        except Exception as error:
            print_error(str(error))


def print_tools_list():
    """Print list of available tools."""
    print("\n Available Tools:")
    print("-" * 50)

    categories = {
        "File Operations": [
            "read_file",
            "read_many_files",
            "write_file",
            "replace_in_file",
            "rename_file",
            "delete_file",
        ],
        "Directory": ["list_directory", "create_directory"],
        "Search": ["glob_files", "grep_search", "search_files"],
        "Shell": ["run_shell_command"],
        "Web": ["web_fetch"],
        "Git (Read)": ["git_status", "git_diff", "git_log", "git_branch"],
        "Git (Write)": ["git_add", "git_commit", "git_checkout", "git_stash"],
        "Testing & Validation": ["run_tests", "lint_code", "format_code", "type_check"],
        "Dependencies": ["list_dependencies", "add_dependency", "remove_dependency"],
        "Project": ["get_project_info", "batch_replace", "multi_edit"],
        "Task Planning": ["plan_task", "save_context", "load_context", "todo_read", "todo_write"],
        "Code Intelligence": ["find_definition", "find_references"],
    }

    for category, tools in categories.items():
        print(f"\n  {category}:")
        for tool in tools:
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
