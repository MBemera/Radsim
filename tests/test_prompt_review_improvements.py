"""Tests for review-backed prompt and harness improvements."""

from types import SimpleNamespace


def test_composed_prompt_names_voice_tools_and_memory_operations():
    """Test that the composed prompt wires markdown fragments into runtime."""
    from radsim.prompts import get_system_prompt

    prompt = get_system_prompt()

    assert "## Personality & Stance" in prompt
    assert "## Harness Tool Use Instructions" in prompt
    assert "save_memory" in prompt
    assert "load_memory" in prompt
    assert "forget_memory" in prompt
    assert "radsim/prompt_fragments/tool_use.md" in prompt
    assert "radsim/prompt_fragments/personality.md" in prompt


def test_prompt_stats_match_layer_lengths():
    """Test that prompt stats report layer sizes consistently."""
    from radsim.prompts import get_prompt_stats

    stats = get_prompt_stats()
    layer_chars = sum(layer["chars"] for layer in stats["layers"])
    layer_tokens = sum(layer["approx_tokens"] for layer in stats["layers"])
    layer_names = {layer["name"] for layer in stats["layers"]}

    assert stats["total_chars"] == layer_chars
    assert stats["approx_tokens"] == layer_tokens
    assert "base" in layer_names
    assert "personality" in layer_names
    assert "tool_use" in layer_names
    assert "self_modification" in layer_names


def test_api_call_refreshes_composed_prompt(monkeypatch):
    """Test that prompt fragment edits can affect the next API call."""
    from radsim.agent_api import AgentApiMixin

    class FakeProtection:
        def check_before_api_call(self):
            return None

        def record_api_success(self, input_tokens, output_tokens):
            return None

    class FakeClient:
        def __init__(self):
            self.seen_prompt = None

        def chat(self, messages, system_prompt=None, tools=None):
            self.seen_prompt = system_prompt
            return {"content": [], "usage": {"input_tokens": 1, "output_tokens": 1}}

    class FakeAgent(AgentApiMixin):
        def __init__(self):
            self.config = SimpleNamespace(stream=False)
            self.client = FakeClient()
            self.messages = []
            self.system_prompt = "stale prompt"
            self.usage_stats = {"input_tokens": 0, "output_tokens": 0}
            self.protection = FakeProtection()
            self._mcp_manager = None

    monkeypatch.setattr("radsim.agent_api.get_system_prompt", lambda: "fresh prompt")

    agent = FakeAgent()
    agent._call_api()

    assert agent.system_prompt == "fresh prompt"
    assert agent.client.seen_prompt == "fresh prompt"
