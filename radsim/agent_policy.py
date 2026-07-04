"""Tool execution policy helpers for the main agent."""

import json
import logging
import time

from .agent_constants import CONFIRMATION_TOOLS, LIGHT_CONFIRM_TOOLS, READ_ONLY_TOOLS
from .output import Spinner, print_error, print_info, print_success, print_warning
from .safety import confirm_action
from .tools import execute_tool

logger = logging.getLogger(__name__)

# Tools with a dedicated confirmation handler on the agent.
# Every entry routes through a handler that asks the user (or honors
# auto_confirm) before executing — never add a write-capable tool to
# READ_ONLY_TOOLS instead of here.
TOOL_HANDLERS = {
    "delegate_task": "_handle_delegate_task",
    "install_system_tool": "_handle_system_tool",
    "write_file": "_handle_write_file",
    "replace_in_file": "_handle_replace",
    "rename_file": "_handle_rename",
    "delete_file": "_handle_delete",
    "run_shell_command": "_handle_shell_command",
    "web_fetch": "_handle_web_fetch",
    "create_directory": "_handle_create_directory",
    "git_add": "_handle_git_add",
    "git_commit": "_handle_git_commit",
    "git_checkout": "_handle_git_checkout",
    "git_stash": "_handle_git_stash",
    "run_tests": "_handle_run_tests",
    "lint_code": "_handle_lint_code",
    "format_code": "_handle_format_code",
    "type_check": "_handle_type_check",
    "add_dependency": "_handle_add_dependency",
    "remove_dependency": "_handle_remove_dependency",
    "batch_replace": "_handle_batch_replace",
    "multi_edit": "_handle_multi_edit",
    "apply_patch": "_handle_apply_patch",
    "save_context": "_handle_save_context",
    "save_memory": "_handle_save_memory",
    "forget_memory": "_handle_forget_memory",
    "schedule_task": "_handle_schedule_task",
    "add_tool": "_handle_add_tool",
    "remove_tool": "_handle_remove_tool",
}


