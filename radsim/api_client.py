"""Multi-provider API wrapper for RadSim Agent."""

import json
import logging
import random
import time
from abc import ABC, abstractmethod
from functools import wraps

# Production Readiness: Explicit timeouts prevent hung connections
# Never use default infinite timeouts in production
DEFAULT_TIMEOUT_SECONDS = 120  # 2 minutes max for LLM responses
DEFAULT_CONNECT_TIMEOUT = 10  # 10 seconds to establish connection

# Production Readiness: Exponential backoff configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 60.0  # seconds
DEFAULT_EXPONENTIAL_BASE = 2

logger = logging.getLogger(__name__)


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
                    return func(*args, **kwargs)

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
                        raise

                except Exception:
                    # Non-retryable errors propagate immediately
                    raise

            # Should not reach here, but safety fallback
            if last_exception:
                raise last_exception

        return wrapper

    return decorator


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


class BaseAPIClient(ABC):
    """Base class for API clients."""

    @abstractmethod
    def chat(self, messages, tools=None):
        """Send a chat request and return the response."""
        pass

    def stream_chat(self, messages, system_prompt=None, tools=None):
        """Stream a chat request, yielding deltas and final response.

        Yields:
            {"type": "text_delta", "text": str}
            {"type": "final_response", "response": dict}
        """
        # Default implementation falls back to non-streaming
        response = self.chat(messages, system_prompt, tools)

        for block in response["content"]:
            if block["type"] == "text":
                yield {"type": "text_delta", "text": block["text"]}

        yield {"type": "final_response", "response": response}


