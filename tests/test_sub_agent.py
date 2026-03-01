"""Tests for sub-agent functionality.

Tests model resolution, task delegation, agentic tool loop, and parallel execution (mocked).
"""

import unittest
from unittest.mock import MagicMock, patch

from radsim.sub_agent import (
    HAIKU_MODEL,
    MODEL_TIERS,
    TOOL_SUBSETS,
    SubAgentResult,
    SubAgentTask,
    _build_model_aliases,
    delegate_task,
    execute_subagent_task,
    get_available_models,
    get_tools_for_tier,
    list_available_models,
    resolve_model_name,
    resolve_task_config,
)


class TestGetAvailableModels(unittest.TestCase):
    """Test that available models come from config."""

    def test_returns_openrouter_models(self):
        """Available models come from PROVIDER_MODELS['openrouter']."""
        models = get_available_models()
        assert isinstance(models, list)
        assert len(models) > 0
        # Each entry is a (model_id, description) tuple
        for model_id, description in models:
            assert isinstance(model_id, str)
            assert isinstance(description, str)

    def test_contains_kimi(self):
        """Config should include kimi model."""
        model_ids = [mid for mid, _desc in get_available_models()]
        assert "moonshotai/kimi-k2.5" in model_ids

    def test_no_free_models(self):
        """No free models like qwen-coder should appear."""
        model_ids = [mid for mid, _desc in get_available_models()]
        for mid in model_ids:
            assert ":free" not in mid


class TestModelResolution(unittest.TestCase):
    """Test model name resolution."""

    def test_resolve_alias_haiku(self):
        """'haiku' alias resolves to Haiku model."""
        result = resolve_model_name("haiku")
        assert result == HAIKU_MODEL

    def test_resolve_alias_fast(self):
        """'fast' alias resolves to Haiku model."""
        result = resolve_model_name("fast")
        assert result == HAIKU_MODEL

    def test_resolve_full_model_id(self):
        """Full model ID from config passes through."""
        result = resolve_model_name("moonshotai/kimi-k2.5")
        assert result == "moonshotai/kimi-k2.5"

    def test_unknown_model_falls_back_to_haiku(self):
        """Unknown model name falls back to Haiku with warning."""
        result = resolve_model_name("nonexistent-model-xyz")
        assert result == HAIKU_MODEL

    def test_case_insensitive(self):
        """Alias resolution is case-insensitive."""
        assert resolve_model_name("HAIKU") == resolve_model_name("haiku")

    def test_resolve_config_short_name(self):
        """Short name derived from config model ID resolves."""
        # "moonshotai/kimi-k2.5" should create alias "kimi-k2.5" and "kimi"
        aliases = _build_model_aliases()
        assert "kimi" in aliases or "kimi-k2.5" in aliases


class TestBuildModelAliases(unittest.TestCase):
    """Test alias building from config."""

    def test_always_includes_haiku(self):
        """Haiku alias is always present."""
        aliases = _build_model_aliases()
        assert "haiku" in aliases
        assert aliases["haiku"] == HAIKU_MODEL

    def test_always_includes_fast(self):
        """'fast' alias is always present and points to Haiku."""
        aliases = _build_model_aliases()
        assert "fast" in aliases
        assert aliases["fast"] == HAIKU_MODEL

    def test_aliases_from_config(self):
        """Aliases are derived from config model IDs."""
        aliases = _build_model_aliases()
        # Should have aliases for models in config
        assert len(aliases) >= 2  # At least haiku and fast


class TestListAvailableModels(unittest.TestCase):
    """Test listing available models."""

    def test_list_returns_config_models(self):
        """Listed models come from config."""
        models = list_available_models()
        assert isinstance(models, dict)
        assert len(models) > 0

    def test_list_includes_haiku(self):
        """List always includes Haiku."""
        models = list_available_models()
        assert HAIKU_MODEL in models


