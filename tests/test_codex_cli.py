"""CLI routing and credential/process isolation for subscription sessions."""

import json
from types import SimpleNamespace

import pytest

from radsim import cli, codex_cli, codex_connection
from radsim.codex_transport import CodexError


def test_subscription_environment_excludes_keys_and_endpoint_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "private-marker")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unexpected.invalid")
    monkeypatch.setenv("RADSIM_API_KEY", "private-marker")
    monkeypatch.setenv("CODEX_HOME", "/existing/codex")
    environment = codex_connection.codex_environment(tmp_path)
    assert environment["CODEX_HOME"] == str(tmp_path)
    assert "OPENAI_API_KEY" not in environment
    assert "RADSIM_API_KEY" not in environment
    assert "OPENAI_BASE_URL" not in environment
    assert "private-marker" not in json.dumps(environment)


def test_isolated_connection_uses_stdio_and_subscription_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_connection, "find_codex", lambda *_: "/trusted/codex")
    connection = codex_connection.open_connection()
    assert connection.command[-3:] == ["app-server", "--listen", "stdio://"]
    assert 'forced_login_method="chatgpt"' in connection.command
    assert 'model_provider="openai"' in connection.command
    assert 'approvals_reviewer="user"' in connection.command
    assert connection.env["CODEX_HOME"] == connection.cwd
    assert 'shell_environment_policy.inherit="none"' in connection.command


def test_permission_profile_denies_sensitive_paths_and_network(tmp_path):
    settings = codex_connection.permission_settings(tmp_path)
    filesystem = settings[f"permissions.{codex_connection.PERMISSION_PROFILE}.filesystem"]
    assert filesystem[":root"] == "deny"
    assert filesystem[":minimal"] == "read"
    assert filesystem[":workspace_roots"]["."] == "read"
    assert filesystem[":workspace_roots"]["**/.env*"] == "deny"
    assert filesystem[str(tmp_path)] == "deny"
    assert settings[f"permissions.{codex_connection.PERMISSION_PROFILE}.network.enabled"] is False


def test_private_directory_rejects_symlink(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(CodexError, match="symbolic link"):
        codex_connection.private_directory(link)


def test_missing_codex_has_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_connection.shutil, "which", lambda *_, **__: None)
    with pytest.raises(CodexError, match="CLI is missing"):
        codex_connection.find_codex(tmp_path, {})


def test_unverified_cli_version_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_connection.shutil, "which", lambda *_, **__: "/trusted/codex")
    monkeypatch.setattr(
        codex_connection.subprocess,
        "run",
        lambda *_, **__: SimpleNamespace(stdout=b"codex-cli 0.1.0"),
    )
    with pytest.raises(CodexError, match="requires tested"):
        codex_connection.find_codex(tmp_path, {})


