"""PowerShell command rules, checked against hand-built parse trees.

These run on every platform; tests/test_windows_shell_policy.py drives the
real PowerShell parser on Windows.
"""

import pytest

from radsim.tools import powershell_analysis
from radsim.tools.constants import DESTRUCTIVE_COMMANDS
from radsim.tools.powershell_analysis import (
    WindowsPathContext,
    find_catastrophic_reason,
    find_unanalyzable_reason,
    parse_is_destructive,
    protected_path_reason,
    resolve_template,
)
from radsim.tools.powershell_parser import (
    PowerShellArgument,
    PowerShellCommand,
    PowerShellParse,
    PowerShellParserError,
    PowerShellRedirection,
)

CONTEXT = WindowsPathContext(
    working_dir=r"C:\Projects\app",
    environment={
        "USERPROFILE": r"C:\Users\alex",
        "SystemRoot": r"C:\Windows",
        "ProgramFiles": r"C:\Program Files",
        "ProgramFiles(x86)": r"C:\Program Files (x86)",
        "ProgramData": r"C:\ProgramData",
        "TEMP": r"C:\Users\alex\AppData\Local\Temp",
    },
)


def literal(text):
    return PowerShellArgument("value", text, text, None, None, False, (text,))


def template(text):
    return PowerShellArgument("value", f'"{text}"', None, text, None, False, None)


def computed(text):
    return PowerShellArgument("value", text, None, None, None, False, None)


def parameter(name, inline=None):
    if inline is None:
        return PowerShellArgument("parameter", f"-{name}", None, None, name, False, None)
    return PowerShellArgument("parameter", f"-{name}:{inline}", inline, None, name, True, (inline,))


def command(name, *arguments, alias_of=None, invocation="Unknown", pipeline_id=0, pipeline_index=0):
    return PowerShellCommand(
        name=name,
        alias_of=alias_of,
        name_text=name or "$x",
        invocation=invocation,
        pipeline_id=pipeline_id,
        pipeline_index=pipeline_index,
        arguments=tuple(arguments),
    )


def parse(*commands, redirections=(), method_calls=(), type_names=(), errors=(), plain=True):
    return PowerShellParse(
        errors=tuple(errors),
        commands=tuple(commands),
        redirections=tuple(redirections),
        method_calls=tuple(method_calls),
        type_names=tuple(type_names),
        plain=plain,
    )


def catastrophic(*commands, **options):
    return find_catastrophic_reason(parse(*commands, **options), CONTEXT)


def destructive(*commands, **options):
    return parse_is_destructive(parse(*commands, **options), DESTRUCTIVE_COMMANDS)


class TestUnanalyzable:
    def test_parse_errors_are_reported(self):
        reason = find_unanalyzable_reason(parse(errors=["Missing closing '}'"]))
        assert "Missing closing" in reason

    def test_computed_program_name_is_refused(self):
        reason = find_unanalyzable_reason(parse(command(None, invocation="Ampersand")))
        assert "literally" in reason

    @pytest.mark.parametrize("name", ["powershell", "pwsh.exe", "cmd", "bash", "wsl", "mshta"])
    def test_nested_shells_are_refused(self, name):
        assert "Nested shells" in find_unanalyzable_reason(parse(command(name, literal("x"))))

    @pytest.mark.parametrize(
        "name,alias_of",
        [("iex", "Invoke-Expression"), ("Add-Type", None), ("sal", "Set-Alias"), ("New-Alias", None)],
    )
    def test_code_hiding_cmdlets_are_refused(self, name, alias_of):
        assert find_unanalyzable_reason(parse(command(name, literal("x"), alias_of=alias_of)))

    def test_alias_provider_writes_are_refused(self):
        reason = find_unanalyzable_reason(
            parse(command("New-Item", literal("alias:ls"), parameter("Value"), literal("Remove-Item")))
        )
        assert "Redefining" in reason

    def test_script_block_from_text_is_refused(self):
        assert find_unanalyzable_reason(parse(type_names=["scriptblock"]))

    def test_inline_interpreter_code_is_refused(self):
        assert find_unanalyzable_reason(parse(command("python", parameter("c"), literal("print(1)"))))

    def test_parent_traversal_is_refused(self):
        assert "traversal" in find_unanalyzable_reason(parse(command("Get-Content", literal(r"..\secret.txt"))))

    def test_ordinary_powershell_is_analysable(self):
        parsed = parse(
            command("Get-ChildItem", parameter("Force")),
            command("Where-Object", computed("{ $_.Length -gt 0 }"), pipeline_index=1),
        )
        assert find_unanalyzable_reason(parsed) is None