class TestSubAgentTaskExecution(unittest.TestCase):
    """Test sub-agent task execution with mocked API."""

    @patch("radsim.sub_agent.get_openrouter_api_key")
    def test_no_api_key_returns_error(self, mock_get_key):
        """Test error returned when no API key."""
        mock_get_key.return_value = None

        task = SubAgentTask(
            task_description="Test task",
            model="haiku",
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
            model="haiku",
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
            model="haiku",
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
            model="moonshotai/kimi-k2.5",
            system_prompt="Be helpful",
        )

        mock_execute.assert_called_once()
        task = mock_execute.call_args[0][0]
        assert task.task_description == "Do something"
        assert task.model == "moonshotai/kimi-k2.5"
        assert task.system_prompt == "Be helpful"

    @patch("radsim.sub_agent.execute_subagent_task")
    def test_delegate_task_defaults_to_haiku(self, mock_execute):
        """Default model for delegate_task is haiku, not free."""
        mock_execute.return_value = SubAgentResult(
            success=True, content="Done", model_used="test", provider_used="openrouter"
        )
        delegate_task("Simple task")

        task = mock_execute.call_args[0][0]
        assert task.model == "haiku"


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


class TestModelTiers(unittest.TestCase):
    """Test tiered model architecture."""

    def test_tiers_defined(self):
        """All three tiers exist."""
        assert "fast" in MODEL_TIERS
        assert "capable" in MODEL_TIERS
        assert "review" in MODEL_TIERS

    def test_fast_tier_uses_haiku(self):
        """Fast tier defaults to Haiku."""
        assert "haiku" in MODEL_TIERS["fast"]["default_model"]

    def test_capable_tier_full_tools(self):
        """Capable tier gets all tools."""
        assert MODEL_TIERS["capable"]["tool_subset"] == "full"

    def test_fast_tier_read_only(self):
        """Fast tier only gets read-only tools."""
        assert MODEL_TIERS["fast"]["tool_subset"] == "read_only"

    def test_haiku_alias_resolves(self):
        """Haiku alias resolves to correct model."""
        result = resolve_model_name("haiku")
        assert "haiku" in result

    def test_fast_alias_points_to_haiku(self):
        """'fast' alias points to Haiku."""
        result = resolve_model_name("fast")
        assert "haiku" in result


class TestGetToolsForTier(unittest.TestCase):
    """Test tool filtering by tier."""

    def test_fast_tier_limited_tools(self):
        """Fast tier returns a subset of tools."""
        tools = get_tools_for_tier("fast")
        tool_names = {t["name"] for t in tools}
        assert "read_file" in tool_names
        assert "grep_search" in tool_names
        assert "write_file" not in tool_names
        assert "replace_in_file" not in tool_names
        assert "run_shell_command" not in tool_names

    def test_capable_tier_all_tools(self):
        """Capable tier returns all tools."""
        from radsim.tools.definitions import TOOL_DEFINITIONS

        tools = get_tools_for_tier("capable")
        assert len(tools) == len(TOOL_DEFINITIONS)

    def test_unknown_tier_defaults_to_capable(self):
        """Unknown tier name falls back to capable (full tools)."""
        from radsim.tools.definitions import TOOL_DEFINITIONS

        tools = get_tools_for_tier("nonexistent")
        assert len(tools) == len(TOOL_DEFINITIONS)

    def test_review_tier_read_only(self):
        """Review tier uses read-only tools."""
        tools = get_tools_for_tier("review")
        tool_names = {t["name"] for t in tools}
        assert "read_file" in tool_names
        assert "write_file" not in tool_names


class TestResolveTaskConfig(unittest.TestCase):
    """Test resolve_task_config function."""

    def test_fast_tier_config(self):
        """Fast tier returns correct config."""
        config = resolve_task_config("summarize this file", tier="fast")
        assert "haiku" in config["model"]
        assert config["max_tokens"] == 2048
        assert len(config["tools"]) < 30

    def test_capable_tier_config(self):
        """Capable tier returns correct config."""
        config = resolve_task_config("refactor this code", tier="capable")
        assert config["max_tokens"] == 4096

    def test_model_override_with_config_model(self):
        """Explicit config model overrides tier default."""
        config = resolve_task_config(
            "summarize", tier="fast", model="moonshotai/kimi-k2.5"
        )
        assert config["model"] == "moonshotai/kimi-k2.5"

    def test_alias_override(self):
        """Model aliases are resolved when overriding."""
        config = resolve_task_config("task", tier="fast", model="haiku")
        assert config["model"] == HAIKU_MODEL