class AgentPolicyMixin:
    """Permission checks and generic tool execution policy."""

    def _run_tool_with_confirmation(
        self,
        tool_name,
        tool_input,
        description,
        force_confirm=False,
        use_spinner=False,
        success_message=None,
        error_message=None,
    ):
        """Execute a tool with optional confirmation and spinner."""
        if self.config.auto_confirm and not force_confirm:
            print_info(f"Auto-executing: {description}")
            confirmed = True
        elif force_confirm:
            confirmed = confirm_action(f"{description}?", config=None)
        else:
            confirmed = self._confirm_action_with_trust(
                tool_name,
                tool_input,
                f"{description}?",
            )

        if not confirmed:
            print_warning(f"{description} cancelled")
            return {"success": False, "error": "STOPPED: User rejected action. Do NOT retry."}

        if use_spinner:
            spinner = Spinner("Running...")
            spinner.start()
        try:
            result = execute_tool(tool_name, tool_input)
        finally:
            if use_spinner:
                spinner.stop()

        if result.get("success"):
            print_success(success_message or f"{tool_name} completed")
        else:
            print_error(error_message or result.get("error", f"{tool_name} failed"))

        return result

    def _confirm_action_with_trust(self, tool_name, tool_input, message):
        """Confirm an action, allowing learned trust for safe Tier 1 tools."""
        try:
            from .trust_bandit_integration import confirm_with_bandit

            return confirm_with_bandit(tool_name, tool_input, message, config=self.config)
        except Exception:
            logger.debug("Trust-bandit confirmation failed, using normal prompt", exc_info=True)
            return confirm_action(message, config=self.config)

    def _warn_if_known_error(self, tool_name, tool_input):
        """Surface a warning when the planned action matches a past error."""
        try:
            from .learning.error_analyzer import check_similar_error

            planned_action = f"{tool_name}: {str(tool_input)[:100]}"
            error_check = check_similar_error(planned_action, tool_name)
            if error_check.get("error_found"):
                print_warning(f"Known issue: {error_check['warning']}")
                if error_check.get("solution"):
                    print_info(f"Suggested fix: {error_check['solution']}")
        except Exception:
            logger.debug("Learning error check failed during tool execution")

    def _check_tool_disabled(self, tool_name):
        """Return an error result if the tool is disabled in settings, else None."""
        try:
            from .agent_config import get_agent_config_manager

            config_manager = get_agent_config_manager()
            if not config_manager.is_tool_enabled(tool_name):
                return {
                    "success": False,
                    "error": (
                        f"Tool '{tool_name}' is disabled in agent settings. "
                        "Use /settings to enable it."
                    ),
                }
        except Exception:
            logger.debug("Agent config check failed, allowing tool execution")
        return None

    def _execute_mcp_tool(self, tool_name, tool_input):
        """Confirm and execute an MCP tool with a live tool-event line."""
        if not self.config.auto_confirm:
            params_preview = json.dumps(tool_input, indent=2)[:200]
            if not confirm_action(f"Execute MCP tool: {tool_name}?\n  {params_preview}"):
                return {
                    "success": False,
                    "error": "STOPPED: User rejected MCP tool. Do NOT retry.",
                }

        from .output import print_tool_call, print_tool_result_verbose

        tool_handle = print_tool_call(tool_name, tool_input)
        start_time = time.time()
        result = self._mcp_manager.call_tool(tool_name, tool_input)
        duration_ms = (time.time() - start_time) * 1000
        print_tool_result_verbose(tool_handle, tool_name, result, duration_ms)
        return result

    def _execute_with_permission(self, tool_name, tool_input):
        """Execute a tool with appropriate permission checks."""
        self._warn_if_known_error(tool_name, tool_input)

        disabled_result = self._check_tool_disabled(tool_name)
        if disabled_result:
            return disabled_result

        handler_name = TOOL_HANDLERS.get(tool_name)
        if handler_name:
            return getattr(self, handler_name)(tool_input)

        if tool_name.startswith("browser_"):
            return self._handle_browser_tool(tool_name, tool_input)

        if tool_name in ("todo_read", "todo_write"):
            result = execute_tool(tool_name, tool_input)
            self._print_tool_result(tool_name, tool_input, result)
            return result

        if tool_name in READ_ONLY_TOOLS:
            return execute_tool(tool_name, tool_input)

        if self._mcp_manager and self._mcp_manager.is_mcp_tool(tool_name):
            return self._execute_mcp_tool(tool_name, tool_input)

        # Confirmation-required tools without a dedicated handler above
        # (run_docker, database_query, deploy, refactor_code, npm_install, ...)
        # must never fall through to unconfirmed execution.
        if tool_name in CONFIRMATION_TOOLS or tool_name in LIGHT_CONFIRM_TOOLS:
            return self._run_tool_with_confirmation(
                tool_name,
                tool_input,
                description=f"Run {tool_name}",
                use_spinner=True,
            )

        # Unknown tools - fail closed: always ask before executing
        print_warning(f"Unknown tool requested: {tool_name}")
        return self._run_tool_with_confirmation(
            tool_name,
            tool_input,
            description=f"Run unrecognized tool '{tool_name}'",
            force_confirm=True,
            use_spinner=True,
        )

    def _print_tool_result(self, tool_name, tool_input, result):
        """Print the result of a tool execution."""
        if not result.get("success", False):
            print_error(f"{tool_name}: {result.get('error', 'Failed')}")
            return

        if tool_name == "read_file":
            file_path = tool_input.get("file_path", "")
            print_info(f"Read: {file_path} ({result.get('line_count', 0)} lines)")
        elif tool_name == "read_many_files":
            print_info(f"Read {result.get('count', 0)} files")
        elif tool_name == "list_directory":
            print_info(f"Listed: {tool_input.get('directory_path', '.')} ({result.get('count', 0)} items)")
        elif tool_name == "glob_files":
            print_info(f"Glob '{tool_input.get('pattern', '')}': {result.get('count', 0)} matches")
        elif tool_name == "grep_search":
            print_info(
                f"Grep '{tool_input.get('pattern', '')}': {result.get('count', 0)} matches in {result.get('files_searched', 0)} files"
            )
        elif tool_name == "search_files":
            print_info(f"Search '{tool_input.get('pattern', '')}': {result.get('count', 0)} files")
        elif tool_name == "git_status":
            print_info("Git status retrieved")
        elif tool_name == "git_diff":
            staged = tool_input.get("staged", False)
            print_info(f"Git diff ({'staged' if staged else 'unstaged'})")
        elif tool_name == "git_log":
            print_info(f"Git log ({tool_input.get('count', 10)} commits)")
        elif tool_name == "git_branch":
            print_info("Git branches listed")
        elif tool_name == "find_definition":
            print_info(f"Find definition '{tool_input.get('symbol', '')}': {result.get('count', 0)} found")
        elif tool_name == "find_references":
            print_info(f"Find references '{tool_input.get('symbol', '')}': {result.get('count', 0)} found")
        elif tool_name == "get_project_info":
            print_info(f"Project type: {result.get('project_type', 'unknown')}")
        elif tool_name == "list_dependencies":
            print_info(f"Dependencies listed ({result.get('package_manager', 'unknown')})")
        elif tool_name == "plan_task":
            print_info(f"Task planned: {result.get('task_id', '')} ({len(result.get('subtasks', []))} subtasks)")
        elif tool_name == "load_context":
            print_info(f"Context loaded (saved: {result.get('saved_at', 'unknown')})")
        else:
            print_info(f"{tool_name}: OK")
