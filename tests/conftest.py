"""Shared test configuration and fixtures for RadSim tests."""


import pytest


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
        "GOOGLE_API_KEY",
        "OPENROUTER_API_KEY",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "RADSIM_ACCESS_CODE",
    ]
    for var in env_vars_to_clear:
        monkeypatch.delenv(var, raising=False)