class TestToolSubsets(unittest.TestCase):
    """Test TOOL_SUBSETS configuration."""

    def test_read_only_subset_exists(self):
        """read_only subset is defined."""
        assert "read_only" in TOOL_SUBSETS
        assert isinstance(TOOL_SUBSETS["read_only"], list)

    def test_full_subset_is_none(self):
        """full subset is None (means all tools)."""
        assert TOOL_SUBSETS["full"] is None

    def test_read_only_contains_expected_tools(self):
        """read_only subset includes the key read tools."""
        ro = TOOL_SUBSETS["read_only"]
        assert "read_file" in ro
        assert "grep_search" in ro
        assert "repo_map" in ro
        assert "submit_completion" in ro

    def test_read_only_contains_web_fetch(self):
        """read_only subset includes web_fetch."""
        assert "web_fetch" in TOOL_SUBSETS["read_only"]

    def test_read_only_contains_todo_read(self):
        """read_only subset includes todo_read."""
        assert "todo_read" in TOOL_SUBSETS["read_only"]


class TestSubAgentTaskDefaults(unittest.TestCase):
    """Test SubAgentTask dataclass new fields."""

    def test_tools_default_empty(self):
        """Tools default to empty list."""
        task = SubAgentTask(task_description="test", model="haiku")
        assert task.tools == []

    def test_max_iterations_default(self):
        """max_iterations defaults to 10."""
        task = SubAgentTask(task_description="test", model="haiku")
        assert task.max_iterations == 10

    def test_tools_can_be_set(self):
        """Tools can be set to a list of definitions."""
        tools = [{"name": "read_file", "description": "Read a file"}]
        task = SubAgentTask(task_description="test", model="haiku", tools=tools)
        assert task.tools == tools

    def test_max_iterations_can_be_set(self):
        """max_iterations can be overridden."""
        task = SubAgentTask(task_description="test", model="haiku", max_iterations=5)
        assert task.max_iterations == 5


