"""API orchestration helpers for the main agent."""

import json
import logging
import time

from .agent_constants import READ_ONLY_TOOLS
from .learning import flush_tool_optimizer, record_error, track_tool_execution
from .output import (
    Spinner,
    finish_stream,
    print_error,
    print_stream_chunk,
    print_tool_call,
    print_tool_result_verbose,
    print_warning,
    reset_stream_state,
)
from .performance import PerformanceTelemetry, request_payload_metrics
from .prompts import get_system_prompt
from .rate_limiter import BudgetExceeded, CircuitBreakerOpen, RateLimitExceeded
from .tool_router import (
    group_for_tool,
    route_tool_schemas,
    routing_enabled,
    schema_budget_tokens,
    tools_in_group,
)
from .tool_scheduler import plan_parallel_group, run_parallel_group
from .tools import TOOL_DEFINITIONS
from .usage import accumulate_usage

logger = logging.getLogger(__name__)

MAX_SERIALIZED_TOOL_RESULT_CHARS = 100_000


def serialize_tool_result(result):
    """Serialize a tool result to JSON without ever crashing the turn.

    Tool results can contain non-JSON types (bytes, Path, datetime).
    Falling back to default=str keeps the tool_use/tool_result pairing
    intact so the conversation stays valid for the API.
    """
    try:
        serialized = json.dumps(result)
    except (TypeError, ValueError):
        serialized = json.dumps(result, default=str)
    if len(serialized) <= MAX_SERIALIZED_TOOL_RESULT_CHARS:
        return serialized
    return _truncated_tool_result(result, serialized)


def _truncated_tool_result(result, serialized):
    """Return valid, bounded JSON with an explicit truncation marker."""
    preview_size = MAX_SERIALIZED_TOOL_RESULT_CHARS // 2
    while preview_size > 0:
        payload = {
            "success": bool(result.get("success", False)) if isinstance(result, dict) else False,
            "truncated": True,
            "original_chars": len(serialized),
            "preview": serialized[:preview_size],
        }
        encoded = json.dumps(payload)
        if len(encoded) <= MAX_SERIALIZED_TOOL_RESULT_CHARS:
            return encoded
        preview_size //= 2
    return json.dumps({"success": False, "truncated": True})


def extract_image_block(result):
    """Pop a tool's private _image payload and return its message block.

    Image bytes travel as message blocks, never as tool-result text: base64
    in the transcript would burn tokens and the model could not see the
    pixels anyway.
    """
    if not isinstance(result, dict):
        return None
    payload = result.pop("_image", None)
    if not payload or not result.get("success"):
        return None
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": payload["media_type"],
            "data": payload["data"],
        },
    }


