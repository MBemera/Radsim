"""Multi-provider API wrapper for RadSim Agent."""

import json
import logging
import random
import time
from abc import ABC, abstractmethod
from functools import wraps
from typing import Any

from .performance import emit_active_performance_event
from .prompt_cache import (
    SystemCachePlan,
    mark_conversation_breakpoint,
    plan_system_cache,
)
from .request_options import RequestOptions
from .tool_router import estimate_schema_tokens
from .tool_schema import canonicalize_tool_schemas
from .usage import merge_usage_snapshots, normalize_usage

# Production Readiness: Explicit timeouts prevent hung connections
# Never use default infinite timeouts in production
DEFAULT_TIMEOUT_SECONDS = 120  # 2 minutes max for LLM responses
DEFAULT_CONNECT_TIMEOUT = 10  # 10 seconds to establish connection

# Production Readiness: Exponential backoff configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 60.0  # seconds
DEFAULT_EXPONENTIAL_BASE = 2

# Output ceiling used when a caller asks for no specific limit. Anthropic
# requires the field, so this is the value the primary agent has always sent;
# the OpenAI-compatible clients omit the field entirely in that case.
DEFAULT_MAX_OUTPUT_TOKENS = 16000

logger = logging.getLogger(__name__)


def _report_prompt_cache_plan(plan: SystemCachePlan, *, provider: str, model: str) -> None:
    """Record how one request's cache breakpoints were placed."""
    emit_active_performance_event(
        "prompt_cache",
        provider=provider,
        model=model,
        prompt_cache_applied=plan.is_cached,
        prompt_cache_prefix_tokens=plan.prefix_tokens,
        prompt_cache_minimum_tokens=plan.minimum_tokens,
        prompt_cache_skipped_reason=plan.skipped_reason,
    )


class RetryableError(Exception):
    """Wrapper for errors that should trigger a retry."""

    def __init__(self, original_error, is_rate_limit=False):
        self.original_error = original_error
        self.is_rate_limit = is_rate_limit
        super().__init__(str(original_error))


def calculate_backoff_delay(
    attempt: int,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    exponential_base: int = DEFAULT_EXPONENTIAL_BASE,
    jitter: bool = True,
) -> float:
    """Calculate delay for exponential backoff with optional jitter.

    Args:
        attempt: Current attempt number (0-indexed)
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap in seconds
        exponential_base: Base for exponential calculation
        jitter: Add random jitter to prevent thundering herd

    Returns:
        Delay in seconds before next retry
    """
    delay = min(base_delay * (exponential_base ** attempt), max_delay)

    if jitter:
        # Add 0-50% random jitter
        delay = delay * (1 + random.random() * 0.5)

    return delay


def with_retry(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    retryable_exceptions: tuple = None,
):
    """Decorator for exponential backoff retry logic.

    Production Readiness: Implements exponential backoff with jitter
    to handle transient failures and rate limits gracefully.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries
        max_delay: Maximum delay cap
        retryable_exceptions: Tuple of exception types to retry on
    """
    if retryable_exceptions is None:
        # Default retryable errors - connection issues and rate limits
        retryable_exceptions = (
            ConnectionError,
            TimeoutError,
            RetryableError,
        )

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    return _attach_retry_count(result, attempt)

                except retryable_exceptions as e:
                    last_exception = e
                    is_rate_limit = (
                        isinstance(e, RetryableError) and e.is_rate_limit
                    )

                    if attempt < max_retries:
                        delay = calculate_backoff_delay(
                            attempt,
                            base_delay=base_delay,
                            max_delay=max_delay,
                        )

                        # Rate limits get longer delays
                        if is_rate_limit:
                            delay = delay * 2

                        logger.warning(
                            f"Retry {attempt + 1}/{max_retries} after {delay:.1f}s: {e}"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"All {max_retries} retries exhausted: {e}")
                        _attach_error_retry_count(e, attempt)
                        raise

                except Exception:
                    # Non-retryable errors propagate immediately
                    raise

            # Should not reach here, but safety fallback
            if last_exception:
                raise last_exception

        return wrapper

    return decorator


def _attach_retry_count(result: Any, retry_attempts: int) -> Any:
    """Attach retry evidence to normalized API responses when possible."""
    if not isinstance(result, dict):
        return result
    usage = result.get("usage")
    if isinstance(usage, dict):
        usage["retry_attempts"] = retry_attempts
    return result


