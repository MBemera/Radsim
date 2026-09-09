"""ChatGPT subscription client: RadSim's own agent loop on a ChatGPT plan.

The subscription is reachable through the Codex sign-in and the Responses
endpoint that the Codex CLI itself uses, so RadSim keeps its banner, tools,
memory and slash commands instead of handing the session to another runtime.
No API key is read or sent; billing follows the ChatGPT plan.
"""

import json
import math
import time
import uuid
from typing import Any

from .api_client import (
    DEFAULT_TIMEOUT_SECONDS,
    BaseAPIClient,
    _parse_tool_arguments,
)
from .codex_transport import CodexError
from .tool_schema import canonicalize_tool_schemas
from .usage import normalize_usage

CHATGPT_BASE_URL = "https://chatgpt.com/backend-api/codex"
# The endpoint accepts Codex-issued credentials, so requests identify as the
# Codex client that produced them, exactly like other subscription clients.
CODEX_ORIGINATOR = "codex_cli_rs"
MAX_OUTPUT_ITEMS = 4096
USAGE_LIMIT_WINDOWS = ("primary", "secondary")
MAX_WINDOW_MINUTES = 366 * 24 * 60
MAX_RESET_SECONDS = 366 * 24 * 3600


def describe_http_failure(error: Exception) -> str:
    """Map a backend failure to one clear line without echoing request content."""
    status = getattr(error, "status_code", None)
    if status in (401, 403):
        return "ChatGPT sign-in has expired. Run: radsim login chatgpt"
    if status == 429:
        return (
            "ChatGPT usage limit reached."
            f"{quota_reset_hint(error)} API billing is never used as a fallback."
        )
    if status == 400:
        return "The ChatGPT backend rejected this request. Try another model."
    return "The ChatGPT backend could not complete this request."


