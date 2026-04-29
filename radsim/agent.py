# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Main agent loop for RadSim."""

import logging
import threading
import time
from pathlib import Path

from .agent_api import AgentApiMixin
from .agent_constants import (  # noqa: F401 - re-exported for compatibility
    CONFIRMATION_TOOLS,
    LIGHT_CONFIRM_TOOLS,
    READ_ONLY_TOOLS,
)
from .agent_conversation import AgentConversationMixin
from .agent_policy import AgentPolicyMixin
from .agent_subagents import AgentSubAgentMixin
from .agent_subtasks import SubAgentMixin
from .api_client import create_client
from .output import (
    Spinner,
    print_error,
    print_info,
    print_shell_output,
    print_success,
    print_tool_call,
    print_tool_result_verbose,
    print_warning,
)
from .prompts import get_system_prompt
from .rate_limiter import (
    ProtectionManager,
)
from .safety import confirm_action, confirm_write, is_path_safe
from .tools import DESTRUCTIVE_COMMANDS, execute_tool

logger = logging.getLogger(__name__)


class RadSimAgent(
    AgentConversationMixin,
    AgentApiMixin,
    AgentPolicyMixin,
    AgentSubAgentMixin,
):
    """The RadSim coding agent."""

    # =========================================================================
    # GENERIC TOOL EXECUTION HELPERS
    # =========================================================================

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
        """Execute a tool with optional confirmation and spinner.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Input dict for the tool
            description: Human-readable description for confirmation prompt
            force_confirm: If True, always prompt (ignore auto_confirm)
            use_spinner: If True, show spinner during execution
            success_message: Custom success message (optional)
            error_message: Custom error message (optional)

        Returns:
            dict with tool result
        """
        return AgentPolicyMixin._run_tool_with_confirmation(
            self,
            tool_name,
            tool_input,
            description,
            force_confirm=force_confirm,
            use_spinner=use_spinner,
            success_message=success_message,
            error_message=error_message,
        )

    def __init__(self, config, context_file=None):
        self.config = config
        self.client = create_client(
            config.provider,
            config.api_key,
            config.model,
            reasoning_effort=getattr(config, "reasoning_effort", None),
        )
        self.messages = []
        self.system_prompt = get_system_prompt()
        self.usage_stats = {"input_tokens": 0, "output_tokens": 0}

        # Learning system attributes
        self._last_response = ""  # For feedback commands (/good, /improve)
        self._current_task_start = None  # For task timing
        self._current_task_tools = []  # Tools used in current task

        # Track rejected writes so the AI can't retry after user says "n"
        self._rejected_writes = set()  # File paths rejected this turn

        # Interrupt flags for soft cancel (Ctrl+C)
        self._interrupted = threading.Event()
        self._is_processing = threading.Event()

        # Lock for serializing message processing (used by Telegram processor)
        self._processing_lock = threading.Lock()

        # Flag: True when processing a Telegram-originated message
        self._telegram_mode = False

        # Teach mode: track if we've already asked the model to retry with annotations
        self._teach_retry_attempted = False

        # Session-level model for capable/review sub-agent tasks
        self._session_capable_model = None

        # Background job manager — completion notifications and result tracking
        self._injected_job_ids = set()
        from .background import get_job_manager
        get_job_manager().set_completion_callback(self._on_background_job_complete)

        # Initialize protection manager with config settings
        from .rate_limiter import BudgetGuard, CircuitBreaker, RateLimiter

        self.protection = ProtectionManager(
            rate_limiter=RateLimiter(
                max_calls_per_turn=config.max_api_calls_per_turn,
                cooldown_ms=config.rate_limit_cooldown_ms,
            ),
            circuit_breaker=CircuitBreaker(
                threshold=config.circuit_breaker_threshold,
            ),
            budget_guard=BudgetGuard(
                max_input_tokens=config.max_session_input_tokens,
                max_output_tokens=config.max_session_output_tokens,
            ),
        )

        # MCP client manager (optional — requires `pip install radsimcli[mcp]`)
        self._mcp_manager = None
        try:
            from .mcp_client import get_mcp_manager, is_mcp_sdk_installed

            if is_mcp_sdk_installed():
                self._mcp_manager = get_mcp_manager()
                connected = self._mcp_manager.connect_auto_servers()
                if connected:
                    from .output import print_info as _mcp_info

                    _mcp_info(f"MCP: auto-connected to {', '.join(connected)}")
            else:
                logger.debug("MCP SDK not installed — MCP features disabled")
        except Exception as exc:
            logger.warning("MCP auto-connect failed: %s", exc)

        if context_file:
            self.load_initial_context(context_file)

    def start_telegram_processor(self):
        """Start a background thread that auto-processes incoming Telegram messages."""
        from .agent_telegram import start_telegram_processor

        start_telegram_processor(self)

    def load_initial_context(self, file_path):
        """Load initial context from a file."""
        return AgentConversationMixin.load_initial_context(self, file_path)

    def update_config(self, provider, api_key, model):
        """Update agent configuration and client."""
        return AgentConversationMixin.update_config(self, provider, api_key, model)

    def reset(self):
        """Clear conversation history."""
        return AgentConversationMixin.reset(self)

    def estimate_tokens(self, text):
        """Estimate token count for text (rough approximation).

        Uses ~4 chars per token as a rough estimate.
        """
        return AgentConversationMixin.estimate_tokens(self, text)

    def get_context_usage(self):
        """Get current context usage as percentage.

        Returns:
            tuple: (current_tokens, max_tokens, percentage)
        """
        return AgentConversationMixin.get_context_usage(self)

    def prune_session(self, target_percentage=70):
        """Prune old messages to reduce context size.

        Keeps the first message (if it's context) and removes oldest
        messages until we're under target percentage.

        Args:
            target_percentage: Target context usage percentage (default 70%)

        Returns:
            int: Number of messages pruned
        """
        return AgentConversationMixin.prune_session(self, target_percentage=target_percentage)

    def check_and_prune(self, threshold=80):
        """Check context usage and prune if over threshold.

        Called before API calls to prevent context overflow.

        Args:
            threshold: Percentage threshold to trigger pruning
        """
        return AgentConversationMixin.check_and_prune(self, threshold=threshold)

    def process_message(self, user_input):
        """Process a user message and return the response."""
        return AgentConversationMixin.process_message(self, user_input)

    def _process_message_inner(self, user_input):
        """Inner message processing (wrapped by process_message for interrupt tracking)."""
        return AgentConversationMixin._process_message_inner(self, user_input)

    def _get_all_tools(self):
        """Return native tool definitions plus any MCP tools."""
        return AgentApiMixin._get_all_tools(self)

    def _call_api(self):
        """Call the API with current messages."""
        return AgentApiMixin._call_api(self)

    def _handle_response(self, response):
        """Handle the API response, including tool calls."""
        return AgentApiMixin._handle_response(self, response)

    def _process_tool_calls(self, response, tool_uses, text_output):
        """Process tool calls from the response."""
        return AgentApiMixin._process_tool_calls(self, response, tool_uses, text_output)

    def _execute_with_permission(self, tool_name, tool_input):
        """Execute a tool with appropriate permission checks."""
        return AgentPolicyMixin._execute_with_permission(self, tool_name, tool_input)

    def _resolve_subagent_model(self, requested_model):
        """Resolve sub-agent model to an OpenRouter config model.

        Sub-agents ALWAYS run via OpenRouter. The "current" option is
        not supported — sub-agents never use the main agent's model.

        Args:
            requested_model: Model alias or ID requested for the sub-agent

        Returns:
            Tuple of (model, "openrouter", "") — always OpenRouter
        """
        return AgentSubAgentMixin._resolve_subagent_model(self, requested_model)

    def _prompt_subagent_model(self):
        """Prompt user to select a model for sub-agent tasks.

        Shows Haiku (fast/cheap) as default, then the OpenRouter
        config models for bigger tasks. Stores the selection in
        self._session_capable_model for the rest of the session.

        Returns:
            Tuple of (model_id, "openrouter", "")
        """
        return AgentSubAgentMixin._prompt_subagent_model(self)

    def _on_background_job_complete(self, job):
        """Callback when a background job finishes. Prints notification."""
        return AgentSubAgentMixin._on_background_job_complete(self, job)

    def _collect_finished_background_results(self):
        """Collect results from completed background jobs and inject into messages.

        Called at the start of each user turn so the AI model sees
        any results that arrived while the user was idle.

        Returns:
            str or None: Summary of completed job results, or None if no jobs finished.
        """
        return AgentSubAgentMixin._collect_finished_background_results(self)

    def _should_stream_subagent(self):
        """Check if sub-agent streaming output is enabled in agent config."""
        return AgentSubAgentMixin._should_stream_subagent(self)

    def _stream_delegate_task(self, task_desc, model, provider, api_key, system_prompt,
                              tools=None, max_iterations=10):
        """Execute a sub-agent task with live streaming output to terminal.

        Shows the sub-agent's response as it generates, so the user
        can watch the work in real time.

        Args:
            task_desc: Task description for the sub-agent
            model: Resolved model ID
            provider: Provider name
            api_key: API key for the provider
            system_prompt: System prompt for the sub-agent
            tools: Tool definitions for the sub-agent (None = text-only)
            max_iterations: Safety limit for agentic loop

        Returns:
            SubAgentResult with full execution results
        """
        return AgentSubAgentMixin._stream_delegate_task(
            self,
            task_desc,
            model,
            provider,
            api_key,
            system_prompt,
            tools=tools,
            max_iterations=max_iterations,
        )

    def _handle_delegate_task(self, tool_input):
        """Handle delegation to a sub-agent with model selection and parallel support."""
        return AgentSubAgentMixin._handle_delegate_task(self, tool_input)

    def _handle_browser_tool(self, tool_name, tool_input):
        """Handle browser automation tools."""
        action = tool_name.replace("browser_", "")
        desc = ""

        if tool_name == "browser_open":
            desc = f"Visit {tool_input.get('url')}"
        elif tool_name == "browser_click":
            desc = f"Click {tool_input.get('selector')}"
        elif tool_name == "browser_type":
            desc = f"Type into {tool_input.get('selector')}"
        elif tool_name == "browser_screenshot":
            desc = "Take screenshot"

        if self.config.auto_confirm:
            print_info(f"Browser: {desc}")
            confirmed = True
        else:
            confirmed = confirm_action(f"Browser {action}: {desc}?", config=self.config)

        if confirmed:
            spinner = Spinner("Browsing...")
            spinner.start()
            try:
                result = execute_tool(tool_name, tool_input)
            finally:
                spinner.stop()

            if result["success"]:
                print_success("Browser action completed")
            else:
                print_error(result.get("error", "Browser action failed"))
            return result
        else:
            print_warning("Browser action cancelled")
            return {"success": False, "error": "STOPPED: User cancelled. Do NOT retry."}

    def _handle_system_tool(self, tool_input):
        """Handle system tool installation."""
        tool_name = tool_input.get("tool_name", "")

        confirmed = confirm_action(f"Install system tool '{tool_name}'?", config=self.config)

        if confirmed:
            print_info(f"Installing {tool_name}...")
            spinner = Spinner("Installing...")
            spinner.start()
            try:
                result = execute_tool("install_system_tool", tool_input)
            finally:
                spinner.stop()

            if result["success"]:
                print_success(f"Installed: {tool_name}")
                if result.get("stdout"):
                    print(result["stdout"][:500])
            else:
                print_error(result.get("error", "Installation failed"))
            return result
        else:
            print_warning("Installation cancelled")
            return {"success": False, "error": "STOPPED: User rejected installation. Do NOT retry."}

    def _handle_write_file(self, tool_input):
        """Handle write_file tool with confirmation."""

        from .modes import is_mode_active
        from .output import strip_teach_comments
        from .response_validator import validate_content_for_write

        file_path = tool_input.get("file_path", "")
        content = tool_input.get("content", "")

        # Block retries for files the user already rejected this turn
        if file_path in self._rejected_writes:
            print_warning(f"Write to {file_path} was already rejected. Skipping retry.")
            return {
                "success": False,
                "error": (
                    f"BLOCKED: User already rejected writing to '{file_path}' this turn. "
                    "Do NOT attempt to write this file again. Move on to something else "
                    "or ask the user what they want instead."
                ),
            }

        # If teach mode is active, preserve original content for display
        # but strip teaching comments from the version written to disk
        display_content = content
        if is_mode_active("teach"):
            stripped = strip_teach_comments(content)
            if stripped == content:
                # Model didn't generate any annotations
                # If we haven't retried yet, ask model to regenerate with annotations
                if not getattr(self, "_teach_retry_attempted", False):
                    self._teach_retry_attempted = True
                    print_warning(
                        "Teach mode is ON but no [teach] annotations found. "
                        "Requesting the model to regenerate with annotations..."
                    )
                    return {
                        "success": False,
                        "error": (
                            "REJECTED: Teach mode is active but your code contains ZERO "
                            "[teach] annotations. This is NOT acceptable. You MUST re-generate "
                            "the SAME code with inline `# [teach] ` teaching annotations above "
                            "every function, class, import, and significant construct. "
                            "Each annotation block must be 3-6 lines. "
                            "Re-call write_file with the annotated version NOW."
                        ),
                    }
                else:
                    # Already retried once — warn but proceed to avoid infinite loop
                    self._teach_retry_attempted = False
                    print_warning(
                        "Teach mode is ON but this model still didn't generate [teach] annotations. "
                        "Some models don't follow teach-mode formatting. "
                        "Try a different model (Claude, GPT-4) for richer annotations."
                    )
            else:
                # Annotations found — reset retry flag and strip for disk
                self._teach_retry_attempted = False
                content = stripped
            tool_input = {**tool_input, "content": content}

        safe, reason = is_path_safe(file_path)
        if not safe:
            print_error(reason)
            return {"success": False, "error": reason}

        # Self-modification safety check
        from .safety import is_core_prompt_intact, is_self_modification

        is_selfmod, _ = is_self_modification(file_path)
        if is_selfmod:
            print_warning("You are editing RadSim's own source code.")
            # Block writes that would destroy the core system prompt
            if Path(file_path).name == "prompts.py":
                intact, block_reason = is_core_prompt_intact(content)
                if not intact:
                    print_error(block_reason)
                    return {"success": False, "error": block_reason}

        # Validate content sanity before writing
        file_ext = Path(file_path).suffix
        valid, validation_error = validate_content_for_write(content, file_ext)
        if not valid:
            print_error(f"Content validation failed: {validation_error}")
            print_warning("The content appears corrupted. Refusing to write garbage to disk.")
            content_preview = content[:200] if len(content) > 200 else content
            print_warning(f"Content preview: {content_preview}...")
            return {
                "success": False,
                "error": f"Content validation failed: {validation_error}. This looks like corrupted data.",
            }

        # Large file heuristic: suggest replace_in_file for surgical edits
        target_path = Path(file_path)
        if target_path.exists():
            try:
                existing_lines = len(target_path.read_text().splitlines())
                if existing_lines > 100 and len(content.splitlines()) > 100:
                    print_warning(
                        f"Overwriting large file ({existing_lines} lines). "
                        f"Consider using replace_in_file for surgical edits."
                    )
            except Exception:
                logger.debug("File size check failed, proceeding with write")

        # Pass annotated content to confirm_write so teach annotations
        # are visible in the first preview (before the user confirms)
        preview_content = display_content if is_mode_active("teach") else content
        confirmed = confirm_write(
            file_path,
            preview_content,
            config=self.config,
        )

        if confirmed:
            result = execute_tool("write_file", tool_input)
            if result["success"]:
                print_success(f"Created: {file_path}")

                # Show code content if Teach Mode is active or verbose mode
                from .output import print_code_content, set_last_written_file

                # Store content for /show; preserve display version when teaching
                if is_mode_active("teach"):
                    set_last_written_file(file_path, content, display_content=display_content)
                else:
                    set_last_written_file(file_path, content)

                # Teach annotations are already shown in the confirm_write preview,
                # so skip duplicate display here. Only show for verbose (non-teach).
                if self.config.verbose and not is_mode_active("teach"):
                    print_code_content(content, file_path, max_lines=50, collapsed=False)

                # Self-verification: remind model to run tests after writes
                verification_hint = (
                    "[Verification reminder: Code was written. "
                    "Run run_tests and lint_code to verify correctness.]"
                )
                result["verification_hint"] = verification_hint

                # Code quality check against RadSim rules
                try:
                    from .code_quality import check_code_quality, format_quality_warnings

                    quality_result = check_code_quality(content, Path(file_path).suffix)
                    if not quality_result["passed"]:
                        warning_text = format_quality_warnings(quality_result["violations"])
                        print_warning(warning_text)
                        result["quality_warnings"] = quality_result["violations"]
                except Exception:
                    logger.debug("Code quality check failed, proceeding with write")
            else:
                print_error(result.get("error", "Failed to write file"))
            return result
        else:
            # Track rejection so AI can't retry this file in the same turn
            self._rejected_writes.add(file_path)
            print_warning("Write cancelled by user")
            return {
                "success": False,
                "error": (
                    f"STOPPED: User rejected writing '{file_path}'. "
                    "Do NOT retry this file. Do NOT attempt to write it again. "
                    "Ask the user what they want instead or move on."
                ),
            }

    def _handle_replace(self, tool_input):
        """Handle replace_in_file tool with confirmation."""
        from .modes import is_mode_active
        from .output import strip_teach_comments

        file_path = tool_input.get("file_path", "")
        old_string = tool_input.get("old_string", "")
        new_string = tool_input.get("new_string", "")

        # Block retries for files the user already rejected this turn
        if file_path in self._rejected_writes:
            print_warning(f"Changes to {file_path} were already rejected. Skipping retry.")
            return {
                "success": False,
                "error": (
                    f"BLOCKED: User already rejected changes to '{file_path}' this turn. "
                    "Do NOT attempt to modify this file again."
                ),
            }

        safe, reason = is_path_safe(file_path)
        if not safe:
            print_error(reason)
            return {"success": False, "error": reason}

        # Self-modification safety check for replace_in_file
        from pathlib import Path as _Path

        from .safety import is_core_prompt_intact, is_self_modification

        is_selfmod, _ = is_self_modification(file_path)
        if is_selfmod:
            print_warning("You are editing RadSim's own source code.")
            # For prompts.py, simulate the final content and verify core prompt
            if _Path(file_path).name == "prompts.py":
                try:
                    current = _Path(file_path).read_text()
                    simulated = current.replace(old_string, new_string, 1)
                    intact, block_reason = is_core_prompt_intact(simulated)
                    if not intact:
                        print_error(block_reason)
                        return {"success": False, "error": block_reason}
                except Exception:
                    pass

        # Strip teaching comments from new_string when teach mode is active
        if is_mode_active("teach"):
            new_string = strip_teach_comments(new_string)
            tool_input = {**tool_input, "new_string": new_string}

        # Self-modification always requires explicit confirmation
        if is_selfmod:
            print(f"\nSELF-MODIFICATION: {file_path}")
            old_preview = old_string[:100] + "..." if len(old_string) > 100 else old_string
            new_preview = new_string[:100] + "..." if len(new_string) > 100 else new_string
            print(f"OLD: {old_preview}")
            print(f"NEW: {new_preview}")
            confirmed = confirm_action("Apply this self-modification?", config=None)
        elif self.config.auto_confirm:
            print_info(f"Auto-replacing in: {file_path}")
            confirmed = True
        else:
            print(f"\nREPLACE IN: {file_path}")
            old_preview = old_string[:100] + "..." if len(old_string) > 100 else old_string
            new_preview = new_string[:100] + "..." if len(new_string) > 100 else new_string
            print(f"OLD: {old_preview}")
            print(f"NEW: {new_preview}")
            confirmed = self._confirm_action_with_trust(
                "replace_in_file",
                tool_input,
                "Apply this change?",
            )

        if confirmed:
            result = execute_tool("replace_in_file", tool_input)
            if result["success"]:
                print_success(f"Modified: {file_path}")
                # Self-verification reminder
                result["verification_hint"] = (
                    "[Verification reminder: Code was modified. "
                    "Run run_tests and lint_code to verify correctness.]"
                )
            else:
                print_error(result.get("error", "Failed to modify file"))
            return result
        else:
            self._rejected_writes.add(file_path)
            print_warning("Replace cancelled by user")
            return {
                "success": False,
                "error": (
                    f"STOPPED: User rejected changes to '{file_path}'. "
                    "Do NOT retry. Ask user what to do instead."
                ),
            }

    def _handle_rename(self, tool_input):
        """Handle rename_file tool with confirmation."""
        old_path = tool_input.get("old_path", "")
        new_path = tool_input.get("new_path", "")

        return self._run_tool_with_confirmation(
            tool_name="rename_file",
            tool_input=tool_input,
            description=f"Rename '{old_path}' to '{new_path}'",
            success_message=f"Renamed: {old_path} -> {new_path}",
        )

    def _handle_delete(self, tool_input):
        """Handle delete_file tool with confirmation (always requires confirmation)."""
        file_path = tool_input.get("file_path", "")

        print_warning(f"DELETE: {file_path}")
        print_warning("This action cannot be undone!")

        # Delete always requires explicit confirmation, ignoring auto_confirm in config
        # But we still pass config so user *could* set auto_confirm=True here (though it won't affect *this* specific check if we ignore it)
        # Actually, for delete, we usually want to force prompt even if auto_confirm is True.
        # So we do NOT pass config to confirm_action here, to force the prompt.
        confirmed = confirm_action(f"Delete '{file_path}'? (type 'yes' to confirm)")

        if confirmed:
            result = execute_tool("delete_file", tool_input)
            if result["success"]:
                print_success(f"Deleted: {file_path}")
            else:
                print_error(result.get("error", "Failed to delete"))
            return result
        else:
            print_warning("Delete cancelled by user")
            return {
                "success": False,
                "error": "STOPPED: User rejected delete. Do NOT retry. Ask user what to do instead.",
            }

    def _handle_shell_command(self, tool_input):
        """Handle shell command with confirmation."""
        command = tool_input.get("command", "")

        # Check for destructive commands
        is_destructive = False
        parts = command.split()
        if parts:
            cmd = parts[0]
            full_cmd = " ".join(parts[:2]) if len(parts) > 1 else cmd
            if cmd in DESTRUCTIVE_COMMANDS or full_cmd in DESTRUCTIVE_COMMANDS:
                is_destructive = True
                print_warning(f"DESTRUCTIVE COMMAND: {command}")
                print_warning("Explicit permission required.")

        if self.config.auto_confirm and not is_destructive:
            print_info(f"Auto-executing: {command}")
            confirmed = True
        else:
            # If destructive, we force prompt by NOT passing config (or passing None) if auto_confirm is enabled?
            # No, if destructive, auto_confirm is bypassed in the 'if' above.
            # So if we are here, either auto_confirm is False OR it is destructive.
            # If destructive, we want to FORCE prompt. So pass None for config.
            # If NOT destructive (and auto_confirm=False), we pass config so user can enable it.

            cfg_to_pass = self.config if not is_destructive else None
            confirmed = confirm_action(f"Execute: '{command}'?", config=cfg_to_pass)

        if confirmed:
            tool_start_time = time.time()
            tool_handle = print_tool_call("run_shell_command", {"command": command}, style="full")

            spinner = Spinner("Executing...")
            spinner.start()
            try:
                result = execute_tool("run_shell_command", tool_input)
            finally:
                spinner.stop()

            duration_ms = (time.time() - tool_start_time) * 1000
            print_tool_result_verbose(tool_handle, "run_shell_command", result, duration_ms)

            if result.get("stdout") or result.get("stderr"):
                print_shell_output(result.get("stdout", ""), result.get("stderr", ""))

            return result
        else:
            print_warning("Command cancelled by user")
            return {
                "success": False,
                "error": "STOPPED: User rejected command execution. Do NOT retry. Ask user what to do instead.",
            }

    def _handle_web_fetch(self, tool_input):
        """Handle web fetch with confirmation."""
        url = tool_input.get("url", "")

        if self.config.auto_confirm:
            print_info(f"Fetching: {url}")
            confirmed = True
        else:
            confirmed = confirm_action(f"Fetch URL: '{url}'?", config=self.config)

        if confirmed:
            print_info(f"Fetching: {url} ...")
            spinner = Spinner("Downloading...")
            spinner.start()
            try:
                result = execute_tool("web_fetch", tool_input)
            finally:
                spinner.stop()

            if result["success"]:
                print_success(f"Fetched: {url}")
            else:
                print_error(result.get("error", "Failed to fetch"))
            return result
        else:
            print_warning("Fetch cancelled by user")
            return {
                "success": False,
                "error": "STOPPED: User rejected fetch. Do NOT retry. Ask user what to do instead.",
            }

    def _handle_create_directory(self, tool_input):
        """Handle create directory with light confirmation."""
        directory_path = tool_input.get("directory_path", "")

        if self.config.auto_confirm:
            print_info(f"Creating directory: {directory_path}")
            confirmed = True
        else:
            confirmed = self._confirm_action_with_trust(
                "create_directory",
                tool_input,
                f"Create directory: '{directory_path}'?",
            )

        if confirmed:
            result = execute_tool("create_directory", tool_input)
            if result["success"]:
                print_success(f"Created directory: {directory_path}")
            else:
                print_error(result.get("error", "Failed to create directory"))
            return result
        else:
            print_warning("Create directory cancelled")
            return {
                "success": False,
                "error": "STOPPED: User rejected directory creation. Do NOT retry. Ask user what to do instead.",
            }

    # =========================================================================
    # GIT WRITE OPERATION HANDLERS
    # =========================================================================

    def _handle_git_add(self, tool_input):
        """Handle git add with light confirmation."""
        file_paths = tool_input.get("file_paths", [])
        all_files = tool_input.get("all_files", False)

        desc = "all files" if all_files else ", ".join(file_paths[:3])
        if len(file_paths) > 3:
            desc += f" (+{len(file_paths) - 3} more)"

        if self.config.auto_confirm:
            print_info(f"Staging: {desc}")
            confirmed = True
        else:
            confirmed = self._confirm_action_with_trust("git_add", tool_input, f"Stage {desc}?")

        if confirmed:
            result = execute_tool("git_add", tool_input)
            if result["success"]:
                staged = result.get("staged_files", [])
                print_success(f"Staged {len(staged)} file(s)")
            else:
                print_error(result.get("error", "Failed to stage files"))
            return result
        else:
            print_warning("Git add cancelled")
            return {"success": False, "error": "STOPPED: User rejected git add. Do NOT retry."}

    def _handle_git_commit(self, tool_input):
        """Handle git commit with confirmation."""
        message = tool_input.get("message", "")
        amend = tool_input.get("amend", False)

        preview = message[:50] + "..." if len(message) > 50 else message
        action = "Amend commit" if amend else "Commit"

        if self.config.auto_confirm:
            print_info(f"{action}: {preview}")
            confirmed = True
        else:
            confirmed = confirm_action(f"{action} with message: '{preview}'?", config=self.config)

        if confirmed:
            result = execute_tool("git_commit", tool_input)
            if result["success"]:
                print_success(f"Committed: {result.get('commit_hash', '')}")
            else:
                print_error(result.get("error", "Failed to commit"))
            return result
        else:
            print_warning("Git commit cancelled")
            return {"success": False, "error": "STOPPED: User rejected git commit. Do NOT retry."}

    def _handle_git_checkout(self, tool_input):
        """Handle git checkout with confirmation."""
        branch = tool_input.get("branch")
        create = tool_input.get("create", False)
        file_path = tool_input.get("file_path")

        if file_path:
            action = f"Restore file: {file_path}"
        elif create:
            action = f"Create and switch to branch: {branch}"
        else:
            action = f"Switch to branch: {branch}"

        if self.config.auto_confirm:
            print_info(action)
            confirmed = True
        else:
            confirmed = confirm_action(f"{action}?", config=self.config)

        if confirmed:
            result = execute_tool("git_checkout", tool_input)
            if result["success"]:
                if file_path:
                    print_success(f"Restored: {file_path}")
                else:
                    print_success(f"Now on branch: {branch}")
            else:
                print_error(result.get("error", "Checkout failed"))
            return result
        else:
            print_warning("Git checkout cancelled")
            return {"success": False, "error": "STOPPED: User rejected git checkout. Do NOT retry."}

    def _handle_git_stash(self, tool_input):
        """Handle git stash with confirmation."""
        action = tool_input.get("action", "push")

        return self._run_tool_with_confirmation(
            tool_name="git_stash",
            tool_input=tool_input,
            description=f"Git stash {action}",
            success_message=f"Stash {action} complete",
        )

    # =========================================================================
    # TESTING & VALIDATION HANDLERS
    # =========================================================================

    def _handle_run_tests(self, tool_input):
        """Handle run_tests with light confirmation."""
        test_command = tool_input.get("test_command")
        test_path = tool_input.get("test_path")

        desc = test_command or "auto-detected tests"
        if test_path:
            desc += f" ({test_path})"

        if self.config.auto_confirm:
            print_info(f"Running tests: {desc}")
            confirmed = True
        else:
            confirmed = self._confirm_action_with_trust(
                "run_tests",
                tool_input,
                f"Run tests: {desc}?",
            )

        if confirmed:
            print_info("Running tests...")
            spinner = Spinner("Testing...")
            spinner.start()
            try:
                result = execute_tool("run_tests", tool_input)
            finally:
                spinner.stop()

            if result["success"]:
                print_success(f"Tests passed ({result.get('framework', 'unknown')})")
            else:
                print_error(f"Tests failed (exit {result.get('returncode', '?')})")
            if result.get("stdout"):
                output = result["stdout"].strip()
                if len(output) > 1000:
                    print(output[:1000] + "\n... [truncated]")
                else:
                    print(output)
            return result
        else:
            print_warning("Tests cancelled")
            return {"success": False, "error": "STOPPED: User rejected tests. Do NOT retry."}

    def _handle_lint_code(self, tool_input):
        """Handle lint_code with light confirmation."""
        file_path = tool_input.get("file_path")
        fix = tool_input.get("fix", False)

        desc = file_path or "project"
        action = "Fix lint issues" if fix else "Lint"

        if self.config.auto_confirm:
            print_info(f"{action}: {desc}")
            confirmed = True
        else:
            confirmed = self._confirm_action_with_trust(
                "lint_code",
                tool_input,
                f"{action} {desc}?",
            )

        if confirmed:
            print_info("Running linter...")
            result = execute_tool("lint_code", tool_input)
            if result["success"]:
                print_success(f"Lint passed ({result.get('linter', 'unknown')})")
            else:
                print_warning("Lint issues found")
            if result.get("stdout"):
                print(result["stdout"][:500])
            return result
        else:
            print_warning("Lint cancelled")
            return {"success": False, "error": "STOPPED: User rejected lint. Do NOT retry."}

    def _handle_format_code(self, tool_input):
        """Handle format_code with confirmation."""
        file_path = tool_input.get("file_path")
        check_only = tool_input.get("check_only", False)

        desc = file_path or "project"
        action = "Check formatting" if check_only else "Format code"

        if self.config.auto_confirm:
            print_info(f"{action}: {desc}")
            confirmed = True
        else:
            confirmed = self._confirm_action_with_trust(
                "format_code",
                tool_input,
                f"{action} in {desc}?",
            )

        if confirmed:
            print_info("Running formatter...")
            result = execute_tool("format_code", tool_input)
            if result["success"]:
                print_success(f"Formatting {'check passed' if check_only else 'applied'}")
            else:
                print_warning("Formatting issues found")
            return result
        else:
            print_warning("Format cancelled")
            return {"success": False, "error": "STOPPED: User rejected formatting. Do NOT retry."}

    def _handle_type_check(self, tool_input):
        """Handle type_check with light confirmation."""
        file_path = tool_input.get("file_path")
        desc = file_path or "project"

        return self._run_tool_with_confirmation(
            tool_name="type_check",
            tool_input=tool_input,
            description=f"Type check {desc}",
            success_message="Type check passed",
        )

    # =========================================================================
    # DEPENDENCY MANAGEMENT HANDLERS
    # =========================================================================

    def _handle_add_dependency(self, tool_input):
        """Handle add_dependency with confirmation."""
        package = tool_input.get("package", "")
        dev = tool_input.get("dev", False)
        dep_type = "dev dependency" if dev else "dependency"

        return self._run_tool_with_confirmation(
            tool_name="add_dependency",
            tool_input=tool_input,
            description=f"Install {package} as {dep_type}",
            use_spinner=True,
            success_message=f"Installed: {package}",
        )

    def _handle_remove_dependency(self, tool_input):
        """Handle remove_dependency with confirmation."""
        package = tool_input.get("package", "")

        return self._run_tool_with_confirmation(
            tool_name="remove_dependency",
            tool_input=tool_input,
            description=f"Remove package {package}",
            success_message=f"Removed: {package}",
        )

    # =========================================================================
    # BATCH OPERATION HANDLERS
    # =========================================================================

    def _handle_batch_replace(self, tool_input):
        """Handle batch_replace with confirmation."""
        pattern = tool_input.get("pattern", "")
        replacement = tool_input.get("replacement", "")
        file_pattern = tool_input.get("file_pattern", "*")

        print_warning(f"BATCH REPLACE across {file_pattern} files")
        print(f"  Pattern: {pattern[:50]}...")
        print(f"  Replace: {replacement[:50]}...")

        confirmed = confirm_action("Apply batch replacement?", config=self.config)

        if confirmed:
            result = execute_tool("batch_replace", tool_input)
            if result["success"]:
                count = result.get("file_count", 0)
                total = result.get("total_replacements", 0)
                print_success(f"Modified {count} files ({total} replacements)")
            else:
                print_error(result.get("error", "Batch replace failed"))
            return result
        else:
            print_warning("Batch replace cancelled")
            return {
                "success": False,
                "error": "STOPPED: User rejected batch replace. Do NOT retry.",
            }

    def _handle_multi_edit(self, tool_input):
        """Handle multi_edit with confirmation."""
        file_path = tool_input.get("file_path", "")
        edits = tool_input.get("edits", [])

        return self._run_tool_with_confirmation(
            tool_name="multi_edit",
            tool_input=tool_input,
            description=f"Apply {len(edits)} edits to '{file_path}'",
            success_message=f"Applied {len(edits)} edits to {file_path}",
        )

    def _handle_apply_patch(self, tool_input):
        """Handle apply_patch with confirmation."""
        patch_text = tool_input.get("patch", "")
        line_count = len(patch_text.strip().split("\n")) if patch_text else 0

        return self._run_tool_with_confirmation(
            tool_name="apply_patch",
            tool_input=tool_input,
            description=f"Apply multi-file patch ({line_count} lines)",
            success_message="Patch applied successfully",
        )

    def _handle_save_context(self, tool_input):
        """Handle save_context with light confirmation."""
        filename = tool_input.get("filename", "radsim_context.json")

        return self._run_tool_with_confirmation(
            tool_name="save_context",
            tool_input=tool_input,
            description=f"Save context to {filename}",
            success_message=f"Context saved: {filename}",
        )

    def _handle_save_memory(self, tool_input):
        """Handle save_memory with confirmation."""
        key = tool_input.get("key", "")
        value = tool_input.get("value", "")
        memory_type = tool_input.get("memory_type", "preference")

        if self.config.auto_confirm:
            print_info(f"Saving to {memory_type} memory: {key}")
            confirmed = True
        else:
            preview = str(value)[:50] + "..." if len(str(value)) > 50 else str(value)
            confirmed = self._confirm_action_with_trust(
                "save_memory",
                tool_input,
                f"Save to {memory_type} memory?\n  Key: {key}\n  Value: {preview}",
            )

        if confirmed:
            result = execute_tool("save_memory", tool_input)
            if result.get("success"):
                print_success(f"Memory saved: {key} ({memory_type})")
            else:
                print_error(result.get("error", "Save failed"))
            return result
        else:
            print_warning("Memory save cancelled")
            return {"success": False, "error": "STOPPED: User rejected memory save. Do NOT retry."}

    def _handle_forget_memory(self, tool_input):
        """Handle forget_memory with confirmation."""
        key = tool_input.get("key", "")
        memory_type = tool_input.get("memory_type", "preference")

        return self._run_tool_with_confirmation(
            tool_name="forget_memory",
            tool_input=tool_input,
            description=f"Forget {memory_type} memory: {key}",
            success_message=f"Memory forgotten: {key} ({memory_type})",
        )

    def _handle_add_tool(self, tool_input):
        """Handle add_tool with confirmation. Trust-bandit can auto-confirm."""
        name = tool_input.get("name", "")
        description = tool_input.get("description", "")
        body_preview = str(tool_input.get("body", ""))[:200]
        message = (
            f"Register new tool {name!r}?\n"
            f"  Description: {description}\n"
            f"  Body preview: {body_preview}"
        )
        return self._run_tool_with_confirmation(
            tool_name="add_tool",
            tool_input=tool_input,
            description=message,
            success_message=f"Tool added: {name}",
        )

    def _handle_remove_tool(self, tool_input):
        """Handle remove_tool with confirmation."""
        name = tool_input.get("name", "")
        return self._run_tool_with_confirmation(
            tool_name="remove_tool",
            tool_input=tool_input,
            description=f"Remove custom tool {name!r}",
            success_message=f"Tool removed: {name}",
        )

    def _handle_schedule_task(self, tool_input):
        """Handle schedule_task with confirmation."""
        name = tool_input.get("name", "")
        schedule = tool_input.get("schedule", "")
        command = tool_input.get("command", "")

        if self.config.auto_confirm:
            print_info(f"Scheduling task: {name}")
            confirmed = True
        else:
            confirmed = confirm_action(
                f"Schedule task?\n  Name: {name}\n  Schedule: {schedule}\n  Command: {command[:50]}...",
                config=self.config,
            )

        if confirmed:
            result = execute_tool("schedule_task", tool_input)
            if result.get("success"):
                print_success(f"Task scheduled: {name}")
            else:
                print_error(result.get("error", "Scheduling failed"))
            return result
        else:
            print_warning("Task scheduling cancelled")
            return {
                "success": False,
                "error": "STOPPED: User rejected task scheduling. Do NOT retry.",
            }

    def _print_tool_result(self, tool_name, tool_input, result):
        """Print the result of a tool execution."""
        return AgentPolicyMixin._print_tool_result(self, tool_name, tool_input, result)

def run_single_shot(config, prompt, context_file=None):
    """Run a single-shot command and return the result."""
    from .agent_runtime import run_single_shot as run_single_shot_runtime

    return run_single_shot_runtime(config, prompt, context_file)


def run_interactive(config, context_file=None):
    """Run the interactive conversation loop."""
    from .agent_runtime import run_interactive as run_interactive_runtime

    return run_interactive_runtime(config, context_file)


def print_tools_list():
    """Print list of available tools."""
    from .agent_runtime import print_tools_list as print_tools_list_runtime

    return print_tools_list_runtime()


class SubAgent(SubAgentMixin, RadSimAgent):
    """A sub-agent that performs a delegated task."""