def _attach_error_retry_count(error: Exception, retry_attempts: int) -> None:
    """Preserve exhausted retry evidence without replacing the original error."""
    try:
        error.retry_attempts = retry_attempts
    except (AttributeError, TypeError):
        pass


def is_retryable_error(error) -> tuple[bool, bool]:
    """Check if an error is retryable and if it's a rate limit.

    Returns:
        Tuple of (is_retryable, is_rate_limit)
    """
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()

    # Rate limit indicators
    rate_limit_indicators = [
        "rate_limit",
        "rate limit",
        "too many requests",
        "429",
        "quota",
        "throttl",
    ]

    is_rate_limit = any(indicator in error_str for indicator in rate_limit_indicators)

    # Retryable error indicators
    retryable_indicators = [
        "timeout",
        "connection",
        "temporary",
        "unavailable",
        "503",
        "502",
        "500",
        "overloaded",
        "capacity",
    ]

    is_retryable = (
        is_rate_limit
        or any(indicator in error_str for indicator in retryable_indicators)
        or any(indicator in error_type for indicator in ["timeout", "connection"])
    )

    return is_retryable, is_rate_limit


def _parse_tool_arguments(raw_arguments, tool_name):
    """Parse a provider tool-call argument string into a dict.

    Providers emit an empty string for some zero-argument calls, and a model
    can produce malformed JSON. Returning a marked error dict instead of
    raising keeps one bad tool call from aborting the whole turn; the agent
    surfaces the parse error back to the model as the tool result.
    """
    if not raw_arguments or not raw_arguments.strip():
        return {}

    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError as error:
        logger.error(
            f"Tool argument JSON parse failed for {tool_name or 'unknown'}: "
            f"{error}. Raw: {raw_arguments[:200]}"
        )
        return {"__parse_error__": str(error), "__raw__": raw_arguments[:500]}

    if not isinstance(parsed, dict):
        logger.error(
            f"Tool arguments for {tool_name or 'unknown'} are not a JSON "
            f"object. Raw: {raw_arguments[:200]}"
        )
        return {
            "__parse_error__": "tool arguments must be a JSON object",
            "__raw__": raw_arguments[:500],
        }

    return parsed


def _block_to_openai_part(block):
    """Convert one Anthropic-style content block to an OpenAI content part.

    Returns None for block types with no OpenAI equivalent.
    """
    if block.get("type") == "text":
        return {"type": "text", "text": block.get("text", "")}
    if block.get("type") == "image":
        source = block.get("source", {})
        data_uri = f"data:{source.get('media_type', 'image/png')};base64,{source.get('data', '')}"
        return {"type": "image_url", "image_url": {"url": data_uri}}
    return None


class BaseAPIClient(ABC):
    """Base class for API clients."""

    @abstractmethod
    def chat(
        self,
        messages,
        system_prompt=None,
        tools=None,
        max_tokens=None,
        request_options=None,
    ):
        """Send a chat request and return the response.

        Args:
            max_tokens: Optional output ceiling for this one request. None
                keeps each provider's existing default, so the primary agent
                sends exactly what it always has.
        """
        pass

    def stream_chat(
        self,
        messages,
        system_prompt=None,
        tools=None,
        max_tokens=None,
        request_options=None,
    ):
        """Stream a chat request, yielding deltas and final response.

        Yields:
            {"type": "text_delta", "text": str}
            {"type": "final_response", "response": dict}
        """
        # Default implementation falls back to non-streaming
        response = self.chat(
            messages,
            system_prompt,
            tools,
            max_tokens,
            request_options=request_options,
        )

        for block in response["content"]:
            if block["type"] == "text":
                yield {"type": "text_delta", "text": block["text"]}

        yield {"type": "final_response", "response": response}

    def _supported_request_parameters(self) -> frozenset[str]:
        """Return conservative request capabilities for this client."""
        return frozenset()

    def request_options_snapshot(self, options: RequestOptions) -> dict[str, Any]:
        """Return the immutable requested-to-applied capability resolution."""
        supported = self._supported_request_parameters()
        return {
            "supported_parameters": sorted(supported),
            "applied": options.for_supported(supported),
        }


