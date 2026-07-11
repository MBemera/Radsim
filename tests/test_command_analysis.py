"""Tests for structure-aware command analysis and the new shell policy.

Covers the abuse cases the structure-aware validator is meant to close:
wrapped privilege escalation, cd-based traversal, process substitution,
and environment-secret isolation.
"""

from radsim.tools import command_analysis
from radsim.tools.constants import DESTRUCTIVE_COMMANDS
from radsim.tools.environment import build_child_environment, is_secret_variable
from radsim.tools.validation import validate_shell_command


class TestPrivilegeEscalationDetection:
    """sudo/su/doas/pkexec must be detected under wrappers and absolute paths."""

    def test_bare_sudo(self):
        assert command_analysis.is_privilege_escalation("sudo apt update") is True

    def test_absolute_path_sudo(self):
        assert command_analysis.is_privilege_escalation("/usr/bin/sudo apt update") is True

    def test_env_wrapped_sudo(self):
        assert command_analysis.is_privilege_escalation("env sudo apt update") is True

    def test_env_with_assignment_wrapped_sudo(self):
        assert command_analysis.is_privilege_escalation("env FOO=1 sudo apt") is True

    def test_xargs_wrapped_sudo(self):
        assert command_analysis.is_privilege_escalation("xargs sudo rm") is True

    def test_sudo_in_second_pipeline_segment(self):
        assert command_analysis.is_privilege_escalation("echo x | sudo tee /etc/hosts") is True

    def test_doas_and_pkexec(self):
        assert command_analysis.is_privilege_escalation("doas rm file") is True
        assert command_analysis.is_privilege_escalation("pkexec whoami") is True

    def test_word_sudo_is_not_escalation(self):
        assert command_analysis.is_privilege_escalation("echo sudo makes it work") is False


class TestDestructiveClassification:
    """Destructive commands must be caught in any form or segment."""

    def test_wrapped_sudo_is_destructive(self):
        assert is_destructive("env sudo apt update")

    def test_git_push_is_destructive(self):
        assert is_destructive("git push origin main")

    def test_crontab_r_is_destructive(self):
        assert is_destructive("crontab -r")

    def test_destructive_in_chain(self):
        assert is_destructive("echo ok && rm file.txt")

    def test_benign_is_not_destructive(self):
        assert not is_destructive("ls -la")
        assert not is_destructive("git status")

    def test_unparseable_fails_closed(self):
        # Unbalanced quotes cannot be parsed -> treat as destructive.
        assert is_destructive('echo "unterminated')


class TestPathTraversal:
    """Traversal detection allows git ranges and Go wildcards, blocks parents."""

    def test_git_range_allowed(self):
        assert command_analysis.is_path_traversal("HEAD..main") is False

    def test_go_wildcard_allowed(self):
        assert command_analysis.is_path_traversal("./...") is False

    def test_parent_reference_blocked(self):
        assert command_analysis.is_path_traversal("../../etc/passwd") is True

    def test_flag_embedded_parent_blocked(self):
        assert command_analysis.is_path_traversal("--path=../secret") is True

    def test_trailing_parent_blocked(self):
        assert command_analysis.is_path_traversal("foo/..") is True

    def test_bare_parent_blocked(self):
        assert command_analysis.is_path_traversal("..") is True


class TestValidatorAbuseCases:
    """End-to-end validator behavior on abuse inputs."""

    def test_cd_dotdot_bypass_blocked(self):
        # Changing to the parent dir then reading a secret must be blocked.
        is_valid, error = validate_shell_command("cd .. && cat secret")
        assert is_valid is False
        assert "traversal" in error.lower()

    def test_process_substitution_blocked(self):
        is_valid, error = validate_shell_command("diff <(cat a) <(cat b)")
        assert is_valid is False
        assert "substitution" in error.lower()

    def test_background_execution_blocked(self):
        is_valid, error = validate_shell_command("long-task &")
        assert is_valid is False
        assert "background" in error.lower()

    def test_subshell_grouping_blocked(self):
        is_valid, error = validate_shell_command("( rm file )")
        assert is_valid is False

    def test_go_test_wildcard_allowed(self):
        is_valid, error = validate_shell_command("go test ./...")
        assert is_valid is True
        assert error is None

    def test_git_range_diff_allowed(self):
        is_valid, error = validate_shell_command("git diff HEAD..main")
        assert is_valid is True
        assert error is None

    def test_file_redirection_allowed(self):
        is_valid, error = validate_shell_command("printf data > out.txt")
        assert is_valid is True
        assert error is None


class TestEnvironmentIsolation:
    """Child processes must not inherit RadSim's secrets."""

    def test_api_keys_are_secret(self):
        assert is_secret_variable("ANTHROPIC_API_KEY") is True
        assert is_secret_variable("OPENAI_API_KEY") is True
        assert is_secret_variable("MY_SERVICE_TOKEN") is True
        assert is_secret_variable("DB_PASSWORD") is True

    def test_ordinary_vars_are_not_secret(self):
        assert is_secret_variable("PATH") is False
        assert is_secret_variable("HOME") is False
        assert is_secret_variable("LANG") is False

    def test_build_child_environment_strips_secrets(self):
        base = {"PATH": "/usr/bin", "ANTHROPIC_API_KEY": "sk-secret", "HOME": "/home/x"}
        child = build_child_environment(base)
        assert "ANTHROPIC_API_KEY" not in child
        assert child["PATH"] == "/usr/bin"
        assert child["HOME"] == "/home/x"


def is_destructive(command):
    """Helper: classify a command with the standard destructive set."""
    return command_analysis.is_destructive_command(command, DESTRUCTIVE_COMMANDS)
