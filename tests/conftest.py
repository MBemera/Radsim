"""Shared test configuration and fixtures for RadSim tests."""

import sys

import pytest

# (module, attribute, value) for process-wide singletons that must not leak
# configuration, policy, registry, or trust-learning state between tests. A
# config written to ~/.radsim or a cached singleton by an earlier test used to
# change the policy a later test saw, so the full suite passed or failed by
# order (R-10).
_SINGLETON_RESETS = [
    ("radsim.agent_config", "_agent_config_manager", None),
    # CommandPolicy caches its config manager, so it must be reset alongside
    # the agent config or it keeps evaluating against a stale (possibly
    # whitelist) config after the manager is rebuilt.
    ("radsim.tools.command_policy", "_command_policy", None),
    ("radsim.mcp_client", "_manager", None),
    ("radsim.hooks", "_hooks_manager", None),
    ("radsim.modes", "_mode_manager", None),
    ("radsim.skill_registry", "_registry", None),
    ("radsim.model_router", "_router", None),
    ("radsim.planner", "_plan_manager", None),
    ("radsim.background", "_manager", None),
    ("radsim.health", "_health_checker", None),
    ("radsim.health", "_expiration_monitor", None),
    ("radsim.learning.active_learner", "_active_learner", None),
    ("radsim.todo", "_tracker", None),
    ("radsim.safety", "_telegram_confirm_fn", None),
]


def _reset_singletons():
    """Drop cached singletons and shared caches for already-imported modules."""
    for module_name, attr, value in _SINGLETON_RESETS:
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, attr):
            setattr(module, attr, value)

    runtime = sys.modules.get("radsim.runtime_context")
    if runtime is not None:
        try:
            runtime.get_runtime_context().clear_all()
        except Exception:
            pass

    validation = sys.modules.get("radsim.tools.validation")
    if validation is not None:
        try:
            validation.clear_path_validation_cache()
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _hermetic_state(tmp_path_factory, monkeypatch):
    """Give every test a unique HOME and reset process-wide singletons (R-10).

    Import-time constants keep the original HOME, so tests that monkeypatch
    CONFIG_DIR/ENV_FILE directly are unaffected; this only isolates runtime
    ``Path.home()`` lookups (e.g. the lazily-built agent config manager) so
    one test cannot make a later one more or less restrictive.
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    _reset_singletons()
    yield
    _reset_singletons()


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory for testing."""
    return tmp_path


@pytest.fixture
def mock_env(monkeypatch):
    """Clear RadSim environment variables for isolated tests."""
    env_vars_to_clear = [
        "RADSIM_PROVIDER",
        "RADSIM_MODEL",
        "RADSIM_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "RADSIM_ACCESS_CODE",
    ]
    for var in env_vars_to_clear:
        monkeypatch.delenv(var, raising=False)