class ClaudeClient(BaseAPIClient):
    """Anthropic Claude API client."""

    PROVIDER_NAME = "anthropic"

    def __init__(self, api_key, model="claude-opus-4-8", timeout=DEFAULT_TIMEOUT_SECONDS):
        try:
            import anthropic
            from anthropic import Timeout
        except ImportError:
            raise ImportError("Install anthropic: pip install anthropic") from None

        # Production Readiness: Explicit timeout configuration
        self.client = anthropic.Anthropic(
            api_key=api_key,
            timeout=Timeout(timeout, connect=DEFAULT_CONNECT_TIMEOUT),
        )
        self.model = model

    def _build_request_kwargs(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        *,
        stream: bool = False,
        max_tokens: int | None = None,
        request_options: RequestOptions | None = None,
    ) -> dict[str, Any]:
        """Build one Claude request without performing network I/O."""
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens or DEFAULT_MAX_OUTPUT_TOKENS,
            "messages": messages,
        }
        if stream:
            kwargs["stream"] = True
        if tools:
            kwargs["tools"] = canonicalize_tool_schemas(tools)
        if system_prompt:
            plan = plan_system_cache(
                system_prompt,
                model=self.model,
                tool_schema_tokens=estimate_schema_tokens(kwargs.get("tools", [])),
            )
            kwargs["system"] = plan.blocks if plan.is_cached else system_prompt
            if plan.is_cached:
                kwargs["messages"] = mark_conversation_breakpoint(messages)
            _report_prompt_cache_plan(plan, provider=self.PROVIDER_NAME, model=self.model)
        if request_options is not None:
            kwargs.update(request_options.for_supported(self._supported_request_parameters()))
        return kwargs

    def _supported_request_parameters(self) -> frozenset[str]:
        return frozenset({"temperature", "top_p"})

    def chat(
        self,
        messages,
        system_prompt=None,
        tools=None,
        max_tokens=None,
        request_options=None,
    ):
        """Send a chat request to Claude with retry logic."""
        kwargs = self._build_request_kwargs(
            messages,
            system_prompt,
            tools,
            max_tokens=max_tokens,
            request_options=request_options,
        )
        return self._chat_with_retry(**kwargs)

    @with_retry(max_retries=DEFAULT_MAX_RETRIES)
    def _chat_with_retry(self, **kwargs):
        """Internal method with retry decorator."""
        try:
            started_at = time.perf_counter()
            response = self.client.messages.create(**kwargs)
            latency_ms = (time.perf_counter() - started_at) * 1000
            return self._parse_response(response, latency_ms=latency_ms)
        except Exception as e:
            is_retryable, is_rate_limit = is_retryable_error(e)
            if is_retryable:
                raise RetryableError(e, is_rate_limit=is_rate_limit) from e
            raise

    def stream_chat(
        self,
        messages,
        system_prompt=None,
        tools=None,
        max_tokens=None,
        request_options=None,
    ):
        """Stream a chat request to Claude."""
        kwargs = self._build_request_kwargs(
            messages,
            system_prompt,
            tools,
            stream=True,
            max_tokens=max_tokens,
            request_options=request_options,
        )
        final_content = []
        current_tool_use = None
        usage = normalize_usage(None)
        stop_reason = "end_turn"
        started_at = time.perf_counter()

        with self.client.messages.create(**kwargs) as stream:
            for event in stream:
                if event.type == "message_start":
                    snapshot = normalize_usage(
                        event.message.usage,
                        provider="anthropic",
                        response=event.message,
                    )
                    usage = merge_usage_snapshots(usage, snapshot)
                elif event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        current_tool_use = {
                            "type": "tool_use",
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                            "input": "",  # Will be built from json chunks
                        }
                        final_content.append(current_tool_use)
                    elif event.content_block.type == "text":
                        final_content.append({"type": "text", "text": ""})

                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        text = event.delta.text
                        final_content[-1]["text"] += text
                        yield {"type": "text_delta", "text": text}
                    elif event.delta.type == "input_json_delta":
                        if current_tool_use:
                            current_tool_use["input"] += event.delta.partial_json

                elif event.type == "content_block_stop":
                    if current_tool_use:
                        current_tool_use["input"] = _parse_tool_arguments(
                            current_tool_use["input"], current_tool_use.get("name")
                        )
                        current_tool_use = None

                elif event.type == "message_delta":
                    snapshot = normalize_usage(event.usage, provider="anthropic", response=event)
                    usage = merge_usage_snapshots(usage, snapshot)
                    if getattr(event.delta, "stop_reason", None):
                        stop_reason = event.delta.stop_reason

        latency = normalize_usage(None, latency_ms=(time.perf_counter() - started_at) * 1000)
        usage = merge_usage_snapshots(usage, latency)

        response = {
            "content": final_content,
            "stop_reason": stop_reason,
            "usage": usage,
        }
        yield {"type": "final_response", "response": response}

    def _parse_response(self, response, latency_ms=None):
        """Parse Claude's response into a standard format."""
        result = {
            "content": [],
            "stop_reason": response.stop_reason,
            "usage": normalize_usage(
                response.usage,
                provider="anthropic",
                response=response,
                latency_ms=latency_ms,
            ),
        }

        for block in response.content:
            if block.type == "text":
                result["content"].append(
                    {
                        "type": "text",
                        "text": block.text,
                    }
                )
            elif block.type == "tool_use":
                result["content"].append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )

        return result


