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
    ("radsim.learning.events", "_reflection_engine", None),
    ("radsim.learning.preference_learner", "_preference_learner", None),
    ("radsim.learning.proposals", "_proposal_engine", None),
    ("radsim.learning.retrieval", "_error_analyzer", None),
    ("radsim.learning.retrieval", "_few_shot_assembler", None),
    ("radsim.learning.retrieval", "_tool_optimizer", None),
    ("radsim.learning.store", "_analytics", None),
    ("radsim.learning.store", "_stores", {}),
    ("radsim.extension_loader", "_extension_loader", None),
    ("radsim.todo", "_tracker", None),
    ("radsim.safety", "_telegram_confirm_fn", None),
]


def _reset_singletons():
    """Drop cached singletons and shared caches for already-imported modules."""
    loader_module = sys.modules.get("radsim.extension_loader")
    if loader_module is not None:
        loader = getattr(loader_module, "_extension_loader", None)
        if loader is not None:
            for loaded in list(loader.loaded.values()):
                loaded.api.deactivate()

    for module_name, attr, value in _SINGLETON_RESETS:
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, attr):
            setattr(module, attr, value.copy() if isinstance(value, dict) else value)

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
    """Isolate user configuration and reset process-wide singletons (R-10)."""
    import radsim.config

    home = tmp_path_factory.mktemp("home")
    config_directory = home / ".radsim"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(radsim.config, "CONFIG_DIR", config_directory)
    monkeypatch.setattr(radsim.config, "ENV_FILE", config_directory / ".env")
    monkeypatch.setattr(
        radsim.config,
        "SETTINGS_FILE",
        config_directory / "settings.json",
    )
    monkeypatch.setattr(
        radsim.config,
        "PROJECT_ENV_FILE",
        home / "nonexistent-project.env",
    )
    _redirect_imported_config_paths(monkeypatch, config_directory)
    _reset_singletons()
    yield
    _reset_singletons()


def _redirect_imported_config_paths(monkeypatch, config_directory):
    """Redirect modules that copied config paths during import."""
    copied_paths = {
        "radsim.login": {"ENV_FILE": config_directory / ".env"},
        "radsim.onboarding": {
            "CONFIG_DIR": config_directory,
            "ENV_FILE": config_directory / ".env",
            "SETTINGS_FILE": config_directory / "settings.json",
            "ONBOARDING_FILE": config_directory / "onboarding_complete.json",
            "TERMS_ACCEPTED_FILE": config_directory / "terms_accepted.json",
        },
        "radsim.theme": {
            "CONFIG_DIR": config_directory,
            "SETTINGS_FILE": config_directory / "settings.json",
        },
        # SKILLS_FILE is resolved from Path.home() at import time, so without
        # this redirect every test after the first one reads and writes the
        # skills file of whichever temporary home existed at import. That leaks
        # a skills prompt layer between tests and makes prompt-size assertions
        # pass or fail by run order.
        "radsim.skills": {"SKILLS_FILE": config_directory / "skills.json"},
        # UNDO_ROOT is frozen the same way, so checkpoint directories from the
        # suite used to land in the developer's real ~/.radsim/undo.
        "radsim.undo": {"UNDO_ROOT": config_directory / "undo"},
    }
    for module_name, path_values in copied_paths.items():
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for attribute, value in path_values.items():
            monkeypatch.setattr(module, attribute, value)


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