def quota_reset_hint(error: Exception) -> str:
    """Turn the backend's reset countdown into a sentence, when it sends one."""
    body = getattr(error, "body", None)
    if not isinstance(body, dict):
        return ""
    # The SDK reports either the whole payload or just its error object.
    detail = body.get("error") if isinstance(body.get("error"), dict) else body
    seconds = detail.get("resets_in_seconds")
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
        return ""
    minutes = int(seconds // 60)
    if minutes >= 60:
        return f" Resets in about {minutes // 60}h {minutes % 60:02d}m."
    return f" Resets in about {max(minutes, 1)} min."


def read_usage_limits(stream: Any) -> tuple[dict[str, Any], ...]:
    """Read the plan's usage windows from the response headers.

    Only the three documented headers per window are read. Everything else
    the backend sends, including its opaque turn state, is ignored.
    """
    headers = getattr(getattr(stream, "response", None), "headers", None)
    if headers is None:
        return ()
    windows = [_read_usage_window(headers, name) for name in USAGE_LIMIT_WINDOWS]
    found = [window for window in windows if window is not None]
    return tuple(sorted(found, key=lambda window: window["window_minutes"]))


def _read_usage_window(headers: Any, name: str) -> dict[str, Any] | None:
    """Return one validated window, or None when the backend omits it."""
    minutes = _bounded_int(headers.get(f"x-codex-{name}-window-minutes"), MAX_WINDOW_MINUTES)
    used_percent = _bounded_number(headers.get(f"x-codex-{name}-used-percent"), 100)
    if not minutes or used_percent is None:
        return None
    return {
        "window_minutes": minutes,
        "used_percent": used_percent,
        "resets_in_seconds": _bounded_int(
            headers.get(f"x-codex-{name}-reset-after-seconds"), MAX_RESET_SECONDS
        ),
    }


def _bounded_int(value: Any, maximum: int) -> int | None:
    number = _bounded_number(value, maximum)
    return None if number is None else int(number)


def _bounded_number(value: Any, maximum: float) -> float | None:
    """Accept only a finite, non-negative number inside the expected range."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or number > maximum:
        return None
    return number


class ChatGPTClient(BaseAPIClient):
    """Talk to the ChatGPT Responses endpoint with the Codex sign-in."""

    PROVIDER_NAME = "chatgpt"

    def __init__(
        self,
        model="gpt-6-astra",
        timeout=DEFAULT_TIMEOUT_SECONDS,
        reasoning_effort=None,
    ):
        try:
            import openai
        except ImportError:
            raise ImportError("Install openai: pip install openai") from None

        from .chatgpt_tokens import load_subscription_credentials
        from .version import get_radsim_version

        access_token, account_id = load_subscription_credentials()
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.session_id = str(uuid.uuid4())
        self.account_id = account_id
        self.usage_limits: tuple[dict[str, Any], ...] = ()
        self.client = openai.OpenAI(
            api_key=access_token,
            base_url=CHATGPT_BASE_URL,
            timeout=timeout,
            max_retries=0,
            default_headers={
                "chatgpt-account-id": account_id,
                "originator": CODEX_ORIGINATOR,
                "session-id": self.session_id,
                "User-Agent": f"{CODEX_ORIGINATOR} (RadSim {get_radsim_version()})",
            },
        )

    def _refresh_credentials(self) -> None:
        """Honor expiry and logout during a long-running RadSim session."""
        from .chatgpt_tokens import load_subscription_credentials

        access_token, account_id = load_subscription_credentials()
        if account_id != self.account_id:
            raise CodexError("ChatGPT account changed. Select it again through /switch.")
        self.client.api_key = access_token

    def _build_request_kwargs(
        self,
        messages,
        system_prompt=None,
        tools=None,
        *,
        max_tokens=None,
    ) -> dict[str, Any]:
        """Build one Responses request without performing network I/O.

        The subscription endpoint only answers streamed requests, so every
        request streams and non-streaming callers are served from the stream.
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "input": build_input_items(messages),
            "store": False,
            "stream": True,
            "parallel_tool_calls": False,
            "prompt_cache_key": self.session_id,
        }
        if system_prompt:
            kwargs["instructions"] = system_prompt
        if tools:
            kwargs["tools"] = convert_tools(tools)
            kwargs["tool_choice"] = "auto"
        # max_tokens is accepted but not forwarded: the subscription endpoint
        # answers "Unsupported parameter: max_output_tokens" and drops the turn.
        if self.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        return kwargs

    def chat(
        self,
        messages,
        system_prompt=None,
        tools=None,
        max_tokens=None,
        request_options=None,
    ):
        """Return one turn in RadSim's normal response shape."""
        final = None
        for event in self.stream_chat(messages, system_prompt, tools, max_tokens):
            if event["type"] == "final_response":
                final = event["response"]
        return final

    def stream_chat(
        self,
        messages,
        system_prompt=None,
        tools=None,
        max_tokens=None,
        request_options=None,
    ):
        """Stream one turn, yielding text deltas then the final response."""
        self._refresh_credentials()
        kwargs = self._build_request_kwargs(messages, system_prompt, tools, max_tokens=max_tokens)
        started_at = time.perf_counter()
        events = None
        try:
            events = self.client.responses.create(**kwargs)
            # Every response carries the plan's windows; keep the last known
            # set when one omits them so the status bar never blanks out.
            self.usage_limits = read_usage_limits(events) or self.usage_limits
            completed = None
            output_items = {}
            for event in events:
                event_type = getattr(event, "type", "")
                if event_type == "response.output_text.delta":
                    yield {"type": "text_delta", "text": getattr(event, "delta", "")}
                elif event_type == "response.output_item.done":
                    _remember_output_item(output_items, event)
                elif event_type in ("response.failed", "error"):
                    raise CodexError("The ChatGPT backend could not complete this request.")
                elif event_type == "response.incomplete":
                    raise CodexError("The ChatGPT backend returned an incomplete response.")
                elif event_type == "response.completed":
                    completed = getattr(event, "response", None) or completed
        except CodexError:
            raise
        except Exception as error:
            raise CodexError(describe_http_failure(error)) from None
        finally:
            if events is not None and callable(getattr(events, "close", None)):
                events.close()

        if completed is None:
            raise CodexError("The ChatGPT backend ended the response early.")
        latency_ms = (time.perf_counter() - started_at) * 1000
        yield {
            "type": "final_response",
            "response": parse_response(
                completed,
                latency_ms=latency_ms,
                output_items=[output_items[index] for index in sorted(output_items)],
            ),
        }