class TestDiskAndBootCommands:
    @pytest.mark.parametrize(
        "name",
        ["Format-Volume", "Clear-Disk", "Initialize-Disk", "Remove-Partition", "diskpart", "format.com",
         "format", "bcdedit.exe", "bootrec", "manage-bde", "Disable-BitLocker", "systemreset"],
    )
    def test_disk_and_boot_programs_are_catastrophic(self, name):
        assert "catastrophic" in catastrophic(command(name, literal("C:")))

    def test_npm_format_script_is_not_catastrophic(self):
        assert catastrophic(command("npm", literal("run"), literal("format"))) is None

    def test_indirect_launch_of_disk_program_is_catastrophic(self):
        assert catastrophic(command("Start-Process", literal("diskpart.exe")))

    @pytest.mark.parametrize(
        "name,arguments",
        [
            ("vssadmin", ["delete", "shadows", "/all"]),
            ("vssadmin", ["resize", "shadowstorage"]),
            ("wbadmin", ["delete", "catalog"]),
            ("wmic", ["shadowcopy", "delete"]),
        ],
    )
    def test_backup_deletion_is_catastrophic(self, name, arguments):
        assert catastrophic(command(name, *[literal(argument) for argument in arguments]))

    def test_listing_shadow_copies_is_allowed(self):
        assert catastrophic(command("vssadmin", literal("list"), literal("shadows"))) is None

    def test_raw_disk_device_is_catastrophic(self):
        assert catastrophic(command("dd", literal(r"of=\\.\PhysicalDrive0")))
        redirect = PowerShellRedirection("file", r"\\.\PhysicalDrive0", r"\\.\PhysicalDrive0")
        assert catastrophic(command("Write-Output", literal("x")), redirections=[redirect])

    def test_privilege_wrapper_cannot_hide_disk_program(self):
        assert catastrophic(command("gsudo", literal("diskpart")))
        assert catastrophic(command("sudo", parameter("inline"), literal("format"), literal("C:")))


class TestProtectedDeletion:
    @pytest.mark.parametrize(
        "target",
        ["C:\\", "/", "\\", "D:", r"C:\*", r"C:\Windows", r"C:\Windows\System32\drivers",
         r"C:\Program Files", r"C:\ProgramData", r"C:\Users", r"C:\Users\alex", "~",
         r"C:\Users\alex\Documents", r"C:\Users\alex\Documents\*", r"~\Desktop",
         r"FileSystem::C:\Windows", r"\\?\C:\Windows"],
    )
    def test_protected_targets_are_catastrophic(self, target):
        reason = catastrophic(command("Remove-Item", literal(target), parameter("Recurse")))
        assert reason and "catastrophic" in reason

    @pytest.mark.parametrize(
        "target",
        [r"build", r"C:\Projects\app\dist", r"C:\Users\alex\Documents\old-report.docx",
         r"C:\Windows\Temp\setup.log", r"C:\Program Files\OldApp", r"~\.cache\pip",
         r"C:\Users\alex\AppData\Local\Temp\radsim"],
    )
    def test_ordinary_targets_are_not_catastrophic(self, target):
        assert catastrophic(command("Remove-Item", literal(target), parameter("Recurse"), parameter("Force"))) is None

    def test_environment_variables_are_expanded(self):
        assert catastrophic(command("Remove-Item", template(r"$env:USERPROFILE"), parameter("Recurse")))
        assert catastrophic(command("Remove-Item", template(r"${env:ProgramFiles(x86)}")))
        assert catastrophic(command("ri", template(r"$HOME\Documents"), alias_of="Remove-Item"))
        safe = command("Remove-Item", template(r"$env:TEMP\radsim-build"), parameter("Recurse"))
        assert catastrophic(safe) is None

    def test_unset_variable_expands_to_drive_root(self):
        reason = catastrophic(command("Remove-Item", template(r"$env:MISSING_FOLDER\*"), parameter("Recurse")))
        assert "drive" in reason

    def test_recursive_delete_of_computed_path_is_catastrophic(self):
        reason = catastrophic(command("Remove-Item", computed("$target"), parameter("Recurse"), parameter("Force")))
        assert "literal path" in reason

    def test_single_delete_of_computed_path_needs_only_confirmation(self):
        single = command("Remove-Item", computed("$file"))
        assert catastrophic(single) is None
        assert destructive(single)

    def test_switch_arguments_are_not_paths(self):
        assert catastrophic(command("Remove-Item", literal("build"), parameter("Recurse", "$true"))) is None
        erroraction = command("Remove-Item", literal("build"), parameter("Recurse"), parameter("ErrorAction"), computed("$pref"))
        assert catastrophic(erroraction) is None

    def test_rm_style_flags_and_cmd_switches_count_as_recursive(self):
        assert catastrophic(command("rm", parameter("rf"), literal("/"), alias_of="Remove-Item"))
        assert catastrophic(command("rd", literal("/s"), literal("/q"), literal("C:\\"), alias_of="Remove-Item"))
        assert catastrophic(command("rd", literal("/s"), computed("$dir"), alias_of="Remove-Item"))

    def test_literal_lists_are_checked_item_by_item(self):
        both = PowerShellArgument("value", r"build,C:\Windows", None, None, None, False, ("build", r"C:\Windows"))
        assert catastrophic(command("Remove-Item", both, parameter("Recurse")))

    def test_machine_registry_keys_are_protected(self):
        assert catastrophic(command("Remove-Item", literal(r"HKLM:\SOFTWARE\Vendor"), parameter("Recurse")))
        assert catastrophic(command("reg", literal("delete"), literal(r"HKLM\SYSTEM\Setup"), literal("/f")))
        single_value = command("reg", literal("delete"), literal(r"HKLM\Software\Run"), literal("/v"), literal("App"))
        assert catastrophic(single_value) is None
        user_key = command("reg", literal("delete"), literal(r"HKCU\Software\Vendor"), literal("/f"))
        assert catastrophic(user_key) is None
        assert destructive(user_key)


