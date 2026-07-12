"""Security-level preset tests: persistence, the "off" level, and its limits."""

from radsim.agent_config import SECURITY_PRESETS, AgentConfigManager
from radsim.tools.command_policy import CommandPolicy


def make_manager(tmp_path):
    """Build a config manager isolated to the test's temp directory."""
    return AgentConfigManager(config_dir=tmp_path)


class TestSecurityLevelPresets:
    """Every documented level must apply and persist like other settings."""

    def test_off_is_a_valid_level(self, tmp_path):
        manager = make_manager(tmp_path)
        result = manager.set_security_level("off")
        assert result["success"] is True
        assert manager.get("security_level") == "off"

    def test_invalid_level_is_rejected(self, tmp_path):
        manager = make_manager(tmp_path)
        result = manager.set_security_level("yolo")
        assert result["success"] is False
        assert "off" in result["valid_levels"]

    def test_level_persists_across_restarts(self, tmp_path):
        make_manager(tmp_path).set_security_level("off")
        reloaded = make_manager(tmp_path)
        assert reloaded.get("security_level") == "off"
        assert reloaded.destructive_confirmation_enabled() is False

    def test_confirmations_enabled_at_every_other_level(self, tmp_path):
        manager = make_manager(tmp_path)
        for level in ("restrictive", "balanced", "permissive"):
            manager.set_security_level(level)
            assert manager.destructive_confirmation_enabled() is True

    def test_off_preset_keeps_blocklist_mode(self):
        # "off" must stay in blocklist mode so CommandPolicy still runs the
        # always-blocked catastrophic check on every command.
        assert SECURITY_PRESETS["off"]["shell_commands"]["mode"] == "blocklist"

    def test_display_warns_when_off(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.set_security_level("off")
        display = manager.get_config_display()
        assert "OFF" in display
        assert "WITHOUT confirmation" in display


class TestOffLevelStillBlocksCatastrophic:
    """Security off removes prompts, never the catastrophic-command wall."""

    def make_off_policy(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.set_security_level("off")
        return CommandPolicy(config_manager=manager)

    def test_rm_rf_root_is_still_blocked(self, tmp_path):
        policy = self.make_off_policy(tmp_path)
        allowed, reason = policy.is_command_allowed("rm -rf /")
        assert allowed is False
        assert "BLOCKED" in reason

    def test_sudo_rm_rf_root_is_still_blocked(self, tmp_path):
        policy = self.make_off_policy(tmp_path)
        allowed, _ = policy.is_command_allowed("sudo rm -rf /")
        assert allowed is False

    def test_mkfs_is_still_blocked(self, tmp_path):
        policy = self.make_off_policy(tmp_path)
        allowed, _ = policy.is_command_allowed("mkfs.ext4 /dev/sda1")
        assert allowed is False

    def test_device_write_is_still_blocked(self, tmp_path):
        policy = self.make_off_policy(tmp_path)
        allowed, _ = policy.is_command_allowed("echo boom > /dev/sda")
        assert allowed is False

    def test_ordinary_destructive_command_is_allowed_through_policy(self, tmp_path):
        # "off" means no confirmation gate; the policy itself must not block
        # everyday destructive-but-legitimate commands like git push.
        policy = self.make_off_policy(tmp_path)
        allowed, reason = policy.is_command_allowed("git push origin main")
        assert allowed is True
        assert reason is None


class TestRestrictiveWhitelistWithRedirection:
    """Restrictive mode must accept whitelisted commands that discard output."""

    def make_restrictive_policy(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.set_security_level("restrictive")
        return CommandPolicy(config_manager=manager)

    def test_whitelisted_command_with_null_redirect_is_allowed(self, tmp_path):
        policy = self.make_restrictive_policy(tmp_path)
        allowed, reason = policy.is_command_allowed("pip show radsim 2>/dev/null")
        assert allowed is True
        assert reason is None

    def test_whitelisted_command_with_file_redirect_is_blocked(self, tmp_path):
        policy = self.make_restrictive_policy(tmp_path)
        allowed, _ = policy.is_command_allowed("pip show radsim > leak.txt")
        assert allowed is False
