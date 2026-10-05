"""Parse commands with Windows PowerShell's own parser.

RadSim runs agent shell commands through Windows PowerShell on Windows. Bash
tokenizing rules misread PowerShell (variables, the call operator, script
blocks), so commands are parsed by PowerShell itself and only the parse tree
comes back. Parsing never executes the command.
"""

import base64
import json
import ntpath
import os
import subprocess
from dataclasses import dataclass
from functools import lru_cache

PARSER_TIMEOUT_SECONDS = 20
SOURCE_ENVIRONMENT_VARIABLE = "RADSIM_POWERSHELL_SOURCE"

PARSER_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$source = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:RADSIM_POWERSHELL_SOURCE))
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$errors)
$language = 'System.Management.Automation.Language'

$aliases = @{}
foreach ($alias in Get-Alias) { $aliases[$alias.Name] = $alias.Definition }

function Get-ConstantText($node) {
    if ($node -is [System.Management.Automation.Language.ConstantExpressionAst]) { return [string]$node.Value }
    return $null
}

function Get-ConstantItems($node) {
    if ($node -is [System.Management.Automation.Language.ConstantExpressionAst]) { return ,@([string]$node.Value) }
    if ($node -is [System.Management.Automation.Language.ArrayLiteralAst]) {
        $items = @()
        foreach ($element in $node.Elements) {
            if (-not ($element -is [System.Management.Automation.Language.ConstantExpressionAst])) { return $null }
            $items += [string]$element.Value
        }
        return ,$items
    }
    return $null
}

function Get-Template($node) {
    if ($node -is [System.Management.Automation.Language.ExpandableStringExpressionAst]) { return $node.Value }
    if ($node -is [System.Management.Automation.Language.VariableExpressionAst]) { return $node.Extent.Text }
    return $null
}

function New-ArgumentRecord($element) {
    if ($element -is [System.Management.Automation.Language.CommandParameterAst]) {
        $inline = $element.Argument
        return [ordered]@{
            kind = 'parameter'
            name = $element.ParameterName
            text = $element.Extent.Text
            value = $(if ($null -ne $inline) { Get-ConstantText $inline } else { $null })
            items = $(if ($null -ne $inline) { Get-ConstantItems $inline } else { $null })
            template = $(if ($null -ne $inline) { Get-Template $inline } else { $null })
            hasArgument = ($null -ne $inline)
        }
    }
    return [ordered]@{
        kind = 'value'
        name = $null
        text = $element.Extent.Text
        value = Get-ConstantText $element
        items = Get-ConstantItems $element
        template = Get-Template $element
        hasArgument = $false
    }
}

function Test-ConstantElement($element) {
    if ($element -is [System.Management.Automation.Language.CommandParameterAst]) {
        return ($null -eq $element.Argument) -or ($element.Argument -is [System.Management.Automation.Language.ConstantExpressionAst])
    }
    return $element -is [System.Management.Automation.Language.ConstantExpressionAst]
}

function Test-PlainCommand($command) {
    if ($command.InvocationOperator -ne 'Unknown') { return $false }
    foreach ($element in $command.CommandElements) {
        if (-not (Test-ConstantElement $element)) { return $false }
    }
    return $true
}

$pipelineIds = New-Object 'System.Collections.Generic.Dictionary[object,int]'
$pipelines = $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.PipelineAst] }, $true)
foreach ($pipeline in $pipelines) { $pipelineIds[$pipeline] = $pipelineIds.Count }

$commands = @(
    foreach ($command in $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.CommandAst] }, $true)) {
        $name = $command.GetCommandName()
        $elements = $command.CommandElements
        $pipelineId = -1
        $pipelineIndex = 0
        if ($command.Parent -is [System.Management.Automation.Language.PipelineAst]) {
            $pipelineId = $pipelineIds[$command.Parent]
            $pipelineIndex = $command.Parent.PipelineElements.IndexOf($command)
        }
        [ordered]@{
            name = $name
            aliasOf = $(if ($name -and $aliases.ContainsKey($name)) { $aliases[$name] } else { $null })
            nameText = $elements[0].Extent.Text
            invocation = [string]$command.InvocationOperator
            pipelineId = $pipelineId
            pipelineIndex = $pipelineIndex
            arguments = @(for ($index = 1; $index -lt $elements.Count; $index++) { New-ArgumentRecord $elements[$index] })
        }
    }
)