class TestAgenticLoop(unittest.TestCase):
    """Test the agentic tool loop in execute_subagent_task."""

    @patch("radsim.sub_agent.get_openrouter_api_key")
    @patch("radsim.sub_agent.create_client")
    def test_tool_use_then_text(self, mock_create_client, mock_get_key):
        """Model calls a tool then returns text — verify 2 API calls."""
        mock_get_key.return_value = "test-key"

        mock_client = MagicMock()
        tool_response = {
            "content": [
                {"type": "tool_use", "id": "tool_1", "name": "read_file", "input": {"file_path": "test.py"}},
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        text_response = {
            "content": [{"type": "text", "text": "File contents analyzed."}],
            "usage": {"input_tokens": 20, "output_tokens": 15},
        }
        mock_client.chat.side_effect = [tool_response, text_response]
        mock_create_client.return_value = mock_client

        tools = [{"name": "read_file", "description": "Read a file", "input_schema": {}}]
        task = SubAgentTask(
            task_description="Analyze test.py",
            model="haiku",
            tools=tools,
        )

        with patch("radsim.sub_agent._execute_tool_calls") as mock_exec:
            mock_exec.return_value = [
                {"type": "tool_result", "tool_use_id": "tool_1", "content": '{"success": true, "content": "hello"}'}
            ]
            result = execute_subagent_task(task)

        assert result.success is True
        assert result.content == "File contents analyzed."
        assert mock_client.chat.call_count == 2
        assert result.input_tokens == 30
        assert result.output_tokens == 20

    @patch("radsim.sub_agent.get_openrouter_api_key")
    @patch("radsim.sub_agent.create_client")
    def test_max_iterations_safety(self, mock_create_client, mock_get_key):
        """Model endlessly requesting tools stops at max_iterations."""
        mock_get_key.return_value = "test-key"

        mock_client = MagicMock()
        infinite_tool_response = {
            "content": [
                {"type": "tool_use", "id": "tool_1", "name": "read_file", "input": {"file_path": "x.py"}},
            ],
            "usage": {"input_tokens": 5, "output_tokens": 3},
        }
        mock_client.chat.return_value = infinite_tool_response
        mock_create_client.return_value = mock_client

        tools = [{"name": "read_file", "description": "Read", "input_schema": {}}]
        task = SubAgentTask(
            task_description="Loop forever",
            model="haiku",
            tools=tools,
            max_iterations=3,
        )

        with patch("radsim.sub_agent._execute_tool_calls") as mock_exec:
            mock_exec.return_value = [
                {"type": "tool_result", "tool_use_id": "tool_1", "content": '{"success": true}'}
            ]
            result = execute_subagent_task(task)

        assert result.success is True
        assert "max iterations" in result.content.lower()
        assert mock_client.chat.call_count == 3

    @patch("radsim.sub_agent.get_openrouter_api_key")
    @patch("radsim.sub_agent.create_client")
    def test_no_tools_single_call(self, mock_create_client, mock_get_key):
        """No tools means single API call with no loop."""
        mock_get_key.return_value = "test-key"

        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "content": [{"type": "text", "text": "Simple response"}],
            "usage": {"input_tokens": 10, "output_tokens": 20},
        }
        mock_create_client.return_value = mock_client

        task = SubAgentTask(
            task_description="Simple question",
            model="haiku",
        )
        result = execute_subagent_task(task)

        assert result.success is True
        assert result.content == "Simple response"
        assert mock_client.chat.call_count == 1
        call_kwargs = mock_client.chat.call_args[1]
        assert call_kwargs.get("tools") is None


class TestDelegateTaskWithTools(unittest.TestCase):
    """Test delegate_task convenience function with tools parameter."""

    @patch("radsim.sub_agent.execute_subagent_task")
    def test_delegate_passes_tools(self, mock_execute):
        """delegate_task passes tools to SubAgentTask."""
        mock_execute.return_value = SubAgentResult(
            success=True, content="Done", model_used="test", provider_used="openrouter"
        )
        tools = [{"name": "read_file"}]
        delegate_task("Do task", model="haiku", tools=tools, max_iterations=5)

        task = mock_execute.call_args[0][0]
        assert task.tools == tools
        assert task.max_iterations == 5

    @patch("radsim.sub_agent.execute_subagent_task")
    def test_delegate_default_no_tools(self, mock_execute):
        """delegate_task with no tools passes empty list."""
        mock_execute.return_value = SubAgentResult(
            success=True, content="Done", model_used="test", provider_used="openrouter"
        )
        delegate_task("Simple task")

        task = mock_execute.call_args[0][0]
        assert task.tools == []
        assert task.max_iterations == 10


class TestTierToolWiring(unittest.TestCase):
    """Test that tier config includes tools correctly."""

    def test_fast_config_has_tools(self):
        """Fast tier config includes tool definitions."""
        config = resolve_task_config("explore codebase", tier="fast")
        assert isinstance(config["tools"], list)
        assert len(config["tools"]) > 0

    def test_fast_config_includes_web_fetch(self):
        """Fast tier tools include web_fetch."""
        config = resolve_task_config("fetch docs", tier="fast")
        tool_names = {t["name"] for t in config["tools"]}
        assert "web_fetch" in tool_names

    def test_fast_config_excludes_write_tools(self):
        """Fast tier tools exclude write operations."""
        config = resolve_task_config("read something", tier="fast")
        tool_names = {t["name"] for t in config["tools"]}
        assert "write_file" not in tool_names
        assert "run_shell_command" not in tool_names

    def test_capable_config_has_all_tools(self):
        """Capable tier config includes all tool definitions."""
        from radsim.tools.definitions import TOOL_DEFINITIONS

        config = resolve_task_config("refactor code", tier="capable")
        assert len(config["tools"]) == len(TOOL_DEFINITIONS)


if __name__ == "__main__":
    unittest.main()
