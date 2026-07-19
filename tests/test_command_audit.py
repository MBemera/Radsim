"""Smoke-audit: every registered slash command must do its job without wiring errors.

Each handler runs against a real (hermetic) RadSimAgent with interactive
input stubbed to EOF, subprocesses stubbed, and HOME isolated so nothing
touches the developer's ~/.radsim. Wiring errors (NameError, ImportError,
AttributeError, UnboundLocalError, TypeError, KeyError) fail the audit;
a handler that stops cleanly at its first interactive prompt passes.
"""

import subprocess

import pytest

from radsim.commands import CommandRegistry
from radsim.commands_metadata import DEFAULT_COMMAND_SPECS
from radsim.config import Config

SPECS = {spec["names"][0]: spec for spec in DEFAULT_COMMAND_SPECS}

WIRING_ERRORS = (
    NameError,
    ImportError,
    AttributeError,
    UnboundLocalError,
    TypeError,
    KeyError,
)

# Safe, read-only subcommands worth exercising beyond the bare command
ARG_VARIANTS = {
    "/help": ["skill"],
    "/stats": ["prefs"],
    "/skill": ["list"],
    "/hook": ["list"],
    "/undo": ["list"],
    "/copy": ["code"],
    "/export": [],
    "/memory": ["list"],
    "/mcp": ["status"],
    "/trust": [],
    "/show": ["all"],
    "/selfmod": ["list"],
    "/telegram": ["status"],
    "/evolve": ["stats"],
    "/reset": [],
}


class ScriptlessClient:
    """API client stub — commands must not silently call the model."""

    def chat(self, messages, system_prompt=None, tools=None):
        raise RuntimeError("command handler unexpectedly called the API")

    def stream_chat(self, messages, system_prompt=None, tools=None):
        raise RuntimeError("command handler unexpectedly called the API")


@pytest.fixture
def audit_env(tmp_path, monkeypatch):
    """Isolate HOME/cwd, stub input and subprocesses, neutralize os._exit."""
    import radsim.memory

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(radsim.memory, "CONFIG_DIR", tmp_path / ".radsim")
    monkeypatch.chdir(tmp_path)

    def refuse_input(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", refuse_input)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    class FakePopen:
        @classmethod
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, *args, **kwargs):
            self.pid = 0
            self.returncode = 0

        def poll(self):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

        def communicate(self, *args, **kwargs):
            return ("", "")

        def wait(self, *args, **kwargs):
            return 0

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(subprocess, "call", lambda *a, **kw: 0)
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: b"")

    def exit_instead_of_kill(code=0):
        raise SystemExit(code)

    monkeypatch.setattr("os._exit", exit_instead_of_kill)

    yield tmp_path

    from radsim.modes import get_active_modes, toggle_mode

    for mode in list(get_active_modes()):
        toggle_mode(mode)


@pytest.fixture
def audit_agent(audit_env):
    """A real agent wired to a client that refuses silent API calls."""
    from radsim.agent import RadSimAgent

    config = Config(
        provider="claude",
        api_key="test-key",
        model="test-model",
        auto_confirm=True,
        stream=False,
    )
    agent = RadSimAgent(config)
    agent.client = ScriptlessClient()
    return agent


def invoke(registry, agent, name, args):
    """Invoke a command handler directly so wiring errors are not swallowed."""
    spec = SPECS[name]
    handler = registry.commands[name]["handler"]
    try:
        if spec["accepts_args"]:
            handler(agent, args)
        else:
            handler(agent)
    except WIRING_ERRORS as error:
        pytest.fail(f"{name} is broken: {type(error).__name__}: {error}")
    except (EOFError, KeyboardInterrupt, SystemExit):
        pass


@pytest.mark.parametrize("name", sorted(SPECS))
def test_command_runs_bare(name, audit_agent):
    registry = CommandRegistry()
    invoke(registry, audit_agent, name, [])


@pytest.mark.parametrize("name", sorted(ARG_VARIANTS))
def test_command_runs_with_safe_args(name, audit_agent):
    registry = CommandRegistry()
    invoke(registry, audit_agent, name, ARG_VARIANTS[name])


def test_every_command_has_help_topic():
    """/help <command> must work for every registered primary command."""
    from radsim.output import HELP_DETAILS

    primaries = {spec["names"][0].lstrip("/") for spec in DEFAULT_COMMAND_SPECS}
    missing = sorted(primaries - set(HELP_DETAILS))
    assert missing == [], f"commands without /help topics: {missing}"


def test_every_help_topic_is_a_real_command():
    """HELP_DETAILS must not document commands that do not exist."""
    from radsim.output import HELP_DETAILS

    primaries = {spec["names"][0].lstrip("/") for spec in DEFAULT_COMMAND_SPECS}
    ghosts = sorted(set(HELP_DETAILS) - primaries)
    assert ghosts == [], f"help topics with no command: {ghosts}"


def test_tools_list_covers_every_defined_tool(capsys):
    """/tools must list every tool in TOOL_DEFINITIONS (none silently hidden)."""
    from radsim.agent_runtime import print_tools_list
    from radsim.tools import TOOL_DEFINITIONS

    print_tools_list()
    output = capsys.readouterr().out
    for tool in TOOL_DEFINITIONS:
        assert tool["name"] in output, f"/tools omits {tool['name']}"


def test_tool_categories_reference_real_tools():
    """Curated /tools categories must not name tools that no longer exist."""
    from radsim.agent_runtime import TOOL_CATEGORIES
    from radsim.tools import TOOL_DEFINITIONS

    available = {tool["name"] for tool in TOOL_DEFINITIONS}
    ghosts = sorted(
        tool
        for tools in TOOL_CATEGORIES.values()
        for tool in tools
        if tool not in available
    )
    assert ghosts == [], f"/tools categories name nonexistent tools: {ghosts}"


def test_help_aliases_match_registry_aliases():
    """Aliases listed in help must actually be registered."""
    from radsim.output import HELP_DETAILS

    registry = CommandRegistry()
    stale = []
    for topic, info in HELP_DETAILS.items():
        for alias in info.get("aliases", []):
            normalized = alias if alias.startswith("/") else f"/{alias}"
            if normalized not in registry.commands:
                stale.append(f"{topic}: {alias}")
    assert stale == [], f"help lists unregistered aliases: {stale}"
