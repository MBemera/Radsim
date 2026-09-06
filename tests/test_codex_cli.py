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


@pytest.mark.parametrize(
    "arguments",
    [
        ["--provider", "chatgpt", "--resume"],
        ["--provider", "chatgpt", "--resume", "thread-1"],
    ],
)
def test_subscription_arguments_are_available(monkeypatch, arguments):
    monkeypatch.setattr("sys.argv", ["radsim", *arguments])
    args = cli.parse_arguments()
    assert args.provider == "chatgpt"
    assert args.resume in ("last", "thread-1")


@pytest.mark.parametrize("explicit", [True, False])
def test_subscription_route_bypasses_api_configuration(monkeypatch, explicit):
    from radsim import access_control, config, log_config

    arguments = ["radsim", "--provider", "chatgpt"] if explicit else ["radsim"]
    monkeypatch.setattr("sys.argv", arguments)
    monkeypatch.setenv("RADSIM_PROVIDER", "chatgpt")
    monkeypatch.setattr(cli, "install_process_handlers", lambda: None)
    monkeypatch.setattr(log_config, "configure_logging", lambda: None)
    monkeypatch.setattr(access_control, "check_access_on_startup", lambda: True)
    monkeypatch.setattr(config, "load_config", lambda **_: pytest.fail("API config must not load"))
    monkeypatch.setattr(codex_cli, "run_chatgpt", lambda _: 0)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 0


def test_saved_subscription_provider_routes_without_flags(monkeypatch):
    """A stored chatgpt selection must start the subscription runtime, not the API path."""
    from radsim import access_control, config, log_config

    monkeypatch.setattr("sys.argv", ["radsim"])
    monkeypatch.delenv("RADSIM_PROVIDER", raising=False)
    monkeypatch.setattr(
        config,
        "load_env_file",
        lambda: {"provider": "chatgpt", "provider_source": "global", "keys": {}},
    )
    monkeypatch.setattr(config, "load_settings_file", lambda: {})
    monkeypatch.setattr(cli, "install_process_handlers", lambda: None)
    monkeypatch.setattr(log_config, "configure_logging", lambda: None)
    monkeypatch.setattr(access_control, "check_access_on_startup", lambda: True)
    monkeypatch.setattr(config, "load_config", lambda **_: pytest.fail("API config must not load"))
    monkeypatch.setattr(codex_cli, "run_chatgpt", lambda _: 0)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 0


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


def test_setup_reopens_the_wizard_when_the_subscription_is_saved(monkeypatch):
    """A saved subscription must not trap the user out of --setup."""
    saved = SimpleNamespace(provider=None, setup=True)
    explicit = SimpleNamespace(provider="chatgpt", setup=True)

    monkeypatch.setenv("RADSIM_PROVIDER", "chatgpt")
    assert cli._wants_subscription_session(saved) is False
    assert cli._wants_subscription_session(explicit) is True

    saved.setup = False
    assert cli._wants_subscription_session(saved) is True


def test_wizard_choice_starts_a_signed_in_subscription_session(monkeypatch):
    """Choosing the subscription in the wizard signs in, it does not load API config."""
    from radsim import access_control, config, log_config, onboarding

    started = []
    monkeypatch.setattr("sys.argv", ["radsim"])
    monkeypatch.delenv("RADSIM_PROVIDER", raising=False)
    monkeypatch.setattr(cli, "install_process_handlers", lambda: None)
    monkeypatch.setattr(log_config, "configure_logging", lambda: None)
    monkeypatch.setattr(onboarding, "should_run_onboarding", lambda: True)
    monkeypatch.setattr(onboarding, "run_onboarding", lambda: (None, "chatgpt", ""))
    monkeypatch.setattr(access_control, "check_access_on_startup", lambda: True)
    monkeypatch.setattr(config, "load_config", lambda **_: pytest.fail("API config must not load"))
    monkeypatch.setattr(codex_cli, "run_chatgpt", lambda args: started.append(args.setup) or 0)

    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 0
    assert started == [True]


def test_session_model_ignores_other_providers_saved_model(monkeypatch):
    """RADSIM_MODEL holds an API-provider model; it must not select a subscription model."""
    monkeypatch.setenv("RADSIM_MODEL", "x-ai/grok-4-fast")
    started = []
    runtime = SimpleNamespace(
        start=lambda model, resume: started.append((model, resume)),
        model="account-default",
        thread_id="thread-1",
        run_turn=lambda _: "completed",
    )
    monkeypatch.setattr(codex_cli, "open_connection", ConnectionStub)
    monkeypatch.setattr(codex_cli, "CodexRuntime", lambda *_, **__: runtime)
    args = SimpleNamespace(
        api_key=None,
        yes=False,
        context_file=None,
        no_stream=True,
        setup=False,
        model=None,
        resume=None,
        prompt="Synthetic task",
    )
    assert codex_cli.run_chatgpt(args) == 0
    assert started == [(None, None)]


def test_subscription_route_preserves_startup_access_control(monkeypatch):
    from radsim import access_control, log_config

    monkeypatch.setattr("sys.argv", ["radsim", "--provider", "chatgpt"])
    monkeypatch.setattr(cli, "install_process_handlers", lambda: None)
    monkeypatch.setattr(log_config, "configure_logging", lambda: None)
    monkeypatch.setattr(access_control, "check_access_on_startup", lambda: False)
    monkeypatch.setattr(codex_cli, "run_chatgpt", lambda _: pytest.fail("must not start"))
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1


@pytest.mark.parametrize("api_key,yes", [("synthetic", False), (None, True)])
def test_subscription_cannot_accept_api_key_or_auto_approve(api_key, yes):
    assert codex_cli.run_chatgpt(SimpleNamespace(api_key=api_key, yes=yes)) == 2


def test_approval_input_is_denied_when_not_interactive(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(EOFError):
        codex_cli.ask("Approve?")


def test_output_escapes_terminal_injection(capsys):
    output = codex_cli.TurnOutput(True)
    output.write("hello\x1b[2J\u202eworld\n")
    captured = capsys.readouterr().out
    assert "\x1b" not in captured
    assert "\u202e" not in captured
    assert "hello" in captured


def test_nonstreaming_output_is_only_emitted_at_completion(capsys):
    output = codex_cli.TurnOutput(False)
    output.write("hello ")
    output.write("world")
    assert capsys.readouterr().out == ""
    output.finish()
    assert capsys.readouterr().out == "hello world\n"


def test_context_file_must_be_safe_and_bounded(tmp_path):
    (tmp_path / "context.txt").write_text("public synthetic context")
    assert "public synthetic context" in codex_cli._initial_context("context.txt", tmp_path)
    (tmp_path / ".env").write_text("synthetic")
    with pytest.raises(CodexError):
        codex_cli._initial_context(".env", tmp_path)
    (tmp_path / "large.txt").write_text("x" * 64001)
    with pytest.raises(CodexError):
        codex_cli._initial_context("large.txt", tmp_path)
