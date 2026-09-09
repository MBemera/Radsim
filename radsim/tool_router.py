"""Deterministic capability-based routing of provider-facing tool schemas.

Sending all 72 tool schemas on every request costs roughly 7,400 input tokens
before any conversation content. This module selects a core set plus the
capability groups a turn actually indicates. The core set alone stays under
COMMON_SCHEMA_TOKEN_TARGET, and the whole routed payload stays under a
configurable budget.

Routing filters schemas only. It never changes permission tiers, confirmation
prompts, or policy checks, and it fails open to the full schema set whenever the
registry cannot be classified with confidence.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

ROUTING_ENV_VAR = "RADSIM_TOOL_SCHEMA_ROUTING"
BUDGET_ENV_VAR = "RADSIM_TOOL_SCHEMA_BUDGET_TOKENS"
COMMON_SCHEMA_TOKEN_TARGET = 2_000
DEFAULT_SCHEMA_BUDGET_TOKENS = 4_000
MINIMUM_SCHEMA_BUDGET_TOKENS = 1_000
EXTERNAL_GROUP_NAME = "external"

_TRUTHY_VALUES = {"1", "true", "yes", "on"}
_WORD_PATTERN = re.compile(r"[a-z0-9_]+")
# Bounds the tokens allocated for one pasted request. A keyword beyond this
# point is still reachable through fallback recovery.
_MAX_REQUEST_SCAN_CHARS = 20_000

# Always sent: the plan's common capability set plus the three tools the agent
# loop itself depends on (completion signalling and the todo list).
CORE_TOOL_NAMES = (
    "apply_patch",
    "git_diff",
    "git_status",
    "glob_files",
    "grep_search",
    "list_directory",
    "read_file",
    "read_many_files",
    "replace_in_file",
    "run_shell_command",
    "run_tests",
    "submit_completion",
    "todo_read",
    "todo_write",
    "write_file",
)


@dataclass(frozen=True)
class CapabilityGroup:
    """One optional schema group with its deterministic request triggers."""

    name: str
    tools: tuple[str, ...]
    keywords: tuple[str, ...]


# Declaration order is priority order: the last group is dropped first when the
# selected payload does not fit the token budget.
CAPABILITY_GROUPS: tuple[CapabilityGroup, ...] = (
    CapabilityGroup(
        name="file_management",
        tools=(
            "batch_replace",
            "create_directory",
            "delete_file",
            "multi_edit",
            "rename_file",
            "repo_map",
            "search_files",
        ),
        keywords=(
            "delete",
            "directory",
            "folder",
            "layout",
            "mkdir",
            "move",
            "rename",
            "repo map",
            "structure",
        ),
    ),
    CapabilityGroup(
        name="code_intelligence",
        tools=(
            "analyze_code",
            "find_definition",
            "find_references",
            "format_code",
            "generate_tests",
            "lint_code",
            "refactor_code",
            "type_check",
        ),
        keywords=(
            "complexity",
            "definition",
            "format",
            "lint",
            "mypy",
            "pyright",
            "refactor",
            "references",
            "ruff",
            "type check",
            "typecheck",
        ),
    ),
    CapabilityGroup(
        name="advanced_git",
        tools=(
            "git_add",
            "git_branch",
            "git_checkout",
            "git_commit",
            "git_log",
            "git_stash",
        ),
        keywords=(
            "branch",
            "checkout",
            "commit",
            "history",
            "merge",
            "pull request",
            "push",
            "rebase",
            "stash",
        ),
    ),
    CapabilityGroup(
        name="web_research",
        tools=("http_request", "web_fetch"),
        keywords=(
            "curl",
            "download",
            "endpoint",
            "http",
            "https",
            "url",
            "webpage",
            "website",
        ),
    ),
    CapabilityGroup(
        name="browser_automation",
        tools=(
            "browser_click",
            "browser_open",
            "browser_screenshot",
            "browser_type",
            "screen_capture",
        ),
        keywords=(
            "browser",
            "click",
            "playwright",
            "screenshot",
            "selector",
            "web page",
        ),
    ),
    CapabilityGroup(
        name="documents_media",
        tools=("read_document", "read_image"),
        keywords=(
            "diagram",
            "docx",
            "image",
            "jpeg",
            "jpg",
            "pdf",
            "png",
            "screenshots",
            "slide",
        ),
    ),
    CapabilityGroup(
        name="dependencies",
        tools=(
            "add_dependency",
            "install_system_tool",
            "list_dependencies",
            "npm_install",
            "pip_install",
            "remove_dependency",
        ),
        keywords=(
            "dependencies",
            "dependency",
            "install",
            "library",
            "package",
            "pip",
            "npm",
            "requirements",
            "uninstall",
            "upgrade",
        ),
    ),
    CapabilityGroup(
        name="delegation",
        tools=("delegate_task", "load_context", "plan_task", "save_context"),
        keywords=(
            "delegate",
            "milestone",
            "plan",
            "roadmap",
            "subagent",
            "sub-agent",
        ),
    ),
    CapabilityGroup(
        name="memory_learning",
        tools=("forget_memory", "load_memory", "save_memory"),
        keywords=("forget", "memorise", "memorize", "memory", "recall", "remember"),
    ),
    CapabilityGroup(
        name="operations",
        tools=(
            "database_query",
            "deploy",
            "list_schedules",
            "run_docker",
            "schedule_task",
            "send_telegram",
        ),
        keywords=(
            "container",
            "cron",
            "database",
            "deploy",
            "docker",
            "notify",
            "release",
            "schedule",
            "sql",
            "telegram",
        ),
    ),
    CapabilityGroup(
        name="project_setup",
        tools=("get_project_info", "init_project"),
        keywords=("bootstrap", "initialise", "initialize", "new project", "scaffold"),
    ),
    CapabilityGroup(
        name="skills",
        tools=("add_skill", "list_skills", "remove_skill"),
        keywords=("skill", "skills"),
    ),
    CapabilityGroup(
        name="custom_tools",
        tools=("add_tool", "list_custom_tools", "remove_tool"),
        keywords=("custom tool", "extension", "plugin", "self-extend"),
    ),
    CapabilityGroup(
        name=EXTERNAL_GROUP_NAME,
        tools=(),
        keywords=("integration", "mcp", "server"),
    ),
)

_GROUPS_BY_NAME = {group.name: group for group in CAPABILITY_GROUPS}
_GROUP_NAME_BY_TOOL = {
    tool_name: group.name for group in CAPABILITY_GROUPS for tool_name in group.tools
}


@dataclass(frozen=True)
class RoutingDecision:
    """The schema set for one turn plus the evidence for how it was chosen."""

    tools: list[dict[str, Any]]
    group_names: tuple[str, ...]
    dropped_group_names: tuple[str, ...]
    schema_tokens: int
    budget_tokens: int
    failed: bool

    @property
    def tool_names(self) -> set[str]:
        """Return the routed tool names for turn-stable membership checks."""
        return {str(tool.get("name", "")) for tool in self.tools}


def routing_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether schema routing is switched on for this process."""
    source = os.environ if environ is None else environ
    return source.get(ROUTING_ENV_VAR, "").strip().lower() in _TRUTHY_VALUES