class TestPipedDeletion:
    def test_listing_a_protected_folder_into_delete_is_catastrophic(self):
        listing = command("Get-ChildItem", literal("C:\\"), pipeline_index=0)
        delete = command("Remove-Item", parameter("Recurse"), pipeline_index=1)
        assert "drive" in catastrophic(listing, delete)

    def test_listing_the_profile_through_an_alias_is_catastrophic(self):
        listing = command("gci", template("$env:USERPROFILE"), alias_of="Get-ChildItem")
        delete = command("ri", parameter("r"), alias_of="Remove-Item", pipeline_index=1)
        assert catastrophic(listing, delete)

    def test_recursive_listing_of_computed_folder_is_catastrophic(self):
        listing = command("Get-ChildItem", computed("$dir"), parameter("Recurse"))
        delete = command("Remove-Item", pipeline_index=1)
        assert "literal path" in catastrophic(listing, delete)

    def test_expression_fed_recursive_delete_is_catastrophic(self):
        delete = command("Remove-Item", parameter("Recurse"), pipeline_index=1)
        assert "literal path" in catastrophic(delete)

    def test_filtered_project_cleanup_needs_only_confirmation(self):
        listing = command("Get-ChildItem", literal("logs"), parameter("Filter"), literal("*.log"))
        where = command("Where-Object", computed("{ $_.Length -gt 0 }"), pipeline_index=1)
        delete = command("Remove-Item", pipeline_index=2)
        assert catastrophic(listing, where, delete) is None
        assert destructive(listing, where, delete)

    def test_listing_the_working_directory_depends_on_where_it_is(self):
        listing = command("Get-ChildItem")
        delete = command("Remove-Item", parameter("Recurse"), pipeline_index=1)
        assert catastrophic(listing, delete) is None
        home_context = WindowsPathContext(r"C:\Users\alex", CONTEXT.environment)
        assert find_catastrophic_reason(parse(listing, delete), home_context)


class TestMoveAndPermissions:
    def test_moving_a_protected_folder_is_catastrophic(self):
        assert catastrophic(command("Move-Item", template(r"$env:USERPROFILE\Documents"), literal(r"D:\backup")))

    def test_moving_a_file_into_a_profile_folder_is_allowed(self):
        move = command("Move-Item", literal("report.txt"), template(r"$env:USERPROFILE\Desktop"))
        assert catastrophic(move) is None
        assert destructive(move)

    def test_ownership_takeover_of_system_folders_is_catastrophic(self):
        assert catastrophic(command("takeown", literal("/f"), literal(r"C:\Windows"), literal("/r")))
        assert catastrophic(command("icacls", literal("C:\\"), literal("/grant"), literal("Everyone:F"), literal("/t")))
        assert catastrophic(command("Set-Acl", parameter("Path"), literal(r"C:\Program Files"), parameter("AclObject"), computed("$acl")))

    def test_reading_acls_is_allowed(self):
        assert catastrophic(command("icacls", literal(r"C:\Windows"))) is None


