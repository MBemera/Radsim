"""Tool execution policy helpers for the main agent."""

import json
import logging

from .agent_constants import READ_ONLY_TOOLS
from .output import Spinner, print_error, print_info, print_success, print_warning
from .safety import confirm_action
from .tools import execute_tool

logger = logging.getLogger(__name__)


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
        else:
            config_for_confirmation = None if force_confirm else self.config
            confirmed = confirm_action(f"{description}?", config=config_for_confirmation)

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

    def _execute_with_permission(self, tool_name, tool_input):
        """Execute a tool with appropriate permission checks."""
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

        if tool_name == "delegate_task":
            return self._handle_delegate_task(tool_input)
        if tool_name.startswith("browser_"):
            return self._handle_browser_tool(tool_name, tool_input)
        if tool_name == "install_system_tool":
            return self._handle_system_tool(tool_input)
        if tool_name == "write_file":
            return self._handle_write_file(tool_input)
        if tool_name == "replace_in_file":
            return self._handle_replace(tool_input)
        if tool_name == "rename_file":
            return self._handle_rename(tool_input)
        if tool_name == "delete_file":
            return self._handle_delete(tool_input)
        if tool_name == "run_shell_command":
            return self._handle_shell_command(tool_input)
        if tool_name == "web_fetch":
            return self._handle_web_fetch(tool_input)
        if tool_name == "create_directory":
            return self._handle_create_directory(tool_input)
        if tool_name == "git_add":
            return self._handle_git_add(tool_input)
        if tool_name == "git_commit":
            return self._handle_git_commit(tool_input)
        if tool_name == "git_checkout":
            return self._handle_git_checkout(tool_input)
        if tool_name == "git_stash":
            return self._handle_git_stash(tool_input)
        if tool_name == "run_tests":
            return self._handle_run_tests(tool_input)
        if tool_name == "lint_code":
            return self._handle_lint_code(tool_input)
        if tool_name == "format_code":
            return self._handle_format_code(tool_input)
        if tool_name == "type_check":
            return self._handle_type_check(tool_input)
        if tool_name == "add_dependency":
            return self._handle_add_dependency(tool_input)
        if tool_name == "remove_dependency":
            return self._handle_remove_dependency(tool_input)
        if tool_name == "batch_replace":
            return self._handle_batch_replace(tool_input)
        if tool_name == "multi_edit":
            return self._handle_multi_edit(tool_input)
        if tool_name == "apply_patch":
            return self._handle_apply_patch(tool_input)
        if tool_name in ("todo_read", "todo_write"):
            result = execute_tool(tool_name, tool_input)
            self._print_tool_result(tool_name, tool_input, result)
            return result
        if tool_name == "save_context":
            return self._handle_save_context(tool_input)
        if tool_name == "save_memory":
            return self._handle_save_memory(tool_input)
        if tool_name == "schedule_task":
            return self._handle_schedule_task(tool_input)
        if tool_name in READ_ONLY_TOOLS:
            result = execute_tool(tool_name, tool_input)
            self._print_tool_result(tool_name, tool_input, result)
            return result
        if self._mcp_manager and self._mcp_manager.is_mcp_tool(tool_name):
            description = f"MCP tool: {tool_name}"
            if not self.config.auto_confirm:
                params_preview = json.dumps(tool_input, indent=2)[:200]
                if not confirm_action(f"Execute {description}?\n  {params_preview}"):
                    return {
                        "success": False,
                        "error": "STOPPED: User rejected MCP tool. Do NOT retry.",
                    }
            else:
                print_info(f"Auto-executing: {description}")

            from .output import print_tool_call

            print_tool_call(tool_name, tool_input)
            result = self._mcp_manager.call_tool(tool_name, tool_input)
            self._print_tool_result(tool_name, tool_input, result)
            return result

        print_warning(f"Unknown tool: {tool_name}")
        result = execute_tool(tool_name, tool_input)
        self._print_tool_result(tool_name, tool_input, result)
        return result

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
