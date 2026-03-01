# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Main agent loop for RadSim."""

import json
import logging
import threading
import time
from pathlib import Path

from .api_client import create_client
from .commands import CommandRegistry
from .learning import (
    get_reflection_engine,
    get_tool_optimizer,
    record_error,
    track_tool_execution,
)
from .output import (
    Spinner,
    print_agent_response,
    print_error,
    print_info,
    print_shell_output,
    print_stream_chunk,
    print_success,
    print_tool_call,
    print_tool_result_verbose,
    print_warning,
    reset_stream_state,
)
from .prompts import get_system_prompt
from .rate_limiter import (
    BudgetExceeded,
    CircuitBreakerOpen,
    ProtectionManager,
    RateLimitExceeded,
)
from .safety import confirm_action, confirm_write, is_path_safe
from .tools import DESTRUCTIVE_COMMANDS, TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger(__name__)


# Tools that require confirmation before execution
CONFIRMATION_TOOLS = {
    "write_file",
    "replace_in_file",
    "rename_file",
    "delete_file",
    "run_shell_command",
    "web_fetch",
    "git_commit",
    "git_checkout",
    "git_stash",
    "add_dependency",
    "remove_dependency",
    "batch_replace",
    "multi_edit",
    "apply_patch",
    "format_code",
    # Advanced Skills
    "run_docker",
    "database_query",
    "refactor_code",
    "deploy",
    # Memory & Scheduling
    "schedule_task",
    "save_memory",
    # Skills & Notifications
    "add_skill",
    "remove_skill",
    "send_telegram",
}

# Read-only tools that execute without confirmation
READ_ONLY_TOOLS = {
    "read_file",
    "read_many_files",
    "list_directory",
    "glob_files",
    "grep_search",
    "search_files",
    "git_status",
    "git_diff",
    "git_log",
    "git_branch",
    "find_definition",
    "find_references",
    "get_project_info",
    "repo_map",
    "list_dependencies",
    "plan_task",
    "load_context",
    # Advanced Skills (read-only)
    "analyze_code",
    "generate_tests",
    # Memory & Scheduling (read-only)
    "load_memory",
    "list_schedules",
    # Skills (read-only)
    "list_skills",
}

# Tools that need light confirmation (auto-confirm in -y mode)
LIGHT_CONFIRM_TOOLS = {
    "git_add",
    "run_tests",
    "lint_code",
    "type_check",
    "save_context",
}