class TestDestructive:
    @pytest.mark.parametrize(
        "name,alias_of",
        [
            ("Remove-Item", None), ("del", "Remove-Item"), ("mv", "Move-Item"), ("sc", "Set-Content"),
            ("Out-File", None), ("Stop-Process", None), ("taskkill", None), ("Start-Process", None),
            ("Invoke-Item", None), ("Set-ExecutionPolicy", None), ("schtasks", None), ("git.exe", None),
        ],
    )
    def test_state_changing_commands_need_confirmation(self, name, alias_of):
        arguments = [literal("push")] if name == "git.exe" else [literal("target")]
        assert destructive(command(name, *arguments, alias_of=alias_of))

    def test_windows_subcommands_need_confirmation(self):
        assert destructive(command("reg", literal("add"), literal(r"HKCU\Software\X")))
        assert destructive(command("net", literal("user"), literal("guest"), literal("/active:yes")))
        assert destructive(command("robocopy", literal("src"), literal("dst"), literal("/MIR")))
        assert destructive(command("winget", literal("uninstall"), literal("Vendor.App")))

    def test_file_redirection_needs_confirmation(self):
        write = PowerShellRedirection("file", "out.txt", "out.txt")
        assert destructive(command("Write-Output", literal("x")), redirections=[write])
        discard = PowerShellRedirection("file", "$null", None)
        merge = PowerShellRedirection("merge", None, None)
        assert not destructive(command("git", literal("status")), redirections=[discard, merge])

    def test_method_calls_dot_sourcing_and_member_invocation_need_confirmation(self):
        assert destructive(method_calls=["Delete"])
        assert destructive(command(r".\setup.ps1", invocation="Dot"))
        assert destructive(command("%", literal("Delete"), alias_of="ForEach-Object", pipeline_index=1))
        assert destructive(command("New-Item", literal("notes.txt"), parameter("Force")))

    @pytest.mark.parametrize(
        "commands",
        [
            [command("Get-ChildItem", parameter("Force"))],
            [command("git", literal("status"), literal("--short"))],
            [command("Get-Content", literal("README.md")), command("Select-Object", parameter("First"), literal("5"), pipeline_index=1)],
            [command("New-Item", parameter("ItemType"), literal("Directory"), literal("build"))],
            [command("ForEach-Object", computed("{ $_.Name }"), pipeline_index=1)],
        ],
    )
    def test_reading_commands_do_not_need_confirmation(self, commands):
        assert not destructive(*commands)

    def test_configured_destructive_commands_apply(self):
        parsed = parse(command("deploy-tool", literal("run")))
        assert not parse_is_destructive(parsed, DESTRUCTIVE_COMMANDS)
        assert parse_is_destructive(parsed, DESTRUCTIVE_COMMANDS | {"deploy-tool"})


class TestFailClosed:
    def test_parser_failure_blocks_everything(self, monkeypatch):
        def fail(_command):
            raise PowerShellParserError("PowerShell could not be started")

        monkeypatch.setattr(powershell_analysis, "parse_powershell", fail)
        assert "blocked for safety" in powershell_analysis.unanalyzable_reason("Get-Date")
        assert "blocked for safety" in powershell_analysis.catastrophic_reason("Get-Date", CONTEXT)
        assert powershell_analysis.is_destructive("Get-Date", DESTRUCTIVE_COMMANDS) is True


class TestPaths:
    def test_templates_only_expand_known_variables(self):
        assert resolve_template(r"$env:TEMP\x", CONTEXT) == r"C:\Users\alex\AppData\Local\Temp\x"
        assert resolve_template(r"$PWD\dist", CONTEXT) == r"C:\Projects\app\dist"
        assert resolve_template(r"$HOME", CONTEXT) == r"C:\Users\alex"
        assert resolve_template(r"$target\x", CONTEXT) is None
        assert resolve_template(r"$($env:TEMP)", CONTEXT) is None

    def test_non_file_paths_are_not_filesystem_targets(self):
        assert protected_path_reason(r"\\server\share", CONTEXT) is None
        assert protected_path_reason("Env:PATH", CONTEXT) is None