class OpenAIClient(BaseAPIClient):
    """OpenAI API client."""

    PROVIDER_NAME = "openai"

    # OpenAI's chat completions API rejects `max_tokens` on its reasoning
    # models and wants `max_completion_tokens`, which counts reasoning tokens
    # as well as visible output.
    MAX_OUTPUT_TOKENS_PARAM = "max_completion_tokens"

    def __init__(
        self,
        api_key,
        model="gpt-5.2",
        timeout=DEFAULT_TIMEOUT_SECONDS,
        reasoning_effort=None,
    ):
        try:
            import openai
        except ImportError:
            raise ImportError("Install openai: pip install openai") from None

        # Production Readiness: Explicit timeout configuration
        self.client = openai.OpenAI(
            api_key=api_key,
            timeout=timeout,
        )
        self.model = model
        self.reasoning_effort = reasoning_effort

    def _apply_reasoning(self, kwargs):
        """Attach reasoning_effort to a chat completion request when set."""
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        return kwargs

    def _build_messages(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        """Convert internal messages into the OpenAI chat format."""
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})

        for message in messages:
            formatted = self._format_message(message)
            if isinstance(formatted, list):
                formatted_messages.extend(formatted)
            else:
                formatted_messages.append(formatted)
        return formatted_messages

    def _build_request_kwargs(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        *,
        stream: bool = False,
        max_tokens: int | None = None,
        request_options: RequestOptions | None = None,
    ) -> dict[str, Any]:
        """Build one OpenAI request without performing network I/O."""
        kwargs = {"model": self.model, "messages": self._build_messages(messages, system_prompt)}
        if stream:
            kwargs.update(stream=True, stream_options={"include_usage": True})
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
        if max_tokens:
            kwargs[self.MAX_OUTPUT_TOKENS_PARAM] = max_tokens
        if request_options is not None:
            kwargs.update(request_options.for_supported(self._supported_request_parameters()))
        return self._apply_reasoning(kwargs)

    def _supported_request_parameters(self) -> frozenset[str]:
        """Return conservative model-specific request support."""
        return frozenset()

    def chat(
        self,
        messages,
        system_prompt=None,
        tools=None,
        max_tokens=None,
        request_options=None,
    ):
        """Send a chat request to OpenAI with retry logic."""
        kwargs = self._build_request_kwargs(
            messages,
            system_prompt,
            tools,
            max_tokens=max_tokens,
            request_options=request_options,
        )
        return self._chat_with_retry(**kwargs)

    @with_retry(max_retries=DEFAULT_MAX_RETRIES)
    def _chat_with_retry(self, **kwargs):
        """Internal method with retry decorator."""
        try:
            started_at = time.perf_counter()
            response = self.client.chat.completions.create(**kwargs)
            latency_ms = (time.perf_counter() - started_at) * 1000
            return self._parse_response(response, latency_ms=latency_ms)
        except Exception as e:
            is_retryable, is_rate_limit = is_retryable_error(e)
            if is_retryable:
                raise RetryableError(e, is_rate_limit=is_rate_limit) from e
            raise

    def stream_chat(
        self,
        messages,
        system_prompt=None,
        tools=None,
        max_tokens=None,
        request_options=None,
    ):
        """Stream a chat request to OpenAI."""
        kwargs = self._build_request_kwargs(
            messages,
            system_prompt,
            tools,
            stream=True,
            max_tokens=max_tokens,
            request_options=request_options,
        )
        started_at = time.perf_counter()
        stream = self.client.chat.completions.create(**kwargs)

        final_text = ""
        tool_calls_map = {}  # index -> tool_call
        usage = normalize_usage(None)
        finish_reason = "stop"

        for chunk in stream:
            # Usage may arrive on a dedicated final chunk (OpenAI) or on a
            # chunk that also carries choices (some OpenRouter models), so
            # record it and keep processing the same chunk.
            if hasattr(chunk, "usage") and chunk.usage:
                snapshot = normalize_usage(
                    chunk.usage,
                    provider=self.PROVIDER_NAME,
                    response=chunk,
                )
                usage = merge_usage_snapshots(usage, snapshot)

            if not chunk.choices:
                continue

            # The final chunk carries why generation stopped. Keeping it means
            # a response cut off at the output ceiling is reported as such
            # instead of reading as a complete answer.
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

            delta = chunk.choices[0].delta

            if delta.content:
                text = delta.content
                final_text += text
                yield {"type": "text_delta", "text": text}

            if delta.tool_calls:
                for tool_call_chunk in delta.tool_calls:
                    idx = tool_call_chunk.index
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {
                            "id": tool_call_chunk.id,
                            "name": tool_call_chunk.function.name,
                            "arguments": "",
                        }

                    if tool_call_chunk.function.name:
                        tool_calls_map[idx]["name"] = tool_call_chunk.function.name
                    if tool_call_chunk.id:
                        tool_calls_map[idx]["id"] = tool_call_chunk.id
                    if tool_call_chunk.function.arguments:
                        tool_calls_map[idx]["arguments"] += tool_call_chunk.function.arguments

        content = []
        if final_text:
            content.append({"type": "text", "text": final_text})

        for idx in sorted(tool_calls_map.keys()):
            tc = tool_calls_map[idx]
            args = _parse_tool_arguments(tc["arguments"], tc.get("name"))

            content.append(
                {
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": args,
                }
            )

        latency = normalize_usage(None, latency_ms=(time.perf_counter() - started_at) * 1000)
        usage = merge_usage_snapshots(usage, latency)
        response = {"content": content, "stop_reason": finish_reason, "usage": usage}
        yield {"type": "final_response", "response": response}

    def _format_message(self, msg):
        """Format a message for OpenAI."""
        if msg["role"] == "user":
            if isinstance(msg["content"], str):
                return {"role": "user", "content": msg["content"]}
            # Handle tool results - convert from Claude format to OpenAI format
            # Claude: {"role": "user", "content": [{"type": "tool_result", "tool_use_id": ..., "content": ...}]}
            # OpenAI: [{"role": "tool", "tool_call_id": ..., "content": ...}]
            if (
                isinstance(msg["content"], list)
                and msg["content"]
                and msg["content"][0].get("type") == "tool_result"
            ):
                # Tool messages first; any trailing image/text blocks (e.g.
                # from read_image) become a follow-up user message, because
                # OpenAI tool messages cannot carry images.
                tool_messages = []
                extra_parts = []
                for item in msg["content"]:
                    if item.get("type") == "tool_result":
                        tool_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": item["tool_use_id"],
                                "content": item["content"]
                                if isinstance(item["content"], str)
                                else json.dumps(item["content"]),
                            }
                        )
                    else:
                        part = _block_to_openai_part(item)
                        if part:
                            extra_parts.append(part)
                if extra_parts:
                    tool_messages.append({"role": "user", "content": extra_parts})
                return tool_messages

            # User messages built from Anthropic-style blocks (text/image).
            parts = [_block_to_openai_part(item) for item in msg["content"]]
            parts = [part for part in parts if part]
            if parts:
                return {"role": "user", "content": parts}
            return {"role": "user", "content": json.dumps(msg["content"])}

        # Handle assistant messages with tool_use content blocks
        if msg["role"] == "assistant":
            if isinstance(msg["content"], str):
                return {"role": "assistant", "content": msg["content"]}

            # Convert Claude's tool_use format to OpenAI's tool_calls format
            if isinstance(msg["content"], list):
                text_content = ""
                tool_calls = []

                for block in msg["content"]:
                    if block.get("type") == "text":
                        text_content += block.get("text", "")
                    elif block.get("type") == "tool_use":
                        tool_calls.append({
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block["input"]),
                            },
                        })

                result = {"role": "assistant", "content": text_content or None}
                if tool_calls:
                    result["tool_calls"] = tool_calls
                return result

        return msg

    def _convert_tools(self, tools):
        """Convert tool definitions to OpenAI format."""
        openai_tools = []
        for tool in canonicalize_tool_schemas(tools):
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"],
                    },
                }
            )
        return openai_tools

    def _parse_response(self, response, latency_ms=None):
        """Parse OpenAI's response into a standard format."""
        message = response.choices[0].message
        result = {
            "content": [],
            "stop_reason": response.choices[0].finish_reason,
            "usage": normalize_usage(
                response.usage,
                provider=self.PROVIDER_NAME,
                response=response,
                latency_ms=latency_ms,
            ),
        }

        if message.content:
            result["content"].append(
                {
                    "type": "text",
                    "text": message.content,
                }
            )

        if message.tool_calls:
            for tool_call in message.tool_calls:
                result["content"].append(
                    {
                        "type": "tool_use",
                        "id": tool_call.id,
                        "name": tool_call.function.name,
                        "input": _parse_tool_arguments(
                            tool_call.function.arguments, tool_call.function.name
                        ),
                    }
                )

        return result