$redirections = @(
    foreach ($redirection in $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.RedirectionAst] }, $true)) {
        if ($redirection -is [System.Management.Automation.Language.FileRedirectionAst]) {
            [ordered]@{ kind = 'file'; targetText = $redirection.Location.Extent.Text; target = Get-ConstantText $redirection.Location }
        } else {
            [ordered]@{ kind = 'merge'; targetText = $null; target = $null }
        }
    }
)

$methodCalls = @(
    foreach ($member in $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.InvokeMemberExpressionAst] }, $true)) {
        $member.Member.Extent.Text
    }
)

$typeNames = @(
    foreach ($node in $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.TypeExpressionAst] -or $node -is [System.Management.Automation.Language.TypeConstraintAst] }, $true)) {
        $node.TypeName.FullName
    }
)

$contextMutations = $false
foreach ($assignment in $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.AssignmentStatementAst] }, $true)) {
    $target = $assignment.Left
    $members = $target.FindAll({ param($node) $node -is [System.Management.Automation.Language.MemberExpressionAst] }, $true)
    if ($members.Count -gt 0) { $contextMutations = $true }
    foreach ($variable in $target.FindAll({ param($node) $node -is [System.Management.Automation.Language.VariableExpressionAst] }, $true)) {
        if ($variable.VariablePath.UserPath -match '^(env:|(?:(global|script|local|private):)?(home|pwd)$)') {
            $contextMutations = $true
        }
    }
}

$plain = ($errors.Count -eq 0) -and ($null -eq $ast.ParamBlock) -and ($null -eq $ast.BeginBlock) -and ($null -eq $ast.ProcessBlock) -and ($null -eq $ast.DynamicParamBlock) -and ($null -ne $ast.EndBlock) -and ($null -eq $ast.EndBlock.Traps)
if ($plain) {
    foreach ($statement in $ast.EndBlock.Statements) {
        if (-not ($statement -is [System.Management.Automation.Language.PipelineAst])) { $plain = $false; break }
        foreach ($element in $statement.PipelineElements) {
            if (-not ($element -is [System.Management.Automation.Language.CommandAst]) -or -not (Test-PlainCommand $element)) { $plain = $false }
        }
    }
}