class ClaudeClient(BaseAPIClient):
    """Anthropic Claude API client."""

    def __init__(self, api_key, model="claude-sonnet-4-5-20251124", timeout=DEFAULT_TIMEOUT_SECONDS):
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

    def chat(self, messages, system_prompt=None, tools=None):
        """Send a chat request to Claude with retry logic."""
        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": messages,
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        if tools:
            kwargs["tools"] = tools

        return self._chat_with_retry(**kwargs)

    @with_retry(max_retries=DEFAULT_MAX_RETRIES)
    def _chat_with_retry(self, **kwargs):
        """Internal method with retry decorator."""
        try:
            response = self.client.messages.create(**kwargs)
            return self._parse_response(response)
        except Exception as e:
            is_retryable, is_rate_limit = is_retryable_error(e)
            if is_retryable:
                raise RetryableError(e, is_rate_limit=is_rate_limit) from e
            raise

    def stream_chat(self, messages, system_prompt=None, tools=None):
        """Stream a chat request to Claude."""
        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": messages,
            "stream": True,
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        if tools:
            kwargs["tools"] = tools

        final_content = []
        current_tool_use = None
        input_tokens = 0
        output_tokens = 0

        with self.client.messages.create(**kwargs) as stream:
            for event in stream:
                if event.type == "message_start":
                    input_tokens = event.message.usage.input_tokens
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
                        # Parse the collected JSON string
                        try:
                            current_tool_use["input"] = json.loads(current_tool_use["input"])
                        except json.JSONDecodeError as e:
                            # Log error and preserve context for upstream handling
                            import logging
                            raw_preview = current_tool_use["input"][:200] if current_tool_use["input"] else "(empty)"
                            logging.error(f"Claude tool input parse failed for {current_tool_use.get('name', 'unknown')}: {e}. Raw: {raw_preview}")
                            current_tool_use["input"] = {
                                "__parse_error__": str(e),
                                "__raw__": current_tool_use["input"][:500] if current_tool_use["input"] else ""
                            }
                        current_tool_use = None

                elif event.type == "message_delta":
                    output_tokens = event.usage.output_tokens

        response = {
            "content": final_content,
            "stop_reason": "end_turn",  # Simplified
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        }
        yield {"type": "final_response", "response": response}

    def _parse_response(self, response):
        """Parse Claude's response into a standard format."""
        result = {
            "content": [],
            "stop_reason": response.stop_reason,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
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

    def __init__(self, api_key, model="gpt-5.2", timeout=DEFAULT_TIMEOUT_SECONDS):
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

    def chat(self, messages, system_prompt=None, tools=None):
        """Send a chat request to OpenAI with retry logic."""
        formatted_messages = []

        if system_prompt:
            formatted_messages.append(
                {
                    "role": "system",
                    "content": system_prompt,
                }
            )

        for msg in messages:
            formatted = self._format_message(msg)
            # Handle tool results which return a list of messages
            if isinstance(formatted, list):
                formatted_messages.extend(formatted)
            else:
                formatted_messages.append(formatted)

        kwargs = {
            "model": self.model,
            "messages": formatted_messages,
        }

        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        return self._chat_with_retry(**kwargs)

    @with_retry(max_retries=DEFAULT_MAX_RETRIES)
    def _chat_with_retry(self, **kwargs):
        """Internal method with retry decorator."""
        try:
            response = self.client.chat.completions.create(**kwargs)
            return self._parse_response(response)
        except Exception as e:
            is_retryable, is_rate_limit = is_retryable_error(e)
            if is_retryable:
                raise RetryableError(e, is_rate_limit=is_rate_limit) from e
            raise

    def stream_chat(self, messages, system_prompt=None, tools=None):
        """Stream a chat request to OpenAI."""
        formatted_messages = []

        if system_prompt:
            formatted_messages.append(
                {
                    "role": "system",
                    "content": system_prompt,
                }
            )

        for msg in messages:
            formatted = self._format_message(msg)
            # Handle tool results which return a list of messages
            if isinstance(formatted, list):
                formatted_messages.extend(formatted)
            else:
                formatted_messages.append(formatted)

        kwargs = {
            "model": self.model,
            "messages": formatted_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        stream = self.client.chat.completions.create(**kwargs)

        final_text = ""
        tool_calls_map = {}  # index -> tool_call
        usage = {"input_tokens": 0, "output_tokens": 0}

        for chunk in stream:
            # Check for usage
            if hasattr(chunk, "usage") and chunk.usage:
                usage["input_tokens"] = chunk.usage.prompt_tokens
                usage["output_tokens"] = chunk.usage.completion_tokens
                continue  # Usage chunk might not have choices

            if not chunk.choices:
                continue

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
            try:
                args = json.loads(tc["arguments"])
            except json.JSONDecodeError as e:
                import logging
                raw_preview = tc["arguments"][:200] if tc["arguments"] else "(empty)"
                logging.error(f"Tool call JSON parse failed for {tc.get('name', 'unknown')}: {e}. Raw: {raw_preview}")
                args = {"__parse_error__": str(e), "__raw__": tc["arguments"][:500] if tc["arguments"] else ""}

            content.append(
                {
                    "type": "tool_use",
                    "id": tc["id"],
                    "name": tc["name"],
                    "input": args,
                }
            )

        response = {"content": content, "stop_reason": "stop", "usage": usage}
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
                # Return list of tool messages (will be flattened by caller)
                return [
                    {
                        "role": "tool",
                        "tool_call_id": item["tool_use_id"],
                        "content": item["content"]
                        if isinstance(item["content"], str)
                        else json.dumps(item["content"]),
                    }
                    for item in msg["content"]
                ]
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
        for tool in tools:
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

    def _parse_response(self, response):
        """Parse OpenAI's response into a standard format."""
        message = response.choices[0].message
        result = {
            "content": [],
            "stop_reason": response.choices[0].finish_reason,
            "usage": {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            },
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
                        "input": json.loads(tool_call.function.arguments),
                    }
                )

        return result


class GeminiClient(BaseAPIClient):
    """Google Gemini API client."""

    def __init__(self, api_key, model="gemini-3-flash", timeout=DEFAULT_TIMEOUT_SECONDS):
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ImportError("Install google-genai: pip install google-genai") from None

        # Production Readiness: Explicit timeout configuration
        # Gemini client uses httpx under the hood
        self.timeout = timeout
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=timeout),
        )
        self.model = model
        self.history = []
        self._genai_types = types

    def _convert_tools_to_gemini(self, tools):
        """Convert tool definitions to Gemini format."""
        if not tools:
            return None

        gemini_tools = []
        for tool in tools:
            # Convert JSON Schema to Gemini function declaration
            function_decl = {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool.get("input_schema", {}),
            }
            gemini_tools.append(function_decl)

        return [self._genai_types.Tool(function_declarations=gemini_tools)]

    def chat(self, messages, system_prompt=None, tools=None):
        """Send a chat request to Gemini with retry logic."""
        # Build contents from messages
        contents = []

        if system_prompt:
            contents.append(
                {"role": "user", "parts": [{"text": f"System instructions: {system_prompt}"}]}
            )
            contents.append(
                {
                    "role": "model",
                    "parts": [{"text": "Understood. I will follow these instructions."}],
                }
            )

        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            content = msg["content"]

            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                # Handle tool results or complex content
                text = content[0].get("text", str(content)) if content else ""
            else:
                text = str(content)

            contents.append({"role": role, "parts": [{"text": text}]})

        # Build request kwargs
        kwargs = {
            "model": self.model,
            "contents": contents,
        }

        # Add tools if provided
        gemini_tools = self._convert_tools_to_gemini(tools)
        if gemini_tools:
            kwargs["config"] = self._genai_types.GenerateContentConfig(tools=gemini_tools)

        return self._chat_with_retry(kwargs, tools is not None)

    @with_retry(max_retries=DEFAULT_MAX_RETRIES)
    def _chat_with_retry(self, kwargs, has_tools):
        """Internal method with retry decorator."""
        try:
            response = self.client.models.generate_content(**kwargs)
            return self._parse_response(response, has_tools)
        except Exception as e:
            is_retryable, is_rate_limit = is_retryable_error(e)
            if is_retryable:
                raise RetryableError(e, is_rate_limit=is_rate_limit) from e
            raise

    def stream_chat(self, messages, system_prompt=None, tools=None):
        """Stream a chat request to Gemini."""
        # Build contents (same as chat)
        contents = []

        if system_prompt:
            contents.append(
                {"role": "user", "parts": [{"text": f"System instructions: {system_prompt}"}]}
            )
            contents.append(
                {
                    "role": "model",
                    "parts": [{"text": "Understood. I will follow these instructions."}],
                }
            )

        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            content = msg["content"]
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = content[0].get("text", str(content)) if content else ""
            else:
                text = str(content)
            contents.append({"role": role, "parts": [{"text": text}]})

        # Build request kwargs
        kwargs = {
            "model": self.model,
            "contents": contents,
        }

        # Add tools if provided
        gemini_tools = self._convert_tools_to_gemini(tools)
        if gemini_tools:
            kwargs["config"] = self._genai_types.GenerateContentConfig(tools=gemini_tools)

        # Gemini stream
        response_stream = self.client.models.generate_content_stream(**kwargs)

        full_text = ""
        tool_calls = []
        usage = {"input_tokens": 0, "output_tokens": 0}

        for chunk in response_stream:
            if hasattr(chunk, "text") and chunk.text:
                text = chunk.text
                full_text += text
                yield {"type": "text_delta", "text": text}

            # Check for function calls in streaming response
            if hasattr(chunk, "candidates") and chunk.candidates:
                candidate = chunk.candidates[0]
                if hasattr(candidate, "content") and candidate.content:
                    for part in candidate.content.parts:
                        if hasattr(part, "function_call") and part.function_call:
                            fc = part.function_call
                            tool_calls.append({
                                "type": "tool_use",
                                "id": f"gemini_{fc.name}_{id(fc)}",
                                "name": fc.name,
                                "input": dict(fc.args) if fc.args else {},
                            })

            if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                usage["input_tokens"] = getattr(chunk.usage_metadata, "prompt_token_count", 0) or 0
                usage["output_tokens"] = getattr(chunk.usage_metadata, "candidates_token_count", 0) or 0

        # Build final content
        content = []
        if full_text:
            content.append({"type": "text", "text": full_text})
        content.extend(tool_calls)

        response = {
            "content": content,
            "stop_reason": "end_turn",
            "usage": usage,
        }
        yield {"type": "final_response", "response": response}

    def _parse_response(self, response, has_tools=False):
        """Parse Gemini response, including function calls if tools enabled."""
        content = []

        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
        }

        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage["input_tokens"] = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            usage["output_tokens"] = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

        # Check for function calls in the response
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, "content") and candidate.content:
                for part in candidate.content.parts:
                    # Handle text parts
                    if hasattr(part, "text") and part.text:
                        content.append({"type": "text", "text": part.text})

                    # Handle function call parts
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        content.append({
                            "type": "tool_use",
                            "id": f"gemini_{fc.name}_{id(fc)}",
                            "name": fc.name,
                            "input": dict(fc.args) if fc.args else {},
                        })

        # Fallback to simple text extraction if no structured content
        if not content:
            text = response.text if hasattr(response, "text") else str(response)
            content.append({"type": "text", "text": text})

        return {
            "content": content,
            "stop_reason": "end_turn",
            "usage": usage,
        }