class OpenRouterClient(OpenAIClient):
    """OpenRouter API client (OpenAI-compatible).

    OpenRouter requires:
    - API key in Authorization header (even for free models)
    - HTTP-Referer header for identification
    - X-Title header (optional, for analytics)
    """

    # OpenRouter normalises `max_tokens` across every upstream provider it
    # routes to, so it is the portable field here.
    MAX_OUTPUT_TOKENS_PARAM = "max_tokens"
    PROVIDER_NAME = "openrouter"

    def __init__(
        self,
        api_key,
        model="qwen/qwen3-coder:free",
        timeout=DEFAULT_TIMEOUT_SECONDS,
        reasoning_effort=None,
    ):
        try:
            import openai
        except ImportError:
            raise ImportError("Install openai: pip install openai") from None

        # Production Readiness: Explicit timeout configuration
        # OpenRouter requires these headers for all requests
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=timeout,
            default_headers={
                "HTTP-Referer": "https://github.com/MBemera/Radsim",
                "X-Title": "RadSim Agent",
            },
        )
        self.model = model
        self.reasoning_effort = reasoning_effort

    def _apply_reasoning(self, kwargs):
        """OpenRouter exposes a unified reasoning param that maps across providers."""
        if not self.reasoning_effort:
            return kwargs
        from .openrouter_models import model_supports_reasoning
        if not model_supports_reasoning(self.model):
            return kwargs
        kwargs["extra_body"] = {
            **kwargs.get("extra_body", {}),
            "reasoning": {"effort": self.reasoning_effort},
        }
        return kwargs

    def _build_messages(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        """Convert messages, caching the system prefix on Anthropic models.

        OpenRouter forwards `cache_control` to Anthropic upstreams, which need
        the explicit breakpoint. Only the system message is marked: conversation
        block placement differs by upstream provider, so RadSim does not guess.
        """
        formatted_messages = super()._build_messages(messages, system_prompt)
        if not system_prompt or not formatted_messages:
            return formatted_messages

        plan = plan_system_cache(system_prompt, model=self.model)
        _report_prompt_cache_plan(plan, provider=self.PROVIDER_NAME, model=self.model)
        if not plan.is_cached:
            return formatted_messages

        system_message = {**formatted_messages[0], "content": plan.blocks}
        return [system_message] + formatted_messages[1:]

    def _supported_request_parameters(self) -> frozenset[str]:
        """Cache validated model capability metadata for this client."""
        cached = getattr(self, "_request_parameter_support", None)
        if cached is not None:
            return cached
        from .openrouter_models import get_model_request_parameters

        supported = frozenset(get_model_request_parameters(self.model))
        self._request_parameter_support = supported
        return supported


def create_client(
    provider,
    api_key,
    model=None,
    reasoning_effort=None,
    timeout=DEFAULT_TIMEOUT_SECONDS,
):
    """Create an API client for the specified provider."""
    clients = {
        "claude": ClaudeClient,
        "openai": OpenAIClient,
        "openrouter": OpenRouterClient,
    }

    if provider not in clients:
        raise ValueError(f"Unknown provider: {provider}")

    client_class = clients[provider]
    kwargs = {"timeout": timeout}
    if model:
        kwargs["model"] = model
    if reasoning_effort and provider in ("openai", "openrouter"):
        kwargs["reasoning_effort"] = reasoning_effort
    return client_class(api_key, **kwargs)
