"""Security regression tests for shell command policy boundaries."""

from radsim.tools.command_policy import CommandPolicy


class FakeConfigManager:
    """Return explicit shell policy settings without touching user config."""

    def __init__(self, mode="blocklist", whitelist=None, blocklist=None):
        self.values = {
            "shell_commands.mode": mode,
            "shell_commands.whitelist": whitelist or [],
            "shell_commands.blocklist": blocklist or [],
            "shell_commands.custom_destructive": [],
        }

    def get(self, key, default=None):
        return self.values.get(key, default)


def build_policy(**settings):
    """Build an isolated policy with explicit settings."""
    return CommandPolicy(FakeConfigManager(**settings))


class TestWhitelistSegments:
    """Every executable segment must independently match the whitelist."""

    def test_single_allowed_command(self):
        allowed, reason = build_policy(mode="whitelist", whitelist=["git status"]).is_command_allowed(
            "git status --short"
        )
        assert allowed is True
        assert reason is None

    def test_chained_command_cannot_borrow_first_prefix(self):
        policy = build_policy(mode="whitelist", whitelist=["echo"])
        for command in (
            "echo safe; curl example.invalid",
            "echo safe && curl example.invalid",
            "echo safe || curl example.invalid",
            "echo safe | curl example.invalid",
            "echo safe |& curl example.invalid",
        ):
            allowed, _ = policy.is_command_allowed(command)
            assert allowed is False

    def test_redirection_is_not_implicitly_whitelisted(self):
        allowed, _ = build_policy(mode="whitelist", whitelist=["echo"]).is_command_allowed(
            "echo secret > output.txt"
        )
        assert allowed is False

    def test_wrapper_is_not_implicitly_whitelisted(self):
        allowed, _ = build_policy(mode="whitelist", whitelist=["git status"]).is_command_allowed(
            "env TOKEN=value git status"
        )
        assert allowed is False


class TestFailClosedPolicy:
    """Invalid configuration and obfuscated catastrophe must never widen access."""

    def test_unknown_mode_is_blocked(self):
        allowed, reason = build_policy(mode="typo").is_command_allowed("echo safe")
        assert allowed is False
        assert "invalid" in reason.lower()

    def test_malformed_whitelist_is_blocked(self):
        manager = FakeConfigManager(mode="whitelist")
        manager.values["shell_commands.whitelist"] = "echo"
        allowed, reason = CommandPolicy(manager).is_command_allowed("echo safe")
        assert allowed is False
        assert "invalid" in reason.lower()

    def test_quoted_catastrophic_command_is_blocked(self):
        allowed, reason = build_policy().is_command_allowed('r"m" -rf "/"')
        assert allowed is False
        assert "catastrophic" in reason.lower()

    def test_reordered_catastrophic_flags_are_blocked(self):
        allowed, reason = build_policy().is_command_allowed("rm -r -f -- /")
        assert allowed is False
        assert "catastrophic" in reason.lower()

    def test_dangerous_device_redirection_is_blocked(self):
        allowed, reason = build_policy().is_command_allowed("printf data >/dev/disk0")
        assert allowed is False
        assert "catastrophic" in reason.lower()

    def test_privilege_wrapper_cannot_hide_catastrophic_delete(self):
        allowed, reason = build_policy().is_command_allowed("sudo -u root rm -rf /")
        assert allowed is False
        assert "catastrophic" in reason.lower()

    def test_busybox_cannot_hide_catastrophic_delete(self):
        allowed, reason = build_policy().is_command_allowed("busybox rm -rf /")
        assert allowed is False
        assert "catastrophic" in reason.lower()

    def test_brace_expansion_cannot_hide_catastrophic_delete(self):
        allowed, reason = build_policy().is_command_allowed("rm -fr {/,/tmp}")
        assert allowed is False
        assert "catastrophic" in reason.lower()

    def test_unanalyzable_nested_execution_is_blocked(self):
        for command in (
            "bash -c 'id'",
            "su -c 'id'",
            "python3 -c 'print(1)'",
            "sudo -i",
            "env -S 'bash -c id'",
        ):
            allowed, reason = build_policy().is_command_allowed(command)
            assert allowed is False
            assert "catastrophic" in reason.lower()

    def test_home_subdirectory_is_not_catastrophic(self):
        allowed, reason = build_policy().is_command_allowed("rm -rf ~/build")
        assert allowed is True
        assert reason is None

    def test_root_content_globs_are_catastrophic(self):
        for command in ("rm -fr /?*", "rm -fr /[a-z]*", r"rm -fr C:\*", "rm -fr ~/*"):
            allowed, reason = build_policy().is_command_allowed(command)
            assert allowed is False
            assert "catastrophic" in reason.lower()