class RadSimAgent:
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
        # Determine if confirmation is needed
        if self.config.auto_confirm and not force_confirm:
            print_info(f"Auto-executing: {description}")
            confirmed = True
        else:
            config_for_confirmation = None if force_confirm else self.config
            confirmed = confirm_action(f"{description}?", config=config_for_confirmation)

        if not confirmed:
            print_warning(f"{description} cancelled")
            return {"success": False, "error": "STOPPED: User rejected action. Do NOT retry."}

        # Execute with optional spinner
        if use_spinner:
            spinner = Spinner("Running...")
            spinner.start()
        try:
            result = execute_tool(tool_name, tool_input)
        finally:
            if use_spinner:
                spinner.stop()

        # Report result
        if result.get("success"):
            msg = success_message or f"{tool_name} completed"
            print_success(msg)
        else:
            msg = error_message or result.get("error", f"{tool_name} failed")
            print_error(msg)

        return result

    def __init__(self, config, context_file=None):
        self.config = config
        self.client = create_client(
            config.provider,
            config.api_key,
            config.model,
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

        if context_file:
            self.load_initial_context(context_file)

    def start_telegram_processor(self):
        """Start a background thread that auto-processes incoming Telegram messages."""
        try:
            from . import telegram as _tg_check  # noqa: F401 — availability check

            del _tg_check
        except ImportError:
            return

        def _telegram_confirm(prompt_message):
            """Send confirmation prompt to Telegram and wait for y/n reply."""
            from .telegram import check_incoming, send_telegram_message

            send_telegram_message(f"Confirm: {prompt_message}\n\nReply 'y' or 'n'")

            deadline = time.time() + 60
            while time.time() < deadline:
                reply = check_incoming()
                if reply:
                    answer = reply.get("text", "").strip().lower()
                    if answer in ("y", "yes"):
                        return True
                    if answer in ("n", "no"):
                        return False
                    send_telegram_message("Please reply 'y' or 'n'")
                time.sleep(0.5)

            send_telegram_message("Confirmation timed out — action skipped.")
            return False

        def _telegram_loop():
            from .commands import CommandRegistry
            from .output import print_status_bar
            from .safety import set_telegram_confirm
            from .telegram import (
                check_incoming,
                check_incoming_callback,
                is_listening,
            )

            registry = CommandRegistry()

            while True:
                time.sleep(0.5)
                try:
                    if not is_listening():
                        continue

                    # Check for incoming text/commands
                    msg = check_incoming()
                    if msg:
                        _process_telegram_message(msg, registry, self, set_telegram_confirm)

                    # Check for callback queries (button presses)
                    callback = check_incoming_callback()
                    if callback:
                        _process_callback_query(callback, registry, self, set_telegram_confirm)

                    # Show token usage in terminal if activity occurred
                    if msg or callback:
                        print_status_bar(
                            self.config.model,
                            self.usage_stats["input_tokens"],
                            self.usage_stats["output_tokens"],
                        )
                except Exception as err:
                    logger.debug(f"Telegram processor error: {err}")

        def _process_telegram_message(msg, registry, agent, set_telegram_confirm):
            """Handle incoming text message or command."""
            from .telegram import send_telegram_message

            sender = msg.get("sender", "Telegram")
            text = msg.get("text", "")
            print_info(f"\n[Telegram from {sender}]: {text}")

            # Handle bot commands
            if msg.get("is_command"):
                cmd = msg["command"]

                # Special handling for /help — send formatted help via Telegram
                if cmd in ["/help", "/h", "/?"]:
                    commands = registry.get_telegram_command_list()
                    help_text = _format_telegram_help(commands)
                    send_telegram_message(help_text)
                    return

                # Check if command is in the allowlist
                if not registry.is_telegram_safe(cmd):
                    send_telegram_message(
                        f"⚠️ *'{cmd}' requires terminal interaction*\n\n"
                        f"This command needs direct access to your terminal. "
                        f"Please run it in the RadSim terminal session.\n\n"
                        f"Use /help to see commands available from Telegram.",
                        parse_mode="Markdown"
                    )
                    return

                # Execute safe command
                with agent._processing_lock:
                    if registry.handle_input(text, agent):
                        send_telegram_message(f"Command executed: {text}")
                        agent.system_prompt = get_system_prompt()
                    return

            # Process as normal message with Telegram confirmations
            set_telegram_confirm(_telegram_confirm)
            agent._telegram_mode = True
            try:
                with agent._processing_lock:
                    response = agent.process_message(f"[via Telegram from {sender}]: {text}")
            finally:
                agent._telegram_mode = False
                set_telegram_confirm(None)

            if response:
                reply = response if len(response) <= 4000 else response[:3997] + "..."
                result = send_telegram_message(reply)
                if result["success"]:
                    print_info("[Reply sent to Telegram]")
                else:
                    print_info(f"[Telegram reply failed: {result['error']}]")

        def _process_callback_query(callback, registry, agent, set_telegram_confirm):
            """Handle inline keyboard button presses."""
            from .telegram import (
                answer_callback_query,
                handle_callback_query,
                send_telegram_message,
            )

            action = handle_callback_query(callback)

            # Answer the callback (required by Telegram to stop loading state)
            answer_callback_query(
                callback["callback_query"]["id"],
                text=action.get("response_text")
            )

            if action["action"] == "execute_command":
                cmd = action["command"]
                args = action["args"]
                cmd_string = f"{cmd} {' '.join(args)}".strip()

                print_info(f"\n[Telegram Button]: {cmd_string}")

                # Check allowlist before executing
                if not registry.is_telegram_safe(cmd):
                    send_telegram_message(
                        f"⚠️ '{cmd}' requires terminal interaction. "
                        f"Run it in the RadSim terminal session."
                    )
                    return

                # Route /help through the special handler
                if cmd in ["/help", "/h", "/?"]:
                    _process_telegram_message(
                        {"is_command": True, "command": cmd, "args": args, "text": cmd_string, "sender": "Button"},
                        registry, agent, set_telegram_confirm
                    )
                    return

                with agent._processing_lock:
                    if registry.handle_input(cmd_string, agent):
                        send_telegram_message(f"Executed: {cmd_string}")
                        agent.system_prompt = get_system_prompt()
            elif action["action"] == "show_help":
                send_telegram_message(action["response_text"])

        def _format_telegram_help(commands: list) -> str:
            """Format help text for Telegram mobile clients."""
            lines = ["*Available Commands*\n"]
            lines.append("Commands you can run from Telegram:\n")

            for cmd in commands[:20]:  # Limit to avoid message too long
                name = cmd["command"]
                desc = cmd["description"]
                lines.append(f"`/{name}` - {desc}")

            lines.append("\nOther commands require the RadSim terminal.")
            return "\n".join(lines)

        thread = threading.Thread(target=_telegram_loop, daemon=True, name="telegram-processor")
        thread.start()

    def load_initial_context(self, file_path):
        """Load initial context from a file."""
        path = Path(file_path)
        if path.exists():
            try:
                content = path.read_text()
                self.messages.append(
                    {"role": "user", "content": f"Context loaded from {file_path}:\n\n{content}"}
                )
                # Add a dummy assistant response to acknowledge context without triggering API
                self.messages.append(
                    {
                        "role": "assistant",
                        "content": f"I have loaded the context from {file_path}. How can I help you?",
                    }
                )
                print_info(f"Loaded context from {file_path}")
            except Exception as e:
                print_error(f"Failed to load context file: {e}")
        else:
            print_warning(f"Context file not found: {file_path}")

    def update_config(self, provider, api_key, model):
        """Update agent configuration and client."""
        self.config.provider = provider
        self.config.api_key = api_key
        self.config.model = model
        self.client = create_client(provider, api_key, model)
        print_success(f"Switched to {provider} ({model})")

    def reset(self):
        """Clear conversation history."""
        self.messages = []
        self._last_response = ""
        self._current_task_start = None
        self._current_task_tools = []
        self._injected_job_ids = set()

    def estimate_tokens(self, text):
        """Estimate token count for text (rough approximation).

        Uses ~4 chars per token as a rough estimate.
        """
        return len(text) // 4

    def get_context_usage(self):
        """Get current context usage as percentage.

        Returns:
            tuple: (current_tokens, max_tokens, percentage)
        """
        from .config import CONTEXT_LIMITS

        max_tokens = CONTEXT_LIMITS.get(self.config.model, 100000)
        current_tokens = sum(self.estimate_tokens(str(m.get("content", ""))) for m in self.messages)
        # Avoid division by zero
        percentage = (current_tokens / max_tokens) * 100 if max_tokens > 0 else 0
        return current_tokens, max_tokens, percentage

    def prune_session(self, target_percentage=70):
        """Prune old messages to reduce context size.

        Keeps the first message (if it's context) and removes oldest
        messages until we're under target percentage.

        Args:
            target_percentage: Target context usage percentage (default 70%)

        Returns:
            int: Number of messages pruned
        """
        current, max_tokens, percentage = self.get_context_usage()

        if percentage <= target_percentage:
            return 0  # No pruning needed

        pruned = 0
        target_tokens = int(max_tokens * (target_percentage / 100))

        # Keep removing oldest messages (after first 2, which might be context)
        # We remove pairs to maintain conversation structure
        while current > target_tokens and len(self.messages) > 4:
            # Remove oldest pair (user + assistant) starting at index 2
            # After first pop, the second message we want is still at index 2
            self.messages.pop(2)  # Remove 3rd message (oldest after context)
            if len(self.messages) > 2:
                self.messages.pop(2)  # Remove what was 4th (now at index 2)
            pruned += 2
            current, _, _ = self.get_context_usage()

        if pruned > 0:
            print_info(f"Session pruned: removed {pruned} old messages")

        return pruned

    def check_and_prune(self, threshold=80):
        """Check context usage and prune if over threshold.

        Called before API calls to prevent context overflow.

        Args:
            threshold: Percentage threshold to trigger pruning
        """
        _, _, percentage = self.get_context_usage()
        if percentage > threshold:
            self.prune_session(target_percentage=70)

    def process_message(self, user_input):
        """Process a user message and return the response."""
        # Clear interrupt flag and mark as actively processing
        self._interrupted.clear()
        self._is_processing.set()

        # Start Escape key listener for soft cancel
        from .escape_listener import start_escape_listener, stop_escape_listener

        start_escape_listener(self)

        try:
            return self._process_message_inner(user_input)
        finally:
            stop_escape_listener()
            self._is_processing.clear()

    def _process_message_inner(self, user_input):
        """Inner message processing (wrapped by process_message for interrupt tracking)."""
        # Reset per-turn rate limiting on new user input
        self.protection.on_user_input()

        # Clear rejected writes from previous turn
        self._rejected_writes.clear()

        # Track task timing for learning
        self._current_task_start = time.time()
        self._current_task_tools = []

        # Inject completed background job results before the user message
        # so the AI sees them as context for this turn
        bg_results = self._collect_finished_background_results()
        if bg_results:
            self.messages.append({
                "role": "user",
                "content": f"[SYSTEM: Background sub-agent results arrived]\n{bg_results}",
            })
            self.messages.append({
                "role": "assistant",
                "content": "I have the background job results. Let me incorporate them.",
            })

        self.messages.append(
            {
                "role": "user",
                "content": user_input,
            }
        )

        # Auto-prune if approaching context limit
        self.check_and_prune(threshold=80)

        # Proactive context gathering: suggest optimal tool chain
        # (only if tool_optimization learning module is enabled)
        try:
            from .agent_config import get_agent_config_manager

            config_mgr = get_agent_config_manager()
            if config_mgr.is_learning_module_enabled("tool_optimization"):
                from .learning.tool_optimizer import suggest_tool_chain

                suggested_chain = suggest_tool_chain(user_input[:200])
                if suggested_chain:
                    chain_hint = ", ".join(suggested_chain[:5])
                    self.messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"[System hint: Based on past success, consider this tool sequence: {chain_hint}]",
                                }
                            ],
                        }
                    )
        except Exception:
            logger.debug("Learning suggestion failed, continuing main flow")

        response = self._call_api()
        result = self._handle_response(response)

        # Record task completion for reflection engine (gated by config)
        try:
            from .agent_config import get_agent_config_manager

            config_mgr = get_agent_config_manager()

            if config_mgr.is_learning_module_enabled("reflection"):
                task_duration = (
                    time.time() - self._current_task_start if self._current_task_start else 0
                )
                reflection_engine = get_reflection_engine()
                reflection_engine.reflect_on_completion(
                    task_description=user_input[:200],
                    approach_taken=f"Used tools: {', '.join(self._current_task_tools[:10])}",
                    result=str(result)[:200] if result else "completed",
                    success=True,  # Basic success - we got a response
                    tools_used=self._current_task_tools,
                    duration_seconds=task_duration,
                )

            if config_mgr.is_learning_module_enabled("tool_optimization"):
                tool_optimizer = get_tool_optimizer()
                tool_optimizer.complete_task_chain(user_input[:200], success=True)

            # Self-improvement: check if enough data for new proposals
            if config_mgr.get("self_improvement.enabled", False) and config_mgr.get(
                "self_improvement.auto_propose", True
            ):
                from .learning.self_improver import get_self_improver

                improver = get_self_improver()
                new_reflections = improver.get_reflection_count_since_last_analysis()
                if new_reflections >= 10:
                    new_proposals = improver.analyze_and_propose()
                    if new_proposals:
                        print_info(
                            f"Self-improvement: {len(new_proposals)} new proposal(s). "
                            "Use /evolve to review."
                        )
        except Exception:
            logger.debug("Learning completion tracking failed, continuing main flow")

        return result

    def _call_api(self):
        """Call the API with current messages."""
        # Check rate limiting before API call
        warning = self.protection.check_before_api_call()
        if warning:
            print_warning(warning)

        spinner = Spinner("Thinking...")
        spinner.start()

        try:
            if self.config.stream:
                # Streaming mode
                reset_stream_state()
                response = None
                first_chunk = True

                # Use stream_chat and handle chunks
                stream = self.client.stream_chat(
                    messages=self.messages,
                    system_prompt=self.system_prompt,
                    tools=TOOL_DEFINITIONS,
                )

                for chunk in stream:
                    if self._interrupted.is_set():
                        break

                    if first_chunk:
                        spinner.stop()
                        print()  # Start on new line
                        first_chunk = False

                    if chunk["type"] == "text_delta":
                        print_stream_chunk(chunk["text"])
                    elif chunk["type"] == "final_response":
                        response = chunk["response"]

                if first_chunk:  # If loop didn't run (empty stream)
                    spinner.stop()

                print()  # End with new line

                if response is None:
                    # Should not happen if stream yields final_response
                    response = {"content": [], "stop_reason": "error", "usage": {}}

            else:
                # Non-streaming mode
                response = self.client.chat(
                    messages=self.messages,
                    system_prompt=self.system_prompt,
                    tools=TOOL_DEFINITIONS,
                )
                spinner.stop()

            # Update usage stats
            if "usage" in response:
                input_tokens = response["usage"].get("input_tokens", 0)
                output_tokens = response["usage"].get("output_tokens", 0)
                self.usage_stats["input_tokens"] += input_tokens
                self.usage_stats["output_tokens"] += output_tokens

                # Record usage with budget guard
                budget_warning = self.protection.record_api_success(input_tokens, output_tokens)
                if budget_warning:
                    print_warning(budget_warning)

            return response

        except (RateLimitExceeded, CircuitBreakerOpen, BudgetExceeded):
            spinner.stop()
            raise  # Re-raise protection exceptions
        except Exception as e:
            spinner.stop()

            # Detect authentication errors and give clear guidance
            error_str = str(e)
            if "401" in error_str or "User not found" in error_str:
                print_error(
                    "API key is invalid or expired. "
                    "Update your key with /config or edit ~/.radsim/.env"
                )
                raise
            if "403" in error_str or "Forbidden" in error_str:
                print_error(
                    "Access denied. Your API key may not have access to this model. "
                    "Try a different model with /config"
                )
                raise

            # Record error for circuit breaker
            try:
                self.protection.record_api_error("api_error")
            except CircuitBreakerOpen:
                raise

            # Record error for learning system
            try:
                error_type = type(e).__name__
                record_error(
                    error_type=error_type,
                    error_message=str(e),
                    context={"action": "api_call", "provider": self.config.provider},
                )
            except Exception:
                logger.debug("Learning error recording failed during API error handling")

            raise e

    def _handle_response(self, response):
        """Handle the API response, including tool calls."""
        # Validate response structure before processing
        from .response_validator import validate_response_structure

        valid, error = validate_response_structure(response)
        if not valid:
            print_error(f"Invalid API response: {error}")
            return f"Error: Received malformed response from API. {error}"

        text_output = []
        tool_uses = []

        for block in response["content"]:
            if block["type"] == "text":
                text_output.append(block["text"])
            elif block["type"] == "tool_use":
                tool_uses.append(block)

        if tool_uses:
            return self._process_tool_calls(response, tool_uses, text_output)

        final_text = "\n".join(text_output)

        self.messages.append(
            {
                "role": "assistant",
                "content": final_text,
            }
        )

        # Store for learning feedback commands
        self._last_response = final_text

        return final_text

    def _process_tool_calls(self, response, tool_uses, text_output):
        """Process tool calls from the response."""
        self.messages.append(
            {
                "role": "assistant",
                "content": response["content"],
            }
        )

        tool_results = []
        user_rejected = False  # Track if user said "no" to any tool

        for tool_use in tool_uses:
            tool_name = tool_use["name"]
            tool_input = tool_use["input"]
            tool_id = tool_use["id"]

            # Check for soft cancel (Ctrl+C)
            if self._interrupted.is_set():
                user_rejected = True

            # If user already rejected a tool this turn, skip remaining tools
            if user_rejected:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(
                            {
                                "success": False,
                                "error": "STOPPED: User cancelled a previous action this turn. All remaining tool calls skipped.",
                            }
                        ),
                    }
                )
                continue

            # Check for corrupted tool input (from JSON parse failures)
            if isinstance(tool_input, dict) and "__parse_error__" in tool_input:
                print_error(f"Skipping {tool_name}: tool input was corrupted")
                raw_preview = tool_input.get("__raw__", "")[:100]
                print_warning(f"Parse error: {tool_input.get('__parse_error__')}")
                if raw_preview:
                    print_warning(f"Raw input preview: {raw_preview}...")
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(
                            {
                                "success": False,
                                "error": f"Tool input was corrupted: {tool_input.get('__parse_error__')}",
                            }
                        ),
                    }
                )
                continue

            # Track tool execution timing for learning
            tool_start_time = time.time()

            # Show tool call transparently (Claude Code style)
            if self.config.verbose or tool_name in READ_ONLY_TOOLS:
                print_tool_call(tool_name, tool_input, style="compact")

            # Use a spinner for read-only tools that don't need confirmation
            if tool_name in READ_ONLY_TOOLS:
                spinner = Spinner("Executing...")
                spinner.start()
                try:
                    result = self._execute_with_permission(tool_name, tool_input)
                finally:
                    spinner.stop()
            else:
                # Permission tools handle their own UI/spinners
                result = self._execute_with_permission(tool_name, tool_input)

            # Calculate duration and track for learning
            duration_ms = (time.time() - tool_start_time) * 1000
            tool_success = result.get("success", False)
            tool_error = result.get("error", "") if not tool_success else ""

            # Detect user rejection — stop processing remaining tools
            if not tool_success and "STOPPED" in tool_error:
                user_rejected = True

            # Show verbose result (Claude Code style)
            if self.config.verbose or tool_name in READ_ONLY_TOOLS:
                print_tool_result_verbose(tool_name, result, duration_ms)

            # Track tool execution with learning system
            try:
                track_tool_execution(
                    tool_name=tool_name,
                    success=tool_success,
                    duration_ms=duration_ms,
                    input_data=tool_input,
                    output_data=result,
                    error=tool_error,
                )
                # Track tools used in current task
                self._current_task_tools.append(tool_name)
            except Exception:
                logger.debug("Learning tool tracking failed during tool execution")

            # Send tool progress to Telegram if processing a Telegram message
            if self._telegram_mode:
                try:
                    from .telegram import send_telegram_message

                    icon = "+" if tool_success else "x"
                    send_telegram_message(f"[{icon}] {tool_name}")
                except Exception:
                    pass

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": json.dumps(result),
                }
            )

        self.messages.append(
            {
                "role": "user",
                "content": tool_results,
            }
        )

        # If user rejected a tool call or interrupted, stop the turn
        if user_rejected:
            return text_output or "Understood — action cancelled."

        # Check for soft cancel before making follow-up API call
        if self._interrupted.is_set():
            return text_output or "Cancelled."

        follow_up = self._call_api()
        return self._handle_response(follow_up)

    def _execute_with_permission(self, tool_name, tool_input):
        """Execute a tool with appropriate permission checks."""

        # Check error history for known failure patterns
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

        # Tool enablement gate — check if tool is allowed by agent config
        try:
            from .agent_config import get_agent_config_manager

            config_mgr = get_agent_config_manager()
            if not config_mgr.is_tool_enabled(tool_name):
                return {
                    "success": False,
                    "error": (
                        f"Tool '{tool_name}' is disabled in agent settings. "
                        "Use /settings to enable it."
                    ),
                }
        except Exception:
            logger.debug("Agent config check failed, allowing tool execution")

        # Agentic Delegation
        if tool_name == "delegate_task":
            return self._handle_delegate_task(tool_input)

        # Browser Tools
        if tool_name.startswith("browser_"):
            return self._handle_browser_tool(tool_name, tool_input)

        # System Tools
        if tool_name == "install_system_tool":
            return self._handle_system_tool(tool_input)

        # Write file - needs confirmation
        if tool_name == "write_file":
            return self._handle_write_file(tool_input)

        # Replace in file - needs confirmation
        if tool_name == "replace_in_file":
            return self._handle_replace(tool_input)

        # Rename file - needs confirmation
        if tool_name == "rename_file":
            return self._handle_rename(tool_input)

        # Delete file - needs confirmation (destructive)
        if tool_name == "delete_file":
            return self._handle_delete(tool_input)

        # Shell command - needs confirmation
        if tool_name == "run_shell_command":
            return self._handle_shell_command(tool_input)

        # Web fetch - needs confirmation for security
        if tool_name == "web_fetch":
            return self._handle_web_fetch(tool_input)

        # Create directory - light confirmation
        if tool_name == "create_directory":
            return self._handle_create_directory(tool_input)

        # Git write operations
        if tool_name == "git_add":
            return self._handle_git_add(tool_input)

        if tool_name == "git_commit":
            return self._handle_git_commit(tool_input)

        if tool_name == "git_checkout":
            return self._handle_git_checkout(tool_input)

        if tool_name == "git_stash":
            return self._handle_git_stash(tool_input)

        # Testing & Validation tools
        if tool_name == "run_tests":
            return self._handle_run_tests(tool_input)

        if tool_name == "lint_code":
            return self._handle_lint_code(tool_input)

        if tool_name == "format_code":
            return self._handle_format_code(tool_input)

        if tool_name == "type_check":
            return self._handle_type_check(tool_input)

        # Dependency management
        if tool_name == "add_dependency":
            return self._handle_add_dependency(tool_input)

        if tool_name == "remove_dependency":
            return self._handle_remove_dependency(tool_input)

        # Batch operations
        if tool_name == "batch_replace":
            return self._handle_batch_replace(tool_input)

        # Atomic multi-edit
        if tool_name == "multi_edit":
            return self._handle_multi_edit(tool_input)

        # Multi-file patch
        if tool_name == "apply_patch":
            return self._handle_apply_patch(tool_input)

        # Task tracking (read-only, no confirmation needed)
        if tool_name in ("todo_read", "todo_write"):
            result = execute_tool(tool_name, tool_input)
            self._print_tool_result(tool_name, tool_input, result)
            return result

        # Context management (light confirmation)
        if tool_name == "save_context":
            return self._handle_save_context(tool_input)

        # Memory management (needs confirmation)
        if tool_name == "save_memory":
            return self._handle_save_memory(tool_input)

        # Task scheduling (needs confirmation)
        if tool_name == "schedule_task":
            return self._handle_schedule_task(tool_input)

        # Read-only tools - execute directly
        if tool_name in READ_ONLY_TOOLS:
            result = execute_tool(tool_name, tool_input)
            self._print_tool_result(tool_name, tool_input, result)
            return result

        # Unknown tools - execute with warning
        print_warning(f"Unknown tool: {tool_name}")
        result = execute_tool(tool_name, tool_input)
        self._print_tool_result(tool_name, tool_input, result)
        return result

    def _resolve_subagent_model(self, requested_model):
        """Resolve sub-agent model to an OpenRouter config model.

        Sub-agents ALWAYS run via OpenRouter. The "current" option is
        not supported — sub-agents never use the main agent's model.

        Args:
            requested_model: Model alias or ID requested for the sub-agent

        Returns:
            Tuple of (model, "openrouter", "") — always OpenRouter
        """
        from .sub_agent import resolve_model_name

        resolved = resolve_model_name(requested_model)
        return resolved, "openrouter", ""

    def _prompt_subagent_model(self):
        """Prompt user to select a model for sub-agent tasks.

        Shows Haiku (fast/cheap) as default, then the OpenRouter
        config models for bigger tasks. Stores the selection in
        self._session_capable_model for the rest of the session.

        Returns:
            Tuple of (model_id, "openrouter", "")
        """
        from .menu import interactive_menu
        from .sub_agent import HAIKU_MODEL, get_available_models

        # Build options: Haiku first (recommended default), then config models
        options = [(HAIKU_MODEL, "Claude Haiku 4.5 (Fast & cheap — recommended)")]
        for model_id, description in get_available_models():
            if model_id != HAIKU_MODEL:
                options.append((model_id, description))

        print_info("Select a model for sub-agent tasks (OpenRouter):")
        choice = interactive_menu("SUB-AGENT MODEL", options)

        if choice is None:
            print_info(f"No selection — using Haiku: {HAIKU_MODEL}")
            self._session_capable_model = HAIKU_MODEL
        else:
            self._session_capable_model = choice
            print_success(f"Session model set: {choice}")

        return self._session_capable_model, "openrouter", ""

    def _on_background_job_complete(self, job):
        """Callback when a background job finishes. Prints notification."""
        import sys

        from .output import supports_color

        yellow = "\033[33m" if supports_color() else ""
        green = "\033[32m" if supports_color() else ""
        red = "\033[31m" if supports_color() else ""
        dim = "\033[2m" if supports_color() else ""
        reset = "\033[0m" if supports_color() else ""
        duration = f"{job.duration:.1f}s"

        if job.status.value == "completed":
            icon = green + "+" + reset
            status = "completed"
        else:
            icon = red + "x" + reset
            status = job.status.value

        # Header
        line = f"\n{yellow}[{icon} Background job #{job.job_id} {status} ({duration})]{reset}\n"
        sys.stdout.write(line)

        # Show result preview for completed jobs
        if job.status.value == "completed" and job.result_content:
            preview_lines = job.result_content.strip().splitlines()
            max_preview = 15
            for pline in preview_lines[:max_preview]:
                sys.stdout.write(f"  {dim}{pline[:120]}{reset}\n")
            if len(preview_lines) > max_preview:
                sys.stdout.write(f"  {dim}... ({len(preview_lines) - max_preview} more lines — /bg {job.job_id} for full output){reset}\n")
        elif job.error:
            sys.stdout.write(f"  {red}Error: {job.error[:200]}{reset}\n")

        sys.stdout.write("\n")
        sys.stdout.flush()

    def _collect_finished_background_results(self):
        """Collect results from completed background jobs and inject into messages.

        Called at the start of each user turn so the AI model sees
        any results that arrived while the user was idle.

        Returns:
            str or None: Summary of completed job results, or None if no jobs finished.
        """
        from .background import get_job_manager

        manager = get_job_manager()
        injected_ids = getattr(self, "_injected_job_ids", set())

        parts = []
        for job in manager.list_jobs():
            if job.job_id in injected_ids:
                continue
            if job.status.value == "completed" and job.result_content:
                duration = f"{job.duration:.1f}s"
                parts.append(
                    f"[Background job #{job.job_id} COMPLETED ({duration})]\n"
                    f"Task: {job.description}\n"
                    f"Results:\n{job.result_content}"
                )
                injected_ids.add(job.job_id)
            elif job.status.value == "failed":
                parts.append(
                    f"[Background job #{job.job_id} FAILED]\n"
                    f"Task: {job.description}\n"
                    f"Error: {job.error}"
                )
                injected_ids.add(job.job_id)

        self._injected_job_ids = injected_ids

        if parts:
            return "\n\n".join(parts)
        return None

    def _should_stream_subagent(self):
        """Check if sub-agent streaming output is enabled in agent config."""
        from .agent_config import AgentConfigManager

        config_manager = AgentConfigManager()
        return config_manager.get("subagents.stream_output", True)

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
        import sys

        from .output import supports_color
        from .sub_agent import SubAgentTask, stream_subagent_task

        task = SubAgentTask(
            task_description=task_desc,
            model=model,
            provider=provider,
            api_key=api_key,
            system_prompt=system_prompt,
            tools=tools or [],
            max_iterations=max_iterations,
        )

        # Print header for sub-agent output
        dim = "\033[2m" if supports_color() else ""
        cyan = "\033[36m" if supports_color() else ""
        reset = "\033[0m" if supports_color() else ""
        sys.stdout.write(f"\n{dim}{'─' * 40}{reset}\n")
        sys.stdout.write(f"{cyan}  Sub-agent output ({model}):{reset}\n")
        sys.stdout.write(f"{dim}{'─' * 40}{reset}\n")
        sys.stdout.flush()

        # Stream the response
        generator = stream_subagent_task(task)
        result = None

        try:
            while True:
                chunk = next(generator)
                chunk_type = chunk.get("type", "")
                if chunk_type == "tool_status":
                    # Show tool execution status in cyan
                    sys.stdout.write(f"\n{cyan}  ⚙ {chunk.get('text', '')}{reset}\n")
                    sys.stdout.flush()
                else:
                    text = chunk.get("text", "")
                    sys.stdout.write(f"{dim}{text}{reset}")
                    sys.stdout.flush()
        except StopIteration as stop:
            result = stop.value

        # Print footer
        sys.stdout.write(f"\n{dim}{'─' * 40}{reset}\n")
        sys.stdout.flush()

        return result

    def _handle_delegate_task(self, tool_input):
        """Handle delegation to a sub-agent with model selection and parallel support."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from .sub_agent import delegate_task as subagent_delegate
        from .sub_agent import resolve_task_config

        task_desc = tool_input.get("task_description", "")
        context = tool_input.get("context", "")
        explicit_model = tool_input.get("model", "")
        tier = tool_input.get("tier", "fast")
        parallel_tasks = tool_input.get("parallel_tasks", [])
        system_prompt = tool_input.get("system_prompt", "")

        # Ignore "current" — sub-agents never use the main agent's model
        if explicit_model == "current":
            explicit_model = ""

        # Resolve tier config to get tools, max_tokens, and default model
        from .sub_agent import HAIKU_MODEL

        tier_config = resolve_task_config(task_desc, tier=tier, model=None)
        tier_tools = tier_config["tools"]

        # If context provided, prepend it to task description
        if context:
            task_desc = f"CONTEXT:\n{context}\n\nTASK:\n{task_desc}"

        # Read background flag early
        background = tool_input.get("background", True)

        # Parallel execution mode
        if parallel_tasks:
            # Prompt user for model on first sub-agent use (unless background/telegram)
            if not self._session_capable_model and not self._telegram_mode:
                self._prompt_subagent_model()
            session_model = self._session_capable_model or HAIKU_MODEL

            print_info(f"Delegating {len(parallel_tasks)} tasks in parallel (model: {session_model})...")

            def run_parallel():
                results = []
                with ThreadPoolExecutor(max_workers=min(3, len(parallel_tasks))) as executor:
                    futures = {}
                    for i, pt in enumerate(parallel_tasks):
                        pt_task = pt.get("task", "")
                        pt_prompt = pt.get("system_prompt", "")

                        # Use session model for all parallel tasks
                        resolved_model = session_model
                        resolved_provider = "openrouter"
                        resolved_key = ""
                        future = executor.submit(
                            subagent_delegate,
                            pt_task,
                            model=resolved_model,
                            provider=resolved_provider,
                            api_key=resolved_key,
                            system_prompt=pt_prompt,
                            tools=tier_tools,
                            max_iterations=10,
                        )
                        futures[future] = {"index": i, "model": resolved_model}

                    for future in as_completed(futures):
                        info = futures[future]
                        try:
                            result = future.result()
                            results.append(
                                {
                                    "index": info["index"],
                                    "model": info["model"],
                                    "success": result.success,
                                    "content": result.content,
                                    "error": result.error,
                                    "input_tokens": result.input_tokens,
                                    "output_tokens": result.output_tokens,
                                }
                            )
                        except Exception as e:
                            results.append(
                                {
                                    "index": info["index"],
                                    "model": info["model"],
                                    "success": False,
                                    "error": str(e),
                                }
                            )

                # Sort by original index
                results.sort(key=lambda x: x["index"])
                success_count = sum(1 for r in results if r.get("success"))

                # Combine content for the result wrapper
                combined_content = f"Parallel delegation complete: {success_count}/{len(results)} succeeded\n\n"
                for i, r in enumerate(results):
                    status = "✅" if r.get("success") else "❌"
                    combined_content += f"--- Task {i + 1} ({status}) ---\n"
                    if r.get("success"):
                        combined_content += r.get("content", "") + "\n\n"
                    else:
                        combined_content += r.get("error", "") + "\n\n"

                from .sub_agent import SubAgentResult
                return SubAgentResult(
                    success=success_count > 0,
                    content=combined_content,
                    model_used="multiple",
                    provider_used="openrouter",
                    input_tokens=sum(r.get("input_tokens", 0) for r in results),
                    output_tokens=sum(r.get("output_tokens", 0) for r in results),
                    error="" if success_count > 0 else "Some parallel tasks failed.",
                )

            if background:
                from .background import get_job_manager
                manager = get_job_manager()

                # Build descriptive task list for /bg display
                task_descriptions = [pt.get("task", "")[:80] for pt in parallel_tasks]
                desc_summary = " | ".join(
                    pt.get("task", "task")[:40] for pt in parallel_tasks
                )

                job = manager.start_job(
                    description=desc_summary[:100],
                    run_function=run_parallel,
                    model=session_model,
                    tier=tier,
                    sub_tasks=task_descriptions,
                )
                print_success(f"Background parallel job #{job.job_id} started — /bg {job.job_id} to check")
                return {
                    "success": True,
                    "background": True,
                    "job_id": job.job_id,
                    "message": f"{len(parallel_tasks)} parallel tasks running in background as job #{job.job_id}. Use /bg to check status.",
                }
            else:
                # Run synchronously
                sync_result = run_parallel()
                return {
                    "success": sync_result.success,
                    "content": sync_result.content,
                    "models_used": "multiple",
                    "input_tokens": sync_result.input_tokens,
                    "output_tokens": sync_result.output_tokens,
                    "error": sync_result.error,
                }

        # Resolve model — sub-agents ALWAYS use OpenRouter
        # If user already picked a model this session, reuse it.
        # Otherwise, prompt them to choose (Haiku default, or pick from config list).
        if explicit_model:
            # AI explicitly requested a model — validate against config
            resolved_model, resolved_provider, resolved_key = self._resolve_subagent_model(
                explicit_model
            )
        elif self._session_capable_model:
            # User already picked a model this session — reuse it
            resolved_model = self._session_capable_model
            resolved_provider = "openrouter"
            resolved_key = ""
        elif background or self._telegram_mode:
            # Can't prompt interactively — use Haiku
            resolved_model = HAIKU_MODEL
            resolved_provider = "openrouter"
            resolved_key = ""
        else:
            # First sub-agent use this session — ask user to pick
            resolved_model, resolved_provider, resolved_key = self._prompt_subagent_model()

        print_info(f"Delegating task to sub-agent (model: {resolved_model}, tier: {tier})")

        # Background execution: run in thread and return immediately
        if background:
            from .background import get_job_manager

            manager = get_job_manager()

            def run_background():
                return subagent_delegate(
                    task_desc,
                    model=resolved_model,
                    provider=resolved_provider,
                    api_key=resolved_key,
                    system_prompt=system_prompt,
                    tools=tier_tools,
                    max_iterations=10,
                )

            job = manager.start_job(
                description=task_desc[:100],
                run_function=run_background,
                model=resolved_model,
                tier=tier,
            )
            print_success(f"Background job #{job.job_id} started — /bg {job.job_id} to check")
            return {
                "success": True,
                "background": True,
                "job_id": job.job_id,
                "message": f"Task running in background as job #{job.job_id}. Use /bg to check status.",
            }

        # Foreground execution
        stream_output = self._should_stream_subagent()

        if stream_output:
            result = self._stream_delegate_task(
                task_desc,
                resolved_model,
                resolved_provider,
                resolved_key,
                system_prompt,
                tools=tier_tools,
                max_iterations=10,
            )
        else:
            result = subagent_delegate(
                task_desc,
                model=resolved_model,
                provider=resolved_provider,
                api_key=resolved_key,
                system_prompt=system_prompt,
                tools=tier_tools,
                max_iterations=10,
            )

        if result.success:
            print_success(f"Sub-agent completed (model: {result.model_used})")
            return {
                "success": True,
                "content": result.content,
                "model_used": result.model_used,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            }
        else:
            print_error(f"Sub-agent failed: {result.error}")
            return {
                "success": False,
                "error": result.error,
                "model_used": result.model_used,
            }

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
        from pathlib import Path

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
                        "Teach mode is ON but no 🎓 annotations found. "
                        "Requesting the model to regenerate with annotations..."
                    )
                    return {
                        "success": False,
                        "error": (
                            "REJECTED: Teach mode is active but your code contains ZERO "
                            "🎓 annotations. This is NOT acceptable. You MUST re-generate "
                            "the SAME code with inline `# 🎓 ` teaching annotations above "
                            "every function, class, import, and significant construct. "
                            "Each annotation block must be 3-6 lines. "
                            "Re-call write_file with the annotated version NOW."
                        ),
                    }
                else:
                    # Already retried once — warn but proceed to avoid infinite loop
                    self._teach_retry_attempted = False
                    print_warning(
                        "⚠ Teach mode is ON but this model still didn't generate 🎓 annotations. "
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
            confirmed = confirm_action("Apply this change?", config=self.config)

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
            # Show command being run (Claude Code style)
            print_tool_call("run_shell_command", {"command": command}, style="full")

            spinner = Spinner("Executing...")
            spinner.start()
            try:
                result = execute_tool("run_shell_command", tool_input)
            finally:
                spinner.stop()

            # Show output in visible panel
            if result.get("stdout") or result.get("stderr"):
                print_shell_output(result.get("stdout", ""), result.get("stderr", ""), max_lines=30)

            if result["success"]:
                print_success(f"Exit code: {result.get('returncode', 0)}")
            else:
                print_error(f"Command failed (exit {result.get('returncode', '?')})")

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
            confirmed = confirm_action(f"Create directory: '{directory_path}'?", config=self.config)

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
            confirmed = confirm_action(f"Stage {desc}?", config=self.config)

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
            confirmed = confirm_action(f"Run tests: {desc}?", config=self.config)

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
            confirmed = confirm_action(f"{action} {desc}?", config=self.config)

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

        if self.config.auto_confirm and check_only:
            print_info(f"{action}: {desc}")
            confirmed = True
        else:
            confirmed = confirm_action(f"{action} in {desc}?", config=self.config)

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
            confirmed = confirm_action(
                f"Save to {memory_type} memory?\n  Key: {key}\n  Value: {preview}",
                config=self.config,
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
        if not result.get("success", False):
            print_error(f"{tool_name}: {result.get('error', 'Failed')}")
            return

        if tool_name == "read_file":
            file_path = tool_input.get("file_path", "")
            lines = result.get("line_count", 0)
            print_info(f"Read: {file_path} ({lines} lines)")

        elif tool_name == "read_many_files":
            count = result.get("count", 0)
            print_info(f"Read {count} files")

        elif tool_name == "list_directory":
            dir_path = tool_input.get("directory_path", ".")
            items = result.get("count", 0)
            print_info(f"Listed: {dir_path} ({items} items)")

        elif tool_name == "glob_files":
            pattern = tool_input.get("pattern", "")
            count = result.get("count", 0)
            print_info(f"Glob '{pattern}': {count} matches")

        elif tool_name == "grep_search":
            pattern = tool_input.get("pattern", "")
            count = result.get("count", 0)
            files = result.get("files_searched", 0)
            print_info(f"Grep '{pattern}': {count} matches in {files} files")

        elif tool_name == "search_files":
            pattern = tool_input.get("pattern", "")
            count = result.get("count", 0)
            print_info(f"Search '{pattern}': {count} files")

        elif tool_name == "git_status":
            print_info("Git status retrieved")

        elif tool_name == "git_diff":
            staged = tool_input.get("staged", False)
            print_info(f"Git diff ({'staged' if staged else 'unstaged'})")

        elif tool_name == "git_log":
            count = tool_input.get("count", 10)
            print_info(f"Git log ({count} commits)")

        elif tool_name == "git_branch":
            print_info("Git branches listed")

        elif tool_name == "find_definition":
            symbol = tool_input.get("symbol", "")
            count = result.get("count", 0)
            print_info(f"Find definition '{symbol}': {count} found")

        elif tool_name == "find_references":
            symbol = tool_input.get("symbol", "")
            count = result.get("count", 0)
            print_info(f"Find references '{symbol}': {count} found")

        elif tool_name == "get_project_info":
            project_type = result.get("project_type", "unknown")
            print_info(f"Project type: {project_type}")

        elif tool_name == "list_dependencies":
            pkg_manager = result.get("package_manager", "unknown")
            print_info(f"Dependencies listed ({pkg_manager})")

        elif tool_name == "plan_task":
            task_id = result.get("task_id", "")
            subtask_count = len(result.get("subtasks", []))
            print_info(f"Task planned: {task_id} ({subtask_count} subtasks)")

        elif tool_name == "load_context":
            saved_at = result.get("saved_at", "unknown")
            print_info(f"Context loaded (saved: {saved_at})")

        else:
            print_info(f"{tool_name}: OK")


class TaskCompleted(Exception):
    """Exception raised when a sub-agent completes its task."""

    def __init__(self, result):
        self.result = result


class SubAgent(RadSimAgent):
    """A sub-agent that performs a delegated task."""

    def _execute_with_permission(self, tool_name, tool_input):
        """Execute tool, intercepting completion."""
        if tool_name == "submit_completion":
            # For sub-agents, this is the exit condition
            result = execute_tool("submit_completion", tool_input)
            raise TaskCompleted(result)

        return super()._execute_with_permission(tool_name, tool_input)


def run_single_shot(config, prompt, context_file=None):
    """Run a single-shot command and return the result."""
    agent = RadSimAgent(config, context_file)
    return agent.process_message(prompt)


def run_interactive(config, context_file=None):
    """Run the interactive conversation loop."""

    from .memory import load_memory
    from .modes import get_active_modes
    from .output import print_header, print_info, print_prompt, print_status_bar

    agent = RadSimAgent(config, context_file)
    registry = CommandRegistry()

    # Register agent for soft cancel (Ctrl+C)
    from .cli import set_active_agent

    set_active_agent(agent)

    print_header(config.provider, config.model)

    # Load persistent memory (preferences, etc)
    mem_result = load_memory(memory_type="preference")
    user_name = None
    if mem_result["success"] and mem_result.get("data"):
        data = mem_result["data"]
        # Check for various name keys
        user_name = data.get("name") or data.get("username") or data.get("user")

        # Load other preferences if needed
        if user_name:
            print_info(f"Welcome back, {user_name}!")

    from .memory import Memory
    memory = Memory()
    agents_md_path = memory.project_mem.agents_file

    if agents_md_path.exists() and not context_file:
        # Auto-load agents.md if it exists and no explicit context file provided
        agent.load_initial_context(str(agents_md_path))

    if memory.session_mem.is_expired():
        # Start fresh session visually
        print_info("Started new session (previous session expired).")
        import datetime
        memory.session_mem.data = {
                 "started_at": datetime.datetime.now().isoformat(),
                 "last_active": datetime.datetime.now().isoformat(),
                 "active_task": "",
                 "conversation_summary": ""
        }
        memory.session_mem.update_activity()
    else:
        if memory.session_mem.data.get("active_task"):
            print_info(f"Resumed session. Active Task: {memory.session_mem.data['active_task']}")
            memory.session_mem.update_activity()

    # Start background Telegram processor (auto-processes messages without Enter)
    agent.start_telegram_processor()

    while True:
        try:
            # Show active modes in prompt
            active_modes = get_active_modes()
            user_input = print_prompt(active_modes)
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input.strip():
            continue

        # Check for action hotkeys (e.g., S for show code)
        from .keybindings import check_action_hotkey

        action = check_action_hotkey(user_input.strip())
        if action == "show_code":
            from .output import print_all_session_code

            print_all_session_code()
            continue

        # Check for mode hotkeys (e.g., T for teach, V for verbose)
        from .keybindings import check_hotkey
        from .modes import toggle_mode

        hotkey_mode = check_hotkey(user_input.strip())
        if hotkey_mode:
            is_active, message = toggle_mode(hotkey_mode)
            if is_active:
                print_info(f"✓ {message} - teaching in ALL responses enabled")
            else:
                print_info(f"✓ {message}")
            agent.system_prompt = get_system_prompt()
            continue

        # Handle slash commands (may toggle modes)
        if registry.handle_input(user_input, agent):
            # Refresh system prompt in case modes changed
            agent.system_prompt = get_system_prompt()
            continue

        # Check for natural language help intent (e.g. "how do I use skills?")
        from .commands import detect_help_intent

        help_topic = detect_help_intent(user_input)
        if help_topic:
            from .output import print_help

            print_help(topic=help_topic)
            continue

        try:
            # Pass user name in context if available
            if user_name and len(agent.messages) == 0:
                agent.messages.append(
                    {"role": "user", "content": f"[System: The user's name is {user_name}]"}
                )
                # Remove it so it doesn't mess up the chat history display,
                # but we need it for the first request context.
                # Actually, better to just let the first prompt handle it or system prompt.
                # Let's just prepend it to the first user input invisibly?
                # or just set it in the agent.
                pass

            with agent._processing_lock:
                response = agent.process_message(user_input)

            try:
                from .memory import Memory
                Memory().session_mem.update_activity()
            except Exception:
                pass

            # Only print response if not streaming (streaming already prints during _call_api)
            if not config.stream:
                print_agent_response(response)

            # Print status bar with token usage
            print_status_bar(
                config.model, agent.usage_stats["input_tokens"], agent.usage_stats["output_tokens"]
            )

        except RateLimitExceeded as e:
            print_error(f"\n🛑 LOOP PROTECTION: {e}")
            print_warning("The AI was making too many consecutive calls. Try a simpler request.")
        except CircuitBreakerOpen as e:
            print_error(f"\n🛑 ERROR PROTECTION: {e}")
            print_warning("Too many consecutive errors. Please wait before retrying.")
        except BudgetExceeded as e:
            print_error(f"\n🛑 BUDGET PROTECTION: {e}")
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

    print()
