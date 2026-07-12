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

    def test_quoted_sudo_is_escalation(self):
        # Bash strips the quotes, so su"do" still runs sudo.
        assert command_analysis.is_privilege_escalation('su"do" apt update') is True

    def test_backslash_escaped_sudo_is_escalation(self):
        assert command_analysis.is_privilege_escalation("su\\do apt update") is True

    def test_timeout_wrapped_sudo_is_escalation(self):
        # The duration argument must not be mistaken for the real program.
        assert command_analysis.is_privilege_escalation("timeout 5 sudo apt") is True

    def test_nice_flag_wrapped_sudo_is_escalation(self):
        assert command_analysis.is_privilege_escalation("nice -n 10 sudo apt") is True

    def test_keyword_wrapped_sudo_is_escalation(self):
        assert command_analysis.is_privilege_escalation("do sudo rm x") is True

    def test_assignment_prefixed_sudo_is_escalation(self):
        assert command_analysis.is_privilege_escalation("LC_ALL=C sudo id") is True

    def test_wrapper_options_with_values_do_not_hide_sudo(self):
        assert command_analysis.is_privilege_escalation("env -u TOKEN sudo id") is True
        assert command_analysis.is_privilege_escalation("timeout --signal KILL 5 sudo id") is True
        assert command_analysis.is_privilege_escalation("stdbuf -o L sudo id") is True
        assert command_analysis.is_privilege_escalation("xargs -I ITEM sudo id") is True

    def test_numeric_redirection_does_not_hide_sudo(self):
        assert command_analysis.is_privilege_escalation("2>/dev/null sudo id") is True


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

    def test_reordered_git_push_flags_is_destructive(self):
        # An option between "git" and "push" must not hide the subcommand.
        assert is_destructive("git -C /repo push origin main")

    def test_reordered_crontab_wipe_is_destructive(self):
        assert is_destructive("crontab -u me -r")

    def test_quoted_rm_is_destructive(self):
        assert is_destructive('"rm" -rf build')

    def test_find_delete_is_destructive(self):
        assert is_destructive("find . -name '*.log' -delete")

    def test_inline_interpreter_is_destructive(self):
        assert is_destructive("python3 -c import shutil")
        assert is_destructive("bash -c whoami")

    def test_eval_is_destructive(self):
        assert is_destructive("eval echo hi")

    def test_assignment_prefixed_delete_is_destructive(self):
        assert is_destructive("LC_ALL=C rm file")

    def test_output_redirection_requires_confirmation(self):
        assert is_destructive("printf secret > output.txt")

    def test_platform_shells_and_versioned_python_are_destructive(self):
        assert is_destructive('powershell -Command "Remove-Item target"')
        assert is_destructive('pwsh -Command "Remove-Item target"')
        assert is_destructive('cmd /c "del target"')
        assert is_destructive('dash -c "rm target"')
        assert is_destructive('python3.14 -Ic "pass"')


class TestHarmlessRedirection:
    """Discarding output must not trip confirmation; file writes still do."""

    def test_stderr_to_null_is_not_destructive(self):
        assert not is_destructive("pip show radsim 2>/dev/null")

    def test_stdout_to_null_is_not_destructive(self):
        assert not is_destructive("echo hi >/dev/null")

    def test_both_streams_to_null_is_not_destructive(self):
        assert not is_destructive("make check &>/dev/null")

    def test_fd_duplication_is_not_destructive(self):
        assert not is_destructive("ls 2>&1")
        assert not is_destructive("echo warn >&2")

    def test_windows_nul_is_not_destructive(self):
        assert not is_destructive("pip show radsim 2>NUL")

    def test_null_in_chain_is_not_destructive(self):
        assert not is_destructive("pip show x 2>/dev/null; pip3 show x 2>/dev/null")

    def test_file_target_stays_destructive(self):
        assert is_destructive("echo secret > output.txt")
        assert is_destructive("make 2>errors.log")
        assert is_destructive("echo x >> log.txt")

    def test_csh_style_file_target_stays_destructive(self):
        assert is_destructive("make >& build.log")

    def test_missing_target_fails_closed(self):
        assert is_destructive("echo hi >")

    def test_lookalike_null_targets_stay_destructive(self):
        assert is_destructive("echo hi 2>/dev/nullx")
        assert is_destructive("echo hi > /dev/null/../../etc/passwd")

    def test_quoted_null_target_is_not_destructive(self):
        assert not is_destructive('echo hi > "/dev/null"')