class VertexAIClient(GeminiClient):
    """Google Vertex AI client for accessing Gemini and Claude models via GCP.

    Uses google-genai SDK with vertexai=True. Authentication is handled by
    Application Default Credentials (ADC) or GOOGLE_APPLICATION_CREDENTIALS.

    The api_key parameter is expected as "project_id:location" format.
    """

    def __init__(self, api_key, model="gemini-2.5-pro", timeout=DEFAULT_TIMEOUT_SECONDS):
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ImportError("Install google-genai: pip install google-genai") from None

        # Parse project ID and location from the "api_key" field
        if ":" in api_key:
            project_id, location = api_key.split(":", 1)
        else:
            project_id = api_key
            location = "us-central1"

        self.timeout = timeout
        self.client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
            http_options=types.HttpOptions(timeout=timeout),
        )
        self.model = model
        self.history = []
        self._genai_types = types


class OpenRouterClient(OpenAIClient):
    """OpenRouter API client (OpenAI-compatible).

    OpenRouter requires:
    - API key in Authorization header (even for free models)
    - HTTP-Referer header for identification
    - X-Title header (optional, for analytics)
    """

    def __init__(self, api_key, model="qwen/qwen3-coder:free", timeout=DEFAULT_TIMEOUT_SECONDS):
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
                "HTTP-Referer": "https://github.com/radsim/radsim",
                "X-Title": "RadSim Agent",
            },
        )
        self.model = model


def create_client(provider, api_key, model=None):
    """Create an API client for the specified provider."""
    clients = {
        "claude": ClaudeClient,
        "openai": OpenAIClient,
        "gemini": GeminiClient,
        "vertex": VertexAIClient,
        "openrouter": OpenRouterClient,
    }

    if provider not in clients:
        raise ValueError(f"Unknown provider: {provider}")

    client_class = clients[provider]

    if model:
        return client_class(api_key, model)
    return client_class(api_key)