def _remember_output_item(items, event) -> None:
    """Keep completed stream items when the terminal response omits output."""
    index = getattr(event, "output_index", None)
    item = getattr(event, "item", None)
    if type(index) is not int or not 0 <= index < MAX_OUTPUT_ITEMS or item is None:
        raise CodexError("The ChatGPT backend returned an invalid output item.")
    items[index] = item


def convert_tools(tools) -> list[dict[str, Any]]:
    """Convert RadSim tool schemas into Responses function tools."""
    return [
        {
            "type": "function",
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        }
        for tool in canonicalize_tool_schemas(tools)
    ]


def build_input_items(messages) -> list[dict[str, Any]]:
    """Convert RadSim's conversation into Responses input items."""
    items: list[dict[str, Any]] = []
    for message in messages:
        items.extend(_message_items(message))
    return items


def _message_items(message) -> list[dict[str, Any]]:
    role = message.get("role")
    content = message.get("content")
    if isinstance(content, str):
        return [_text_item(role, content)]
    if not isinstance(content, list):
        return [_text_item(role, json.dumps(content))]
    return _block_items(role, content)


def _block_items(role, blocks) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    parts: list[dict[str, Any]] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "text":
            parts.append(_content_part(role, block.get("text", "")))
        elif block_type == "image":
            part = _image_part(block)
            if part:
                parts.append(part)
        elif block_type == "tool_use":
            items.append(
                {
                    "type": "function_call",
                    "call_id": block["id"],
                    "name": block["name"],
                    "arguments": json.dumps(block.get("input", {})),
                }
            )
        elif block_type == "tool_result":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": block["tool_use_id"],
                    "output": _result_text(block.get("content")),
                }
            )
    if parts:
        items.append({"type": "message", "role": role, "content": parts})
    return items


def _text_item(role, text) -> dict[str, Any]:
    return {"type": "message", "role": role, "content": [_content_part(role, text)]}


def _content_part(role, text) -> dict[str, Any]:
    kind = "output_text" if role == "assistant" else "input_text"
    return {"type": kind, "text": text}


def _image_part(block) -> dict[str, Any] | None:
    source = block.get("source") or {}
    media_type = source.get("media_type")
    data = source.get("data")
    if not media_type or not data:
        return None
    return {"type": "input_image", "image_url": f"data:{media_type};base64,{data}"}


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content)


def parse_response(response, latency_ms=None, output_items=None) -> dict[str, Any]:
    """Convert a Responses result into RadSim's normal response shape."""
    content = []
    for item in _read(response, "output") or output_items or []:
        item_type = _read(item, "type")
        if item_type == "message":
            text = "".join(
                _read(part, "text") or ""
                for part in (_read(item, "content") or [])
                if _read(part, "type") == "output_text"
            )
            if text:
                content.append({"type": "text", "text": text})
        elif item_type == "function_call":
            name = _read(item, "name")
            content.append(
                {
                    "type": "tool_use",
                    "id": _read(item, "call_id") or _read(item, "id"),
                    "name": name,
                    "input": _parse_tool_arguments(_read(item, "arguments") or "{}", name),
                }
            )
    return {
        "content": content,
        "stop_reason": _stop_reason(response, content),
        "usage": normalize_usage(
            _usage_fields(_read(response, "usage")),
            provider=ChatGPTClient.PROVIDER_NAME,
            response=response,
            latency_ms=latency_ms,
        ),
    }


def _stop_reason(response, content) -> str:
    details = _read(response, "incomplete_details")
    if details is not None and _read(details, "reason") == "max_output_tokens":
        return "length"
    if any(block["type"] == "tool_use" for block in content):
        return "tool_calls"
    return "stop"


def _usage_fields(usage) -> dict[str, Any]:
    """Reshape Responses usage into the fields normalize_usage reads."""
    if usage is None:
        return {}
    input_details = _read(usage, "input_tokens_details")
    output_details = _read(usage, "output_tokens_details")
    return {
        "input_tokens": _read(usage, "input_tokens") or 0,
        "output_tokens": _read(usage, "output_tokens") or 0,
        "prompt_tokens_details": {"cached_tokens": _read(input_details, "cached_tokens") or 0},
        "completion_tokens_details": {
            "reasoning_tokens": _read(output_details, "reasoning_tokens") or 0
        },
    }


def _read(source, field):
    """Read a field from an SDK object or a plain dictionary."""
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(field)
    return getattr(source, field, None)
