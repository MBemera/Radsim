"""Tests for sub-agent functionality.

Tests model resolution, task delegation, and parallel execution (mocked).
"""

import unittest
from unittest.mock import MagicMock, patch

from radsim.sub_agent import (
    MODEL_ALIASES,
    SubAgentResult,
    SubAgentTask,
    delegate_task,
    execute_subagent_task,
    list_available_models,
    resolve_model_name,
)


class TestModelResolution(unittest.TestCase):
    """Test model name resolution."""

    def test_resolve_alias_free(self):
        """Test 'free' alias resolves correctly."""
        result = resolve_model_name("free")
        assert result == MODEL_ALIASES["free"]

    def test_resolve_alias_glm(self):
        """Test 'glm' alias resolves correctly."""
        result = resolve_model_name("glm")
        assert result == "z-ai/glm-4.7"

    def test_resolve_alias_minimax(self):
        """Test 'minimax' alias resolves correctly."""
        result = resolve_model_name("minimax")
        assert result == "minimax/minimax-m2.1"

    def test_resolve_subagent_model(self):
        """Test short name from SUBAGENT_MODELS."""
        result = resolve_model_name("kimi")
        assert result == "moonshotai/kimi-k2.5"

    def test_resolve_full_model_id(self):
        """Test full model ID passes through unchanged."""
        full_id = "anthropic/claude-3-5-sonnet"
        result = resolve_model_name(full_id)
        assert result == full_id

    def test_case_insensitive(self):
        """Test alias resolution is case-insensitive."""
        assert resolve_model_name("FREE") == resolve_model_name("free")
        assert resolve_model_name("GLM") == resolve_model_name("glm")


class TestListAvailableModels(unittest.TestCase):
    """Test listing available models."""

    def test_list_contains_aliases(self):
        """Test list includes aliases."""
        models = list_available_models()
        assert "free" in models
        assert "glm" in models
        assert "minimax" in models

    def test_list_contains_subagent_models(self):
        """Test list includes sub-agent models."""
        models = list_available_models()
        assert "qwen-coder" in models
        assert "kimi" in models


class TestSubAgentTaskExecution(unittest.TestCase):
    """Test sub-agent task execution with mocked API."""

    @patch("radsim.sub_agent.get_openrouter_api_key")
    def test_no_api_key_returns_error(self, mock_get_key):
        """Test error returned when no API key."""
        mock_get_key.return_value = None

        task = SubAgentTask(
            task_description="Test task",
            model="free",
        )
        result = execute_subagent_task(task)

        assert result.success is False
        assert "API key" in result.error or "OPENROUTER_API_KEY" in result.error

    @patch("radsim.sub_agent.get_openrouter_api_key")
    @patch("radsim.sub_agent.create_client")
    def test_successful_execution(self, mock_create_client, mock_get_key):
        """Test successful task execution."""
        mock_get_key.return_value = "test-api-key"

        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "content": [{"type": "text", "text": "Test response"}],
            "usage": {"input_tokens": 10, "output_tokens": 20},
        }
        mock_create_client.return_value = mock_client

        task = SubAgentTask(
            task_description="What is 2+2?",
            model="free",
        )
        result = execute_subagent_task(task)

        assert result.success is True
        assert result.content == "Test response"
        assert result.input_tokens == 10
        assert result.output_tokens == 20

    @patch("radsim.sub_agent.get_openrouter_api_key")
    @patch("radsim.sub_agent.create_client")
    def test_execution_with_error(self, mock_create_client, mock_get_key):
        """Test task execution handles API errors."""
        mock_get_key.return_value = "test-api-key"
        mock_create_client.side_effect = Exception("API error")

        task = SubAgentTask(
            task_description="Test task",
            model="free",
        )
        result = execute_subagent_task(task)

        assert result.success is False
        assert "API error" in result.error


class TestDelegateTaskConvenience(unittest.TestCase):
    """Test the delegate_task convenience function."""

    @patch("radsim.sub_agent.execute_subagent_task")
    def test_delegate_task_creates_proper_task(self, mock_execute):
        """Test delegate_task creates SubAgentTask correctly."""
        mock_execute.return_value = SubAgentResult(
            success=True,
            content="Done",
            model_used="test-model",
            provider_used="openrouter",
        )

        delegate_task(
            "Do something",
            model="glm",
            system_prompt="Be helpful",
        )

        # Check the task was created correctly
        mock_execute.assert_called_once()
        task = mock_execute.call_args[0][0]
        assert task.task_description == "Do something"
        assert task.model == "glm"
        assert task.system_prompt == "Be helpful"


class TestSubAgentResult(unittest.TestCase):
    """Test SubAgentResult dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        result = SubAgentResult(
            success=True,
            content="test",
            model_used="test-model",
            provider_used="openrouter",
        )
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.error == ""


if __name__ == "__main__":
    unittest.main()