def test_workspace_codex_binary_is_rejected(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(codex_connection.shutil, "which", lambda *_, **__: str(tmp_path / "codex"))
    with pytest.raises(CodexError, match="current workspace"):
        codex_connection.find_codex(tmp_path, {})


@pytest.mark.parametrize("action", ["login", "logout", "status", "models"])
def test_subscription_account_commands_route_without_api_key_wizard(monkeypatch, action):
    calls = []
    monkeypatch.setattr("sys.argv", ["radsim", action, "chatgpt"])
    monkeypatch.setattr(
        codex_cli, "run_account_command", lambda *args, **kwargs: calls.append((args, kwargs)) or 0
    )
    assert cli._handle_login_subcommand() == 0
    assert calls[0][0] == (action,)


def test_device_code_is_only_for_subscription_login(monkeypatch):
    monkeypatch.setattr("sys.argv", ["radsim", "login", "openai", "--device-code"])
    with pytest.raises(SystemExit) as error:
        cli._handle_login_subcommand()
    assert error.value.code == 2


def test_subscription_loads_as_an_ordinary_provider(monkeypatch):
    """The subscription runs in RadSim's own frame: normal config, no API key."""
    from radsim import config

    monkeypatch.delenv("RADSIM_PROVIDER", raising=False)
    monkeypatch.delenv("RADSIM_API_KEY", raising=False)
    monkeypatch.setattr(
        config,
        "load_env_file",
        lambda: {
            "provider": "chatgpt",
            "provider_source": "global",
            "model": "gpt-6-astra",
            "keys": {},
        },
    )
    monkeypatch.setattr(config, "load_settings_file", lambda: {})
    monkeypatch.setattr(
        config, "setup_config", lambda *_, **__: pytest.fail("must not ask for an API key")
    )

    loaded = config.load_config()

    assert loaded.provider == "chatgpt"
    assert loaded.model == "gpt-6-astra"
    assert not loaded.api_key


def test_subscription_health_check_uses_the_sign_in(monkeypatch, tmp_path):
    """A missing key must not fail startup when the sign-in is what authenticates."""
    from radsim import chatgpt_tokens
    from radsim.health import HealthChecker

    checker = HealthChecker(SimpleNamespace(provider="chatgpt", api_key=None))
    store = tmp_path / "auth.json"
    monkeypatch.setattr(chatgpt_tokens, "auth_file", lambda: store)

    healthy, message = checker.check_api_key_present()
    assert healthy is False
    assert "radsim login chatgpt" in message

    store.write_text(
        json.dumps({"tokens": {"access_token": "private-marker", "account_id": "acct-marker"}})
    )
    healthy, message = checker.check_api_key_present()
    assert healthy is True
    assert "private-marker" not in message
    assert "acct-marker" not in message


def test_api_providers_keep_their_saved_selection(monkeypatch):
    from radsim import config

    monkeypatch.delenv("RADSIM_PROVIDER", raising=False)
    monkeypatch.setattr(
        config,
        "load_env_file",
        lambda: {"provider": "openai", "provider_source": "global", "keys": {}},
    )
    monkeypatch.setattr(config, "load_settings_file", lambda: {"last_provider": "claude"})
    assert config.resolve_provider() == "claude"
    assert config.resolve_provider("openrouter") == "openrouter"


class ConnectionStub:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def request(self, _method, _params, **__):
        return {}


def test_login_and_logout_switch_the_default_provider(monkeypatch):
    """Signing in selects the subscription for later sessions; signing out undoes it."""
    from radsim import access_control, config

    monkeypatch.delenv("RADSIM_PROVIDER", raising=False)
    monkeypatch.setattr(access_control, "check_access_on_startup", lambda: True)
    monkeypatch.setattr(codex_cli, "open_connection", ConnectionStub)
    monkeypatch.setattr(codex_cli, "login", lambda *_, **__: None)

    assert codex_cli.run_account_command("login") == 0
    assert config.resolve_provider() == "chatgpt"

    assert codex_cli.run_account_command("logout") == 0
    assert config.resolve_provider() != "chatgpt"


def test_failed_login_does_not_change_the_default_provider(monkeypatch):
    from radsim import access_control, config

    monkeypatch.delenv("RADSIM_PROVIDER", raising=False)
    monkeypatch.setattr(access_control, "check_access_on_startup", lambda: True)
    monkeypatch.setattr(codex_cli, "open_connection", ConnectionStub)
    monkeypatch.setattr(
        codex_cli, "login", lambda *_, **__: (_ for _ in ()).throw(CodexError("sign-in failed"))
    )

    assert codex_cli.run_account_command("login") == 1
    assert config.resolve_provider() != "chatgpt"


def test_wizard_offers_the_subscription_without_asking_for_a_key(monkeypatch):
    from radsim import onboarding

    monkeypatch.setattr(onboarding, "clear_screen", lambda: None)
    monkeypatch.setattr(onboarding, "pause", lambda *_: None)
    monkeypatch.setattr(onboarding, "step_api_key", lambda _: pytest.fail("must not ask"))
    monkeypatch.setattr("builtins.input", lambda _: "4")

    assert onboarding.step_select_provider() == ("chatgpt", "")


def test_wizard_saves_the_subscription_choice(monkeypatch):
    from radsim import config, onboarding

    monkeypatch.delenv("RADSIM_PROVIDER", raising=False)
    for step in ("step_user_profile", "step_provider_intro", "step_settings", "step_appearance"):
        monkeypatch.setattr(onboarding, step, lambda *_: None)
    monkeypatch.setattr(onboarding, "step_tutorial", lambda: None)
    monkeypatch.setattr(onboarding, "step_complete", lambda *_: None)
    monkeypatch.setattr(onboarding, "has_accepted_terms", lambda: True)
    monkeypatch.setattr(onboarding, "step_welcome", lambda: "Matt")
    monkeypatch.setattr(onboarding, "step_select_provider", lambda: ("chatgpt", ""))
    monkeypatch.setattr(onboarding, "step_api_key", lambda _: pytest.fail("must not ask"))

    assert onboarding.run_onboarding() == (None, "chatgpt", "")
    assert config.resolve_provider() == "chatgpt"


def _switch_handler():
    from radsim.commands_core import CoreCommandHandlersMixin

    return CoreCommandHandlersMixin()


def test_switch_menu_offers_the_subscription_and_opens_its_menu(monkeypatch, capsys):
    """Every ChatGPT account action is reachable from /switch and /model."""
    handler = _switch_handler()
    agent = SimpleNamespace(config=SimpleNamespace(provider="openrouter"))
    monkeypatch.setattr("builtins.input", lambda _: "4")
    opened = []
    monkeypatch.setattr(handler, "_chatgpt_account_menu", lambda passed: opened.append(passed))

    handler._cmd_switch(agent)

    assert opened == [agent]
    assert "ChatGPT subscription" in capsys.readouterr().out


class AgentStub:
    def __init__(self):
        self.config = SimpleNamespace(provider="openrouter")
        self.switched = []

    def update_config(self, provider, api_key, model):
        self.switched.append((provider, api_key, model))
        self.config.provider = provider


@pytest.mark.parametrize(
    "action,expected,switches",
    [
        ("login", ("login", False), True),
        ("login-device", ("login", True), True),
        ("status", ("status", False), False),
        ("logout", ("logout", False), False),
    ],
)
def test_account_menu_runs_each_action(monkeypatch, action, expected, switches):
    from radsim import menu

    handler = _switch_handler()
    agent = AgentStub()
    calls = []
    monkeypatch.setattr(
        codex_cli,
        "run_account_command",
        lambda name, device_code=False: calls.append((name, device_code)) or 0,
    )
    monkeypatch.setattr(
        menu, "interactive_menu_loop", lambda _title, _options, run: run(action)
    )

    handler._chatgpt_account_menu(agent)

    assert calls == [expected]
    assert bool(agent.switched) is switches


def test_account_menu_switches_the_live_session(monkeypatch):
    """Sessions run in RadSim's own loop, so no restart is needed."""
    from radsim import config, menu

    handler = _switch_handler()
    agent = AgentStub()
    config.save_subscription_selection("gpt-6-astra")
    monkeypatch.setattr(menu, "interactive_menu_loop", lambda _t, _o, run: run("use"))

    handler._chatgpt_account_menu(agent)

    assert agent.switched == [("chatgpt", None, "gpt-6-astra")]


def test_account_menu_opens_model_selection(monkeypatch):
    from radsim import chatgpt_models, menu

    agent = AgentStub()
    selected = []
    monkeypatch.setattr(chatgpt_models, "select_model", selected.append)
    monkeypatch.setattr(menu, "interactive_menu_loop", lambda _t, _o, run: run("models"))
    _switch_handler()._chatgpt_account_menu(agent)
    assert selected == [agent]


def test_switch_to_subscription_ignores_saved_api_model(monkeypatch):
    from radsim import config

    config.save_config("synthetic-api-key", "openrouter", "custom-provider/model")
    monkeypatch.setenv("RADSIM_MODEL", "custom-provider/model")
    monkeypatch.setenv("RADSIM_API_KEY", "synthetic-api-key")
    agent = AgentStub()

    _switch_handler()._switch_to_subscription(agent)

    assert agent.switched == [("chatgpt", None, config.DEFAULT_SUBSCRIPTION_MODEL)]
    assert config.load_config(provider_override="chatgpt").api_key is None


def test_account_menu_covers_every_subscription_command():
    from radsim.commands_core import CoreCommandHandlersMixin

    assert [key for key, _ in CoreCommandHandlersMixin.CHATGPT_ACCOUNT_ACTIONS] == [
        "login",
        "login-device",
        "use",
        "status",
        "models",
        "logout",
    ]


def test_account_menu_does_not_switch_when_sign_in_fails(monkeypatch):
    from radsim import menu

    handler = _switch_handler()
    agent = AgentStub()
    monkeypatch.setattr(codex_cli, "run_account_command", lambda *_, **__: 1)
    monkeypatch.setattr(menu, "interactive_menu_loop", lambda _t, _o, run: run("login"))

    handler._chatgpt_account_menu(agent)

    assert agent.switched == []


def test_wizard_choice_signs_in_and_keeps_the_normal_frame(monkeypatch):
    """Choosing the subscription signs in, then the ordinary session continues."""
    from radsim import onboarding

    signed_in = []
    args = SimpleNamespace(provider=None, api_key="stale", setup=True)
    monkeypatch.setattr(onboarding, "run_onboarding", lambda: (None, "chatgpt", ""))
    monkeypatch.setattr(
        codex_cli, "run_account_command", lambda action: signed_in.append(action) or 0
    )

    cli._complete_onboarding(args)

    assert signed_in == ["login"]
    assert args.provider == "chatgpt"
    assert args.api_key is None


def test_wizard_stops_when_sign_in_fails(monkeypatch):
    from radsim import onboarding

    monkeypatch.setattr(onboarding, "run_onboarding", lambda: (None, "chatgpt", ""))
    monkeypatch.setattr(codex_cli, "run_account_command", lambda _: 1)

    with pytest.raises(SystemExit) as error:
        cli._complete_onboarding(SimpleNamespace(provider=None, api_key=None, setup=True))
    assert error.value.code == 1


def test_account_output_escapes_terminal_injection(capsys):
    codex_cli.emit("hello\x1b[2J\u202eworld")
    captured = capsys.readouterr().out
    assert "\x1b" not in captured
    assert "\u202e" not in captured
    assert "hello" in captured


def test_login_saves_the_account_default_model(monkeypatch):
    from radsim import access_control, config

    monkeypatch.delenv("RADSIM_PROVIDER", raising=False)
    monkeypatch.setattr(access_control, "check_access_on_startup", lambda: True)
    monkeypatch.setattr(codex_cli, "open_connection", ConnectionStub)
    monkeypatch.setattr(codex_cli, "login", lambda *_, **__: None)
    monkeypatch.setattr(
        codex_cli,
        "list_models",
        lambda _: [{"model": "other-model"}, {"model": "gpt-6-astra", "isDefault": True}],
    )

    assert codex_cli.run_account_command("login") == 0
    assert config.load_env_file()["model"] == "gpt-6-astra"


def test_switching_away_drops_the_subscription_model(monkeypatch):
    """A ChatGPT catalogue model must never be handed to an API provider."""
    from radsim import config

    monkeypatch.delenv("RADSIM_MODEL", raising=False)
    config.save_subscription_selection("gpt-6-astra")
    config.save_config("test-key", "openrouter", None)

    assert config.load_env_file()["model"] != "gpt-6-astra"