class AgentApiMixin:
    """API call and response handling methods for the main agent."""

    def _get_all_tools(self):
        """Return native tool definitions plus any MCP tools."""
        tools = list(TOOL_DEFINITIONS)
        if self._mcp_manager:
            mcp_tools = self._mcp_manager.get_all_tools()
            if mcp_tools:
                tools.extend(mcp_tools)
        return tools

    def _get_request_tools(self):
        """Return the schemas for this request, honouring the turn's routing."""
        tools = self._get_all_tools()
        routed_names = getattr(self, "_routed_tool_names", None)
        if not routed_names:
            return tools
        return [tool for tool in tools if tool.get("name") in routed_names]

    def _route_tool_schemas_for_turn(self, user_input, telemetry, turn_id):
        """Choose one stable schema set for the whole turn.

        Routing is opt-in and filters schemas only: permission tiers,
        confirmation prompts, and policy checks are unchanged, and any
        registry the router cannot classify keeps every schema.
        """
        self._routed_tool_names = None
        if not routing_enabled():
            return

        decision = route_tool_schemas(
            self._get_all_tools(),
            user_input,
            budget_tokens=schema_budget_tokens(),
        )
        if not decision.failed:
            self._routed_tool_names = decision.tool_names

        telemetry.emit(
            "tool_routing",
            turn_id=turn_id,
            routing_enabled=True,
            routing_failed=decision.failed,
            routed_groups=",".join(decision.group_names),
            routed_group_count=len(decision.group_names),
            routing_dropped_groups=",".join(decision.dropped_group_names),
            routed_tool_count=len(decision.tools),
            routed_schema_tokens=decision.schema_tokens,
            routing_budget_tokens=decision.budget_tokens,
        )

    def _recover_routed_tool(self, tool_name):
        """Add an omitted tool's capability group back for the rest of the turn.

        The model can still name a tool whose schema was routed away. The
        call is never blocked by routing, so recovery only restores the
        group's schemas and records how often routing was too narrow.
        """
        routed_names = getattr(self, "_routed_tool_names", None)
        if not routed_names or tool_name in routed_names:
            return

        available_names = {tool.get("name") for tool in self._get_all_tools()}
        group_name = group_for_tool(tool_name, available_names)
        recovered = tools_in_group(group_name, available_names) if group_name else ()
        self._routed_tool_names = routed_names | set(recovered) | {tool_name}

        telemetry = getattr(self, "performance_telemetry", None) or PerformanceTelemetry()
        telemetry.emit(
            "tool_routing_recovery",
            turn_id=getattr(self, "_performance_turn_id", None),
            tool_name=tool_name,
            routing_recovered_group=group_name or "",
            routed_tool_count=len(self._routed_tool_names),
        )

    def _call_api(self):
        """Call the API with current messages."""
        from .context_budget import DEFAULT_CONTEXT_OUTPUT_RESERVE_TOKENS

        prompt_started_at = time.perf_counter()
        self.system_prompt = get_system_prompt()
        prompt_construction_ms = (time.perf_counter() - prompt_started_at) * 1000
        self.check_and_prune()
        output_reserve_tokens = getattr(
            self.config,
            "context_output_reserve_tokens",
            DEFAULT_CONTEXT_OUTPUT_RESERVE_TOKENS,
        )

        warning = self.protection.check_before_api_call()
        if warning:
            print_warning(warning)

        assembly_started_at = time.perf_counter()
        all_tools = self._get_request_tools()
        telemetry = getattr(self, "performance_telemetry", None) or PerformanceTelemetry()
        request_metrics = (
            request_payload_metrics(self.system_prompt, all_tools) if telemetry.enabled else {}
        )
        request_assembly_ms = (time.perf_counter() - assembly_started_at) * 1000
        self._performance_request_index = getattr(self, "_performance_request_index", 0) + 1
        request_index = self._performance_request_index
        telemetry.emit(
            "provider_request",
            turn_id=getattr(self, "_performance_turn_id", None),
            provider=getattr(self.config, "provider", ""),
            model=getattr(self.config, "model", ""),
            request_index=request_index,
            message_count=len(self.messages),
            prompt_construction_ms=prompt_construction_ms,
            request_assembly_ms=request_assembly_ms,
            **request_metrics,
        )

        spinner = Spinner("Thinking...")
        spinner.start()
        provider_started_at = time.perf_counter()
        first_chunk_ms = None

        try:
            if self.config.stream:
                reset_stream_state()
                response = None
                first_chunk = True
                stream = self.client.stream_chat(
                    messages=self.messages,
                    system_prompt=self.system_prompt,
                    tools=all_tools,
                    max_tokens=output_reserve_tokens,
                )

                for chunk in stream:
                    if self._interrupted.is_set():
                        break

                    if first_chunk:
                        first_chunk_ms = (time.perf_counter() - provider_started_at) * 1000
                        spinner.stop()
                        print()
                        first_chunk = False

                    if chunk["type"] == "text_delta":
                        print_stream_chunk(chunk["text"])
                    elif chunk["type"] == "final_response":
                        response = chunk["response"]

                if first_chunk:
                    spinner.stop()

                finish_stream()
                print()

                if response is None:
                    response = {"content": [], "stop_reason": "error", "usage": {}}
            else:
                response = self.client.chat(
                    messages=self.messages,
                    system_prompt=self.system_prompt,
                    tools=all_tools,
                    max_tokens=output_reserve_tokens,
                )
                spinner.stop()

            if "usage" in response:
                input_tokens = response["usage"].get("input_tokens", 0)
                output_tokens = response["usage"].get("output_tokens", 0)
                accumulate_usage(self.usage_stats, response["usage"])

                budget_warning = self.protection.record_api_success(input_tokens, output_tokens)
                if budget_warning:
                    print_warning(budget_warning)

            usage = response.get("usage", {})
            telemetry.emit(
                "provider_response",
                turn_id=getattr(self, "_performance_turn_id", None),
                provider=getattr(self.config, "provider", ""),
                model=getattr(self.config, "model", ""),
                request_index=request_index,
                duration_ms=(time.perf_counter() - provider_started_at) * 1000,
                first_chunk_ms=first_chunk_ms,
                success=True,
                stop_reason=str(response.get("stop_reason", ""))[:80],
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
                cache_write_input_tokens=usage.get("cache_write_input_tokens", 0),
                retry_attempts=usage.get("retry_attempts", 0),
            )

            try:
                from .hooks import HookContext, HookType, get_hooks_manager

                get_hooks_manager().execute(
                    HookType.POST_API,
                    HookContext(
                        hook_type=HookType.POST_API,
                        metadata={
                            "provider": getattr(self.config, "provider", ""),
                            "model": getattr(self.config, "model", ""),
                            "stop_reason": str(response.get("stop_reason", ""))[:80],
                            "usage": dict(response.get("usage", {})),
                        },
                    ),
                )
            except Exception:
                logger.debug("post_api hooks failed", exc_info=True)

            return response

        except (RateLimitExceeded, CircuitBreakerOpen, BudgetExceeded):
            spinner.stop()
            telemetry.emit(
                "provider_response",
                turn_id=getattr(self, "_performance_turn_id", None),
                provider=getattr(self.config, "provider", ""),
                model=getattr(self.config, "model", ""),
                request_index=request_index,
                duration_ms=(time.perf_counter() - provider_started_at) * 1000,
                success=False,
                error_type="protection_stop",
            )
            raise
        except Exception as error:
            spinner.stop()
            telemetry.emit(
                "provider_response",
                turn_id=getattr(self, "_performance_turn_id", None),
                provider=getattr(self.config, "provider", ""),
                model=getattr(self.config, "model", ""),
                request_index=request_index,
                duration_ms=(time.perf_counter() - provider_started_at) * 1000,
                success=False,
                error_type=type(error).__name__,
            )

            error_text = str(error)
            if "401" in error_text or "User not found" in error_text:
                print_error(
                    "API key is invalid or expired. "
                    "Update your key with /config or edit ~/.radsim/.env"
                )
                raise
            if "403" in error_text or "Forbidden" in error_text:
                print_error(
                    "Access denied. Your API key may not have access to this model. "
                    "Try a different model with /config"
                )
                raise

            try:
                self.protection.record_api_error("api_error")
            except CircuitBreakerOpen:
                raise

            try:
                record_error(
                    error_type=type(error).__name__,
                    error_message=str(error),
                    context={"action": "api_call", "provider": self.config.provider},
                )
            except Exception:
                logger.debug("Learning error recording failed during API error handling")

            raise error

    def _handle_response(self, response):
        """Handle API responses, looping through tool rounds until a final answer.

        Iterative rather than recursive so long tool chains cannot hit
        Python's recursion limit; the rate limiter bounds total API calls.
        """
        from .response_validator import validate_response_structure

        while True:
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

            if not tool_uses:
                final_text = "\n".join(text_output)
                self.messages.append({"role": "assistant", "content": final_text})
                self._last_response = final_text
                return final_text

            stop_message = self._process_tool_calls(response, tool_uses, text_output)
            if stop_message is not None:
                return stop_message

            response = self._call_api()

    def _execute_tool_guarded(self, tool_name, tool_input):
        """Run one tool call, converting crashes into error results.

        A handler exception must not abort the turn: the assistant
        message with the tool_use is already in history, so failing to
        append a matching tool_result would corrupt the conversation.
        Protection exceptions still propagate — they are deliberate stops.
        """
        try:
            return self._execute_with_permission(tool_name, tool_input)
        except (RateLimitExceeded, CircuitBreakerOpen, BudgetExceeded):
            raise
        except Exception as error:
            logger.exception("Tool %s crashed during execution", tool_name)
            print_error(f"{tool_name} crashed: {type(error).__name__}: {error}")
            try:
                from .user_hooks import fire_error_hooks

                fire_error_hooks(tool_name, type(error).__name__, str(error))
            except Exception:
                logger.debug("on_error hooks failed during tool crash handling")
            try:
                record_error(
                    error_type=type(error).__name__,
                    error_message=str(error),
                    context={"action": "tool_execution", "tool": tool_name},
                )
            except Exception:
                logger.debug("Learning error recording failed during tool crash handling")
            return {
                "success": False,
                "error": (
                    f"Tool crashed: {type(error).__name__}: {error}. "
                    "The error was caught — continue with a different approach."
                ),
            }

    def _run_independent_reads(self, tool_uses):
        """Execute the round's leading independent read-only calls concurrently.

        Returns (result, duration_ms) by original index for whatever ran ahead
        of time. The serial loop still owns every ordered side effect — output,
        telemetry, learning, and outcome tracking — so parallelism changes when
        a read happens, never the order anything is recorded in.
        """
        plan = plan_parallel_group(
            tool_uses,
            needs_confirmation=self._read_needs_confirmation,
            hooks_present=self._order_sensitive_hooks_present(),
        )
        if not plan.is_parallel:
            return {}

        started_at = time.perf_counter()
        try:
            completed = run_parallel_group(
                self._execute_tool_guarded,
                tool_uses,
                plan,
                interrupted=self._interrupted,
            )
        except (RateLimitExceeded, CircuitBreakerOpen, BudgetExceeded):
            raise
        except Exception:
            logger.exception("Parallel tool round failed; falling back to serial execution")
            return {}

        telemetry = getattr(self, "performance_telemetry", None) or PerformanceTelemetry()
        telemetry.emit(
            "tool_parallel_round",
            turn_id=getattr(self, "_performance_turn_id", None),
            tool_calls=len(tool_uses),
            parallel_group_size=len(plan.indexes),
            parallel_worker_count=plan.worker_count,
            parallel_completed=len(completed),
            duration_ms=(time.perf_counter() - started_at) * 1000,
        )
        return completed

    def _read_needs_confirmation(self, tool_name, tool_input):
        """Return whether a read would prompt, so it is never dispatched blind."""
        try:
            return bool(self._protected_read_targets(tool_name, tool_input))
        except Exception:
            logger.debug("Protected-read screening failed; treating as unsafe", exc_info=True)
            return True

    def _order_sensitive_hooks_present(self):
        """Return whether any tool hook would have its ordering disturbed."""
        try:
            from .hooks import HookType, get_hooks_manager
            from .user_hooks import load_user_hooks

            manager = get_hooks_manager()
            if manager.count(HookType.PRE_TOOL) or manager.count(HookType.POST_TOOL):
                return True
            return any(
                hook.enabled and hook.event in ("pre_tool", "post_tool")
                for hook in load_user_hooks()
            )
        except Exception:
            logger.debug("Hook inspection failed; assuming hooks are present", exc_info=True)
            return True

    def _process_tool_calls(self, response, tool_uses, text_output):
        """Run one round of tool calls.

        Returns:
            str: A final message when the turn must stop (user rejected
                 an action or interrupted).
            None: All tools ran; the caller should request a follow-up.
        """
        self.messages.append({"role": "assistant", "content": response["content"]})

        tool_results = []
        image_blocks = []
        user_rejected = False
        completed = self._run_independent_reads(tool_uses)

        for index, tool_use in enumerate(tool_uses):
            tool_name = tool_use["name"]
            tool_input = tool_use["input"]
            tool_id = tool_use["id"]

            if self._interrupted.is_set():
                user_rejected = True
                if self._task_outcome_tracker is not None:
                    self._task_outcome_tracker.mark_cancelled()

            if user_rejected:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": serialize_tool_result(
                            {
                                "success": False,
                                "error": "STOPPED: User cancelled a previous action this turn. All remaining tool calls skipped.",
                            }
                        ),
                    }
                )
                continue

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
                        "content": serialize_tool_result(
                            {
                                "success": False,
                                "error": f"Tool input was corrupted: {tool_input.get('__parse_error__')}",
                            }
                        ),
                    }
                )
                if self._task_outcome_tracker is not None:
                    self._task_outcome_tracker.record_tool(
                        tool_name,
                        False,
                        error=f"Tool input parse error: {tool_input.get('__parse_error__')}",
                    )
                continue

            self._recover_routed_tool(tool_name)

            tool_start_time = time.perf_counter()
            tool_handle = None

            if self.config.verbose or tool_name in READ_ONLY_TOOLS:
                tool_handle = print_tool_call(tool_name, tool_input, style="compact")

            if index in completed:
                result, duration_ms = completed[index]
            elif tool_name in READ_ONLY_TOOLS:
                spinner = Spinner("Executing...")
                spinner.start()
                try:
                    result = self._execute_tool_guarded(tool_name, tool_input)
                finally:
                    spinner.stop()
                duration_ms = (time.perf_counter() - tool_start_time) * 1000
            else:
                result = self._execute_tool_guarded(tool_name, tool_input)
                duration_ms = (time.perf_counter() - tool_start_time) * 1000
            tool_success = result.get("success", False)
            tool_error = result.get("error", "") if not tool_success else ""

            if not tool_success and "STOPPED" in tool_error:
                user_rejected = True

            if self._task_outcome_tracker is not None:
                self._task_outcome_tracker.record_tool(
                    tool_name,
                    tool_success,
                    duration_ms,
                    tool_error,
                )

            if self.config.verbose or tool_name in READ_ONLY_TOOLS:
                print_tool_result_verbose(tool_handle, tool_name, result, duration_ms)

            try:
                from .agent_config import get_agent_config_manager

                if get_agent_config_manager().is_learning_module_enabled("tool_optimization"):
                    tracker = self._task_outcome_tracker
                    track_tool_execution(
                        tool_name=tool_name,
                        success=tool_success,
                        duration_ms=duration_ms,
                        input_data=tool_input,
                        output_data=result,
                        error=tool_error,
                        task_context=tracker.task_description if tracker else "",
                        task_id=tracker.task_id if tracker else "",
                        model=getattr(self.config, "model", ""),
                        provider=getattr(self.config, "provider", ""),
                    )
                self._current_task_tools.append(tool_name)
            except Exception:
                logger.debug("Learning tool tracking failed during tool execution")

            if self._telegram_mode:
                try:
                    from .telegram import send_telegram_message

                    status = "ok" if tool_success else "fail"
                    send_telegram_message(f"[{status}] {tool_name}")
                except Exception:
                    logger.debug("Telegram tool notification failed", exc_info=True)

            image_block = extract_image_block(result)
            if image_block:
                image_blocks.append(image_block)

            serialized_result = serialize_tool_result(result)
            telemetry = getattr(self, "performance_telemetry", None) or PerformanceTelemetry()
            telemetry.emit(
                "tool_execution",
                turn_id=getattr(self, "_performance_turn_id", None),
                tool_name=tool_name,
                duration_ms=duration_ms,
                success=tool_success,
                result_chars=len(serialized_result),
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": serialized_result,
                }
            )

        # One learning transaction per tool round rather than one per tool call.
        try:
            flush_tool_optimizer()
        except Exception:
            logger.debug("Learning flush failed at tool-round boundary", exc_info=True)

        # tool_result blocks must precede other content in the user message.
        self.messages.append({"role": "user", "content": tool_results + image_blocks})

        if user_rejected:
            if self._task_outcome_tracker is not None:
                self._task_outcome_tracker.user_rejected = True
            return "\n".join(text_output) or "Understood — action cancelled."

        if self._interrupted.is_set():
            if self._task_outcome_tracker is not None:
                self._task_outcome_tracker.mark_cancelled()
            return "\n".join(text_output) or "Cancelled."

        return None
