"""Runs one behavioural case against one candidate prompt.

The loop is deliberately the same shape as the agent's: send the candidate
system prompt with the real tool schemas, execute whatever the model asks for
against the fakes, feed the results back, and stop when it answers in text.

Each run gets its own temporary project directory, so a case that writes a
file cannot affect the next case or the machine.
"""

import copy
import json
import logging
import math
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from radsim.usage import TOKEN_FIELDS, accumulate_usage

from .fake_tools import FakeToolRunner

logger = logging.getLogger(__name__)

# Enough rounds for inspect-then-answer work. Four cut real runs off
# mid-loop, which scores as "did not finish" when the model was still working.
DEFAULT_MAX_ITERATIONS = 7

# Enough for a paragraph and a tool call, small enough to keep a 29-case
# matrix affordable across repetitions.
EVAL_MAX_OUTPUT_TOKENS = 1500


@dataclass
class RunRecord:
    """Everything one case run produced, before any scoring."""

    case_id: str
    group: str
    candidate: str
    repetition: int
    sample_source: str = "live"
    final_text: str = ""
    tool_calls: list = field(default_factory=list)
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    reasoning_output_tokens: int = 0
    reported_cost_usd: float = 0.0
    reported_cost_requests: int = 0
    estimated_cost_usd: float = 0.0
    estimated_cost_requests: int = 0
    request_count: int = 0
    retry_attempts: int = 0
    latency_ms: float = 0.0
    request_ids: list[str] = field(default_factory=list)
    request_observations: list[dict[str, Any]] = field(default_factory=list)
    reported_cost_complete: bool = False
    error: str = ""

    def called(self, tool_name):
        """Return True when this run asked for one tool at least once."""
        return any(call["name"] == tool_name for call in self.tool_calls)

    def call_count(self, tool_name):
        """Return how many times this run asked for one tool."""
        return sum(1 for call in self.tool_calls if call["name"] == tool_name)

    def as_dict(self):
        """Return a JSON-serialisable copy."""
        return asdict(self)


def write_project(files, directory):
    """Materialise one case's project files inside a directory."""
    for relative_path, content in files.items():
        target = Path(directory) / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def extract_text(response):
    """Return the text blocks of one API response, joined."""
    return "\n".join(
        block.get("text", "")
        for block in response.get("content", [])
        if block.get("type") == "text"
    ).strip()


def extract_tool_uses(response):
    """Return the tool_use blocks of one API response."""
    return [block for block in response.get("content", []) if block.get("type") == "tool_use"]


def run_case(case, candidate, system_prompt, client, max_iterations=DEFAULT_MAX_ITERATIONS):
    """Run one case once and return what happened.

    An API failure is recorded on the run rather than raised: one bad request
    should not lose the rest of the matrix.
    """
    record = RunRecord(
        case_id=case.id, group=case.group, candidate=candidate, repetition=0
    )

    with tempfile.TemporaryDirectory(prefix="radsim-eval-") as directory:
        project_dir = Path(directory)
        write_project(case.files, project_dir)
        runner = FakeToolRunner(
            project_dir=project_dir, seeded_results=copy.deepcopy(dict(case.seeded_results))
        )
        messages = [{"role": "user", "content": case.user_message}]

        try:
            _drive_model(record, case, system_prompt, client, runner, messages, max_iterations)
        except Exception as error:  # one failed request must not lose the matrix
            record.retry_attempts += _error_retry_attempts(error)
            record.error = str(error)
            logger.warning("Case %s (%s) failed: %s", case.id, candidate, error)

        record.tool_calls = [
            {"name": call.name, "arguments": call.arguments} for call in runner.calls
        ]

    return record


def _drive_model(record, case, system_prompt, client, runner, messages, max_iterations):
    """Run the request/tool loop, updating the record as it goes."""
    for iteration in range(max_iterations):
        record.iterations = iteration + 1
        response = client.chat(
            messages=messages,
            system_prompt=system_prompt,
            tools=runner.schemas(),
            max_tokens=EVAL_MAX_OUTPUT_TOKENS,
        )

        usage = response.get("usage", {})
        _record_usage(record, usage)

        text = extract_text(response)
        if text:
            record.final_text = text

        tool_uses = extract_tool_uses(response)
        if not tool_uses:
            return

        messages.append({"role": "assistant", "content": response.get("content", [])})
        messages.append({"role": "user", "content": _tool_results(runner, tool_uses)})


def _record_usage(record: RunRecord, usage: dict[str, Any]) -> None:
    """Add one normalized provider usage object to an eval record."""
    fields = (
        *TOKEN_FIELDS,
        "reported_cost_usd",
        "reported_cost_requests",
        "estimated_cost_usd",
        "estimated_cost_requests",
        "request_count",
        "retry_attempts",
        "latency_ms",
    )
    totals = {name: getattr(record, name) for name in fields}
    accumulate_usage(totals, usage)
    for name in fields:
        setattr(record, name, totals[name])

    request_id = usage.get("request_id")
    if isinstance(request_id, str) and request_id:
        record.request_ids.append(request_id[:256])
    record.request_observations.append(_request_observation(usage))
    record.reported_cost_complete = (
        record.request_count > 0 and record.reported_cost_requests == record.request_count
    )


def _request_observation(usage: dict[str, Any]) -> dict[str, Any]:
    """Keep bounded per-request cache, route, model, and latency evidence."""
    return {
        "request_id": _bounded_metadata(usage.get("request_id")),
        "provider_name": _bounded_metadata(usage.get("provider_name")),
        "routed_provider": _bounded_metadata(usage.get("routed_provider")),
        "response_model": _bounded_metadata(usage.get("response_model")),
        "input_tokens": _nonnegative_integer(usage.get("input_tokens")),
        "cache_read_input_tokens": _nonnegative_integer(
            usage.get("cache_read_input_tokens")
        ),
        "cache_write_input_tokens": _nonnegative_integer(
            usage.get("cache_write_input_tokens")
        ),
        "latency_ms": _nonnegative_float(usage.get("latency_ms")),
    }


def _bounded_metadata(value: Any) -> str | None:
    return value[:256] if isinstance(value, str) and value else None


def _nonnegative_integer(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return 0
    return value


def _nonnegative_float(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def _error_retry_attempts(error: Exception) -> int:
    value = getattr(error, "retry_attempts", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _tool_results(runner, tool_uses):
    """Execute each requested tool and return the result blocks."""
    results = []
    for block in tool_uses:
        result = runner.run(block.get("name", ""), block.get("input", {}))
        results.append(
            {
                "type": "tool_result",
                "tool_use_id": block.get("id", ""),
                "content": json.dumps(result),
                **({"is_error": True} if not result.get("success") else {}),
            }
        )
    return results