def schema_budget_tokens(environ: Mapping[str, str] | None = None) -> int:
    """Return the configured schema-token budget, ignoring unusable values."""
    source = os.environ if environ is None else environ
    raw_value = source.get(BUDGET_ENV_VAR, "").strip()
    if not raw_value.isdigit():
        return DEFAULT_SCHEMA_BUDGET_TOKENS
    return max(MINIMUM_SCHEMA_BUDGET_TOKENS, int(raw_value))


def group_for_tool(tool_name: str, known_names: Iterable[str] = ()) -> str | None:
    """Return the capability group a tool belongs to, if it has one."""
    if tool_name in CORE_TOOL_NAMES:
        return None
    named_group = _GROUP_NAME_BY_TOOL.get(tool_name)
    if named_group:
        return named_group
    if tool_name in set(known_names):
        return EXTERNAL_GROUP_NAME
    return None


def tools_in_group(group_name: str, available_names: Iterable[str]) -> tuple[str, ...]:
    """Return the available tools belonging to one capability group."""
    available = set(available_names)
    group = _GROUPS_BY_NAME.get(group_name)
    if group is None:
        return ()
    if group.name == EXTERNAL_GROUP_NAME:
        return tuple(sorted(available - _classified_names()))
    return tuple(sorted(set(group.tools) & available))


def matched_group_names(request_text: str, available_names: Iterable[str] = ()) -> tuple[str, ...]:
    """Return the groups a request indicates, in declaration priority order."""
    lowered_text = request_text[:_MAX_REQUEST_SCAN_CHARS].lower()
    tokens = set(_WORD_PATTERN.findall(lowered_text))
    external_names = set(available_names) - _classified_names()
    matched = []
    for group in CAPABILITY_GROUPS:
        candidate_tools = external_names if group.name == EXTERNAL_GROUP_NAME else set(group.tools)
        if _group_matches(group, candidate_tools, tokens, lowered_text):
            matched.append(group.name)
    return tuple(matched)


