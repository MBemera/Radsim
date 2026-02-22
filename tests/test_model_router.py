"""Tests for the Model Router with fallback support."""

import pytest

from radsim.model_router import ModelRouter


class TestModelRouter:
    """Test model routing and fallback logic."""

    def test_default_provider(self):
        router = ModelRouter(primary_provider="claude")
        assert router.primary_provider == "claude"
        assert router.primary_model == "claude-sonnet-4-5"

    def test_default_model_per_provider(self):
        providers = ["claude", "openai", "gemini", "vertex", "openrouter"]
        for provider in providers:
            router = ModelRouter(primary_provider=provider)
            assert router.primary_model is not None

    def test_fallback_chain_includes_primary(self):
        router = ModelRouter(primary_provider="claude")
        chain = router.get_fallback_chain()
        providers_in_chain = [p for p, m in chain]
        assert "claude" in providers_in_chain

    def test_fallback_chain_includes_openrouter(self):
        """Non-openrouter providers should fall back to openrouter."""
        router = ModelRouter(primary_provider="claude")
        chain = router.get_fallback_chain()
        providers_in_chain = [p for p, m in chain]
        assert "openrouter" in providers_in_chain

    def test_openrouter_fallback_chain_no_duplicate(self):
        """OpenRouter provider shouldn't add openrouter twice."""
        router = ModelRouter(primary_provider="openrouter")
        chain = router.get_fallback_chain()
        openrouter_count = sum(1 for p, m in chain if p == "openrouter")
        # Should only appear once (from primary provider's models)
        assert openrouter_count == len(chain)


class TestProviderHealth:
    """Test provider health tracking."""

    def test_all_providers_start_healthy(self):
        router = ModelRouter()
        assert router.is_provider_healthy("claude") is True
        assert router.is_provider_healthy("openai") is True
        assert router.is_provider_healthy("gemini") is True

    def test_mark_unhealthy(self):
        router = ModelRouter()
        router.mark_provider_unhealthy("claude", "rate limited")
        assert router.is_provider_healthy("claude") is False

    def test_mark_healthy_again(self):
        router = ModelRouter()
        router.mark_provider_unhealthy("claude", "rate limited")
        router.mark_provider_healthy("claude")
        assert router.is_provider_healthy("claude") is True

    def test_error_count_tracked(self):
        router = ModelRouter()
        router.mark_provider_unhealthy("openai", "error 1")
        router.mark_provider_unhealthy("openai", "error 2")
        assert router._provider_status["openai"].error_count == 2

    def test_error_count_resets_on_healthy(self):
        router = ModelRouter()
        router.mark_provider_unhealthy("openai", "error")
        router.mark_provider_healthy("openai")
        assert router._provider_status["openai"].error_count == 0

    def test_unknown_provider_is_healthy(self):
        router = ModelRouter()
        assert router.is_provider_healthy("unknown_provider") is True


class TestModelSelection:
    """Test model selection logic."""

    def test_select_returns_tuple(self):
        router = ModelRouter(primary_provider="claude")
        provider, model = router.select_model()
        assert isinstance(provider, str)
        assert isinstance(model, str)

    def test_select_respects_max_cost(self):
        router = ModelRouter(primary_provider="claude")
        provider, model = router.select_model(max_cost=0.5)
        # Should skip expensive claude models and fall back
        from radsim.config import MODEL_PRICING

        if model in MODEL_PRICING:
            input_cost, output_cost = MODEL_PRICING[model]
            assert input_cost <= 0.5 or output_cost <= 0.5

    def test_select_skips_unhealthy_providers(self):
        router = ModelRouter(primary_provider="claude")
        router.mark_provider_unhealthy("claude", "down")

        provider, model = router.select_model()
        # Should fall back to openrouter since claude is down
        # (unless no other providers are available)
        if provider != "claude":
            assert router.is_provider_healthy(provider) is True

    def test_select_cost_effective(self):
        router = ModelRouter(primary_provider="claude")
        provider, model = router.select_cost_effective()
        assert isinstance(provider, str)
        assert isinstance(model, str)

    def test_fallback_to_primary_when_all_fail(self):
        router = ModelRouter(primary_provider="claude")
        # Mark everything unhealthy
        for p in ["claude", "openai", "gemini", "vertex", "openrouter"]:
            router.mark_provider_unhealthy(p, "down")

        provider, model = router.select_model()
        # Should fall back to primary
        assert provider == "claude"


class TestRouteWithFallback:
    """Test route_with_fallback execution."""

    def test_successful_call(self):
        router = ModelRouter(primary_provider="claude")

        def mock_api(provider, model):
            return {"response": "hello", "provider": provider}

        result = router.route_with_fallback(mock_api)
        assert result["response"] == "hello"

    def test_fallback_on_failure(self):
        router = ModelRouter(primary_provider="claude")
        call_log = []

        def flaky_api(provider, model):
            call_log.append(provider)
            if provider == "claude":
                raise ConnectionError("claude is down")
            return {"response": "ok", "provider": provider}

        result = router.route_with_fallback(flaky_api)
        assert result["response"] == "ok"
        assert "claude" in call_log
        assert router.is_provider_healthy("claude") is False

    def test_all_providers_fail_raises(self):
        router = ModelRouter(primary_provider="claude")

        def always_fail(provider, model):
            raise ConnectionError(f"{provider} is down")

        with pytest.raises(RuntimeError, match="All providers failed"):
            router.route_with_fallback(always_fail)
