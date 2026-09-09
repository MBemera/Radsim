"""Subscription catalogue controls use account metadata and the normal agent."""

from types import SimpleNamespace

import pytest

from radsim import chatgpt_models, config
from radsim.codex_transport import CodexError


def account_model(name="gpt-fixture"):
    return {
        "model": name,
        "isDefault": True,
        "defaultReasoningEffort": "low",
        "supportedReasoningEfforts": [
            {"reasoningEffort": effort} for effort in ("low", "high", "ultra")
        ],
        "account_id": "must-not-cache",
    }


def test_catalogue_metadata_enables_supported_efforts(monkeypatch):
    metadata = chatgpt_models._model_metadata(account_model())
    monkeypatch.setattr(chatgpt_models, "load_catalog", lambda **_: [metadata])
    assert config.get_reasoning_effort_options("chatgpt", "gpt-fixture") == ("low", "high", "ultra")
    assert config.resolve_reasoning_effort("chatgpt", "gpt-fixture", "medium") == "low"
    assert "must-not-cache" not in str(metadata)
    config.save_reasoning_effort("ultra")
    assert config.load_reasoning_effort() == "ultra"


@pytest.mark.parametrize("supported", [None, {}, [{}], [{"reasoningEffort": "invented"}]])
def test_invalid_efforts_fail_closed(supported):
    model = account_model()
    model["supportedReasoningEfforts"] = supported
    with pytest.raises(CodexError):
        chatgpt_models._model_metadata(model)


def test_missing_catalogue_never_enables_settings(monkeypatch):
    def fail(**kwargs):
        raise CodexError("not signed in")

    monkeypatch.setattr(chatgpt_models, "load_catalog", fail)
    assert config.get_reasoning_effort_options("chatgpt", "gpt-fixture") == ()


def test_selecting_account_model_uses_agent_configuration(monkeypatch):
    from radsim import menu
    from radsim.commands_learning import LearningCommandHandlersMixin

    metadata = chatgpt_models._model_metadata(account_model())
    monkeypatch.setattr(chatgpt_models, "load_catalog", lambda **_: [metadata])
    monkeypatch.setattr(menu, "interactive_menu", lambda *a, **kw: "gpt-fixture")
    calls = []
    agent = SimpleNamespace(
        config=SimpleNamespace(model="old-model"), update_config=lambda *args: calls.append(args)
    )
    monkeypatch.setattr(
        LearningCommandHandlersMixin,
        "_reasoning_effort_menu",
        lambda self, selected: calls.append(selected),
    )
    chatgpt_models.select_model(agent)
    assert calls == [("chatgpt", None, "gpt-fixture"), agent]


def test_cancelling_model_selection_preserves_session(monkeypatch):
    from radsim import menu

    monkeypatch.setattr(
        chatgpt_models,
        "load_catalog",
        lambda **_: [chatgpt_models._model_metadata(account_model())],
    )
    monkeypatch.setattr(menu, "interactive_menu", lambda *a, **kw: None)
    agent = SimpleNamespace(
        config=SimpleNamespace(model="old-model"),
        update_config=lambda *args: pytest.fail("must not switch"),
    )
    chatgpt_models.select_model(agent)


def test_catalogue_cache_is_bounded_and_expires(monkeypatch, tmp_path):
    from contextlib import nullcontext

    from radsim import chatgpt_tokens, codex_auth, codex_connection

    store = tmp_path / "auth.json"
    store.write_text("synthetic-state")
    monkeypatch.setattr(chatgpt_tokens, "auth_file", lambda: store)
    monkeypatch.setattr(codex_connection, "open_connection", lambda: nullcontext(None))
    calls = []
    monkeypatch.setattr(
        codex_auth, "list_models", lambda _: calls.append(True) or [account_model()]
    )
    clock = [10.0]
    monkeypatch.setattr(chatgpt_models.time, "monotonic", lambda: clock[0])
    chatgpt_models.load_catalog()
    chatgpt_models.load_catalog()
    assert len(calls) == 1
    clock[0] += 301
    chatgpt_models.load_catalog()
    assert len(calls) == 2
    store.unlink()
    with pytest.raises(CodexError):
        chatgpt_models.load_catalog()
    assert chatgpt_models._catalog_cache.max_entries == 4


def test_failed_effort_change_keeps_client_and_saved_setting(monkeypatch):
    from radsim.commands_learning import LearningCommandHandlersMixin

    monkeypatch.setattr(
        chatgpt_models,
        "load_catalog",
        lambda **_: [chatgpt_models._model_metadata(account_model())],
    )

    def fail(*args, **kwargs):
        raise CodexError("sign in required")

    monkeypatch.setattr("radsim.api_client.create_client", fail)
    config.save_reasoning_effort("low")
    agent = SimpleNamespace(
        config=SimpleNamespace(
            provider="chatgpt", model="gpt-fixture", api_key=None, reasoning_effort="low"
        ),
        client="original-client",
    )
    LearningCommandHandlersMixin()._apply_reasoning_effort(agent, "high")
    assert agent.client == "original-client"
    assert agent.config.reasoning_effort == config.load_reasoning_effort() == "low"