class TestWrapperSeeThrough:
    """Benign wrappers resolve to the real program; opaque ones fail closed."""

    def test_timeout_wrapped_benign_command_is_not_destructive(self):
        assert not is_destructive("timeout 5 pip show radsim")

    def test_env_assignment_benign_command_is_not_destructive(self):
        assert not is_destructive("env FOO=1 python script.py")

    def test_nice_wrapped_benign_command_is_not_destructive(self):
        assert not is_destructive("nice -n 10 make build")

    def test_timeout_wrapped_destructive_command_stays_destructive(self):
        assert is_destructive("timeout 5 rm -rf build")

    def test_env_split_string_fails_closed(self):
        assert is_destructive('env -S "sh -c whoami"')

    def test_wrapper_without_command_fails_closed(self):
        assert is_destructive("env")
        assert is_destructive("cat names.txt | xargs")

    def test_xargs_destructive_command_stays_destructive(self):
        assert is_destructive("cat files.txt | xargs rm")

    def test_wrapper_wrapping_nested_shell_stays_destructive(self):
        assert is_destructive('timeout 5 bash -c "echo hi"')


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

    def test_quoted_parent_blocked(self):
        assert command_analysis.is_path_traversal('".."') is True

    def test_flag_equals_bare_parent_blocked(self):
        assert command_analysis.is_path_traversal("--dir=..") is True


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

    def test_policy_failure_fails_closed(self):
        # If the policy engine raises, the command must be blocked, not run.
        from unittest.mock import patch

        with patch(
            "radsim.tools.command_policy.get_command_policy",
            side_effect=RuntimeError("policy engine down"),
        ):
            is_valid, error = validate_shell_command("ls -la")
        assert is_valid is False
        assert "blocked for safety" in error.lower()

    def test_obfuscated_catastrophic_deletion_is_blocked(self):
        for command in (
            "r\\m -rf /",
            'r"m" -fr "/"',
            "rm -r -f -- /",
            "rm --recursive --force ~",
        ):
            is_valid, error = validate_shell_command(command)
            assert is_valid is False
            assert "catastrophic" in error.lower()

    def test_expanding_executable_name_is_blocked(self):
        for command in ("r{m,x} -rf /", "/bin/r? -rf /"):
            is_valid, error = validate_shell_command(command)
            assert is_valid is False
            assert "executable" in error.lower()

    def test_shell_control_structure_is_blocked(self):
        is_valid, error = validate_shell_command("if true; then rm file; fi")
        assert is_valid is False
        assert "control" in error.lower()

    def test_unanalyzable_nested_execution_is_blocked(self):
        for command in (
            "bash -c 'printf safe'",
            "su -c 'id'",
            "python3 -c 'print(1)'",
            "sudo python3 -Ic 'print(1)'",
            "sudo -s",
            "sudo -Hsi",
            "env -S 'bash -c id'",
        ):
            is_valid, error = validate_shell_command(command)
            assert is_valid is False
            assert "nested" in error.lower() or "inline" in error.lower()

    def test_python_script_and_module_execution_remain_allowed(self):
        for command in ("python scripts/check.py", "python -m pytest"):
            is_valid, error = validate_shell_command(command)
            assert is_valid is True
            assert error is None

    def test_brace_expansion_is_blocked_before_shell_expansion(self):
        command = "rm -fr {/,/tmp}"

        is_valid, error = validate_shell_command(command)

        assert is_valid is False
        assert "brace expansion" in error.lower()
        assert command_analysis.is_catastrophic_command(command) is True

    def test_quoted_braces_remain_literal_data(self):
        is_valid, error = validate_shell_command("printf '%s' '{/,/tmp}'")

        assert is_valid is True
        assert error is None

    def test_terminal_control_characters_are_blocked(self):
        for control_character in ("\x08", "\x1b", "\x7f", "\x9b", "\u202e"):
            is_valid, error = validate_shell_command(f"echo safe{control_character}")
            assert is_valid is False
            assert "terminal control" in error.lower()

    def test_only_home_root_is_catastrophic(self):
        assert command_analysis.is_catastrophic_command("rm -rf ~") is True
        assert command_analysis.is_catastrophic_command("rm -rf ~/") is True
        assert command_analysis.is_catastrophic_command("rm -rf ~/build") is False

        is_valid, error = validate_shell_command("rm -rf ~/build")
        assert is_valid is True
        assert error is None

    def test_recursive_root_content_globs_are_catastrophic(self):
        for command in (
            "rm -fr /?*",
            "rm -fr /[a-z]*",
            r"rm -fr C:\*",
            "rm -fr ~/*",
        ):
            assert command_analysis.is_catastrophic_command(command) is True
            is_valid, error = validate_shell_command(command)
            assert is_valid is False
            assert "catastrophic" in error.lower()

    def test_recursive_subdirectory_globs_remain_confirmable(self):
        for command in ("rm -fr /tmp/*", "rm -fr ~/build/*", r"rm -fr C:\tmp\*"):
            assert command_analysis.is_catastrophic_command(command) is False
            is_valid, error = validate_shell_command(command)
            assert is_valid is True
            assert error is None


class TestEnvironmentIsolation:
    """Child processes must not inherit RadSim's secrets."""

    def test_api_keys_are_secret(self):
        assert is_secret_variable("ANTHROPIC_API_KEY") is True
        assert is_secret_variable("OPENAI_API_KEY") is True
        assert is_secret_variable("MY_SERVICE_TOKEN") is True
        assert is_secret_variable("DB_PASSWORD") is True

    def test_connection_strings_are_secret(self):
        # No marker substring, but these embed credentials.
        assert is_secret_variable("DATABASE_URL") is True
        assert is_secret_variable("REDIS_URL") is True
        assert is_secret_variable("SENTRY_DSN") is True

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

    def test_build_child_environment_strips_execution_hooks(self):
        base = {
            "PATH": "/usr/bin",
            "BASH_ENV": "/tmp/injected.sh",
            "BASH_FUNC_demo%%": "() { echo injected; }",
            "LD_PRELOAD": "/tmp/injected.so",
            "NODE_OPTIONS": "--require=/tmp/injected.js",
            "SSH_AUTH_SOCK": "/tmp/agent.sock",
            "PIP_INDEX_URL": "https://untrusted.invalid/simple",
        }

        child = build_child_environment(base)

        assert child == {"PATH": "/usr/bin"}


def is_destructive(command):
    """Helper: classify a command with the standard destructive set."""
    return command_analysis.is_destructive_command(command, DESTRUCTIVE_COMMANDS)