$result = [ordered]@{
    errors = @(foreach ($parseError in $errors) { $parseError.Message })
    commands = $commands
    redirections = $redirections
    methodCalls = $methodCalls
    typeNames = $typeNames
    contextMutations = $contextMutations
    plain = $plain
}
$json = ConvertTo-Json -InputObject $result -Depth 8 -Compress
[Console]::Out.Write([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json)))
"""

ENCODED_PARSER_SCRIPT = base64.b64encode(PARSER_SCRIPT.encode("utf-16-le")).decode("ascii")


class PowerShellParserError(Exception):
    """Raised when the PowerShell parser cannot be run or returns nonsense."""


@dataclass(frozen=True)
class PowerShellArgument:
    """One command element after the command name."""

    kind: str
    text: str
    value: str | None
    template: str | None
    name: str | None
    has_argument: bool
    items: tuple[str, ...] | None = None


@dataclass(frozen=True)
class PowerShellCommand:
    """One command invocation found anywhere in the parse tree."""

    name: str | None
    alias_of: str | None
    name_text: str
    invocation: str
    pipeline_id: int
    pipeline_index: int
    arguments: tuple[PowerShellArgument, ...]


@dataclass(frozen=True)
class PowerShellRedirection:
    """One output redirection."""

    kind: str
    target_text: str | None
    target: str | None


@dataclass(frozen=True)
class PowerShellParse:
    """The parts of a PowerShell parse tree that command policy needs.

    plain is True when the command is only pipelines of named commands with
    literal arguments (redirections are reported separately).
    """

    errors: tuple[str, ...]
    commands: tuple[PowerShellCommand, ...]
    redirections: tuple[PowerShellRedirection, ...]
    method_calls: tuple[str, ...]
    type_names: tuple[str, ...]
    plain: bool
    context_mutations: bool = False


def windows_powershell_executable() -> str:
    """Return the absolute path of Windows PowerShell.

    A bare "powershell" would let Windows find a same-named program in the
    current directory first, so a project could plant its own.
    """
    system_root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    return ntpath.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


@lru_cache(maxsize=256)
def parse_powershell(command: str) -> PowerShellParse:
    """Parse one command with PowerShell and return its analysed structure.

    Raises:
        PowerShellParserError: when PowerShell cannot be run or its output is invalid.
    """
    encoded_source = base64.b64encode(command.encode("utf-8")).decode("ascii")
    environment = dict(os.environ, **{SOURCE_ENVIRONMENT_VARIABLE: encoded_source})
    output = _run_parser(environment)
    try:
        document = json.loads(base64.b64decode(output, validate=True).decode("utf-8"))
        return _build_parse(document)
    except (ValueError, TypeError, KeyError) as error:
        raise PowerShellParserError(f"unexpected parser output ({error})") from error


def _run_parser(environment: dict[str, str]) -> bytes:
    """Run the parser script and return its base64 stdout."""
    arguments = [
        windows_powershell_executable(),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
        ENCODED_PARSER_SCRIPT,
    ]
    try:
        completed = subprocess.run(
            arguments,
            capture_output=True,
            env=environment,
            timeout=PARSER_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PowerShellParserError(f"PowerShell could not be started ({error})") from error
    if completed.returncode != 0:
        raise PowerShellParserError(f"PowerShell parser exited with code {completed.returncode}")
    return completed.stdout.strip()


def _build_parse(document: dict) -> PowerShellParse:
    """Convert the parser's JSON document into immutable records."""
    return PowerShellParse(
        errors=tuple(str(message) for message in document["errors"]),
        commands=tuple(_build_command(item) for item in document["commands"]),
        redirections=tuple(
            PowerShellRedirection(
                kind=str(item["kind"]),
                target_text=_optional_text(item["targetText"]),
                target=_optional_text(item["target"]),
            )
            for item in document["redirections"]
        ),
        method_calls=tuple(str(name) for name in document["methodCalls"]),
        type_names=tuple(str(name) for name in document["typeNames"]),
        plain=document["plain"] is True,
        context_mutations=document["contextMutations"] is True,
    )


def _build_command(item: dict) -> PowerShellCommand:
    """Convert one command record."""
    return PowerShellCommand(
        name=_optional_text(item["name"]),
        alias_of=_optional_text(item["aliasOf"]),
        name_text=str(item["nameText"]),
        invocation=str(item["invocation"]),
        pipeline_id=int(item["pipelineId"]),
        pipeline_index=int(item["pipelineIndex"]),
        arguments=tuple(
            PowerShellArgument(
                kind=str(argument["kind"]),
                text=str(argument["text"]),
                value=_optional_text(argument["value"]),
                template=_optional_text(argument["template"]),
                name=_optional_text(argument["name"]),
                has_argument=argument["hasArgument"] is True,
                items=_optional_items(argument["items"]),
            )
            for argument in item["arguments"]
        ),
    )


def _optional_text(value) -> str | None:
    """Return a string field, keeping JSON null as None."""
    return None if value is None else str(value)


def _optional_items(value) -> tuple[str, ...] | None:
    """Return a list of literal strings, keeping JSON null as None."""
    if value is None:
        return None
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return (str(value),)