def estimate_schema_tokens(tools: list[dict[str, Any]]) -> int:
    """Estimate the provider token cost of a serialized schema list."""
    if not tools:
        return 0
    serialized = json.dumps(tools, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return (len(serialized) + 3) // 4


def route_tool_schemas(
    tools: list[dict[str, Any]],
    request_text: str,
    *,
    budget_tokens: int | None = None,
    required_names: Iterable[str] = (),
    extra_groups: Iterable[str] = (),
) -> RoutingDecision:
    """Select the schemas for one turn, keeping every schema when unsure."""
    budget = DEFAULT_SCHEMA_BUDGET_TOKENS if budget_tokens is None else budget_tokens
    schema_names = [_schema_name(tool) for tool in tools]
    if not _names_are_routable(schema_names):
        return _unrouted_decision(tools, budget, failed=True)

    available_names = set(schema_names)
    selected_groups = _selected_group_names(request_text, available_names, extra_groups)
    protected_names = _core_names(available_names) | (set(required_names) & available_names)
    kept_groups, dropped_groups = _trim_groups_to_budget(
        tools_by_name=dict(zip(schema_names, tools, strict=True)),
        protected_names=protected_names,
        selected_groups=selected_groups,
        available_names=available_names,
        budget_tokens=budget,
    )

    routed_names = protected_names | _names_for_groups(kept_groups, available_names)
    routed_tools = [tool for name, tool in zip(schema_names, tools, strict=True) if name in routed_names]
    return RoutingDecision(
        tools=routed_tools,
        group_names=kept_groups,
        dropped_group_names=dropped_groups,
        schema_tokens=estimate_schema_tokens(routed_tools),
        budget_tokens=budget,
        failed=False,
    )


def _selected_group_names(
    request_text: str,
    available_names: set[str],
    extra_groups: Iterable[str],
) -> tuple[str, ...]:
    """Combine request-matched and caller-supplied groups in priority order."""
    requested = set(matched_group_names(request_text, available_names))
    requested.update(name for name in extra_groups if name in _GROUPS_BY_NAME)
    return tuple(group.name for group in CAPABILITY_GROUPS if group.name in requested)


def _trim_groups_to_budget(
    *,
    tools_by_name: dict[str, dict[str, Any]],
    protected_names: set[str],
    selected_groups: tuple[str, ...],
    available_names: set[str],
    budget_tokens: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Drop the lowest-priority groups until the payload fits the budget."""
    kept = list(selected_groups)
    dropped: list[str] = []
    while kept:
        routed_names = protected_names | _names_for_groups(tuple(kept), available_names)
        routed_tools = [tools_by_name[name] for name in sorted(routed_names)]
        if estimate_schema_tokens(routed_tools) <= budget_tokens:
            break
        dropped.append(kept.pop())
    return tuple(kept), tuple(reversed(dropped))


def _names_for_groups(group_names: tuple[str, ...], available_names: set[str]) -> set[str]:
    """Return every available tool name covered by the given groups."""
    names: set[str] = set()
    for group_name in group_names:
        names.update(tools_in_group(group_name, available_names))
    return names


def _core_names(available_names: set[str]) -> set[str]:
    return set(CORE_TOOL_NAMES) & available_names


def _classified_names() -> set[str]:
    return set(CORE_TOOL_NAMES) | set(_GROUP_NAME_BY_TOOL)


def _group_matches(
    group: CapabilityGroup,
    candidate_tools: set[str],
    tokens: set[str],
    lowered_text: str,
) -> bool:
    """Match a group on a curated keyword or an explicit tool name."""
    for keyword in group.keywords:
        if " " in keyword or "-" in keyword:
            if keyword in lowered_text:
                return True
        elif keyword in tokens:
            return True
    return bool(candidate_tools & tokens)


def _names_are_routable(schema_names: list[str]) -> bool:
    """Reject registries with missing or duplicate names so routing fails open."""
    if any(not name for name in schema_names):
        return False
    return len(set(schema_names)) == len(schema_names)


def _unrouted_decision(
    tools: list[dict[str, Any]],
    budget_tokens: int,
    *,
    failed: bool,
) -> RoutingDecision:
    return RoutingDecision(
        tools=list(tools),
        group_names=(),
        dropped_group_names=(),
        schema_tokens=estimate_schema_tokens(tools),
        budget_tokens=budget_tokens,
        failed=failed,
    )


def _schema_name(tool: Any) -> str:
    if not isinstance(tool, dict):
        return ""
    name = tool.get("name")
    return name if isinstance(name, str) and name.strip() else ""
