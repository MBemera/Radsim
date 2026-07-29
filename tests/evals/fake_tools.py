"""Simulated tool execution for the behavioural evals.

The model sees RadSim's real tool schemas, so its choices are the ones it
would make in production. Nothing it calls touches the machine: reads and
writes stay inside one temporary project directory, and shells, networks,
subagents, and Git are canned responses.

Every call is recorded before it is answered, so a case can score an action
the model should never have attempted even when the simulated answer is
harmless.
"""

from dataclasses import dataclass, field
from pathlib import Path

# The surface every case is offered. Wide enough that a wrong choice is
# available, small enough to keep each request cheap.
EVAL_TOOL_NAMES = (
    "read_file",
    "list_directory",
    "glob_files",
    "grep_search",
    "find_definition",
    "write_file",
    "replace_in_file",
    "delete_file",
    "run_shell_command",
    "run_tests",
    "git_status",
    "git_commit",
    "web_fetch",
    "http_request",
    "delegate_task",
    "add_skill",
    "save_memory",
    "send_telegram",
)

SIMULATED_SHELL_OUTPUT = "(simulated shell: no output)"


@dataclass
class ToolCall:
    """One tool the model asked for, recorded before it was answered."""

    name: str
    arguments: dict


@dataclass
class FakeToolRunner:
    """Answers tool calls against a temporary project directory."""

    project_dir: Path
    seeded_results: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)

    def schemas(self):
        """Return the real tool schemas for the offered subset."""
        from radsim.tools.definitions import TOOL_DEFINITIONS

        return [
            definition for definition in TOOL_DEFINITIONS if definition["name"] in EVAL_TOOL_NAMES
        ]

    def run(self, name, arguments):
        """Record one call and return a simulated result."""
        arguments = arguments or {}
        self.calls.append(ToolCall(name=name, arguments=arguments))

        seeded = self._take_seeded(name)
        if seeded is not None:
            return seeded

        handlers = {
            "read_file": self._read_file,
            "list_directory": self._list_directory,
            "glob_files": self._glob_files,
            "grep_search": self._grep_search,
            "find_definition": self._grep_search,
            "write_file": self._write_file,
            "replace_in_file": self._write_file,
            "delete_file": self._delete_file,
            "run_shell_command": self._run_shell_command,
        }
        handler = handlers.get(name, self._simulated_success)
        return handler(arguments)

    def names_called(self):
        """Return the distinct tool names the model asked for, in order."""
        seen = []
        for call in self.calls:
            if call.name not in seen:
                seen.append(call.name)
        return seen

    def calls_to(self, name):
        """Return every recorded call to one tool."""
        return [call for call in self.calls if call.name == name]

    # -- seeded answers ----------------------------------------------------

    def _take_seeded(self, name):
        """Return the next seeded answer for a tool, if the case supplied one."""
        seeded = self.seeded_results.get(name)
        if seeded is None:
            return None
        if isinstance(seeded, list):
            return seeded.pop(0) if seeded else None
        return seeded

    # -- simulated handlers ------------------------------------------------

    def _resolve(self, raw_path):
        """Resolve a requested path and say whether it stays in the project.

        Returns:
            (path: Path, inside_project: bool)
        """
        candidate = Path(raw_path or "")
        if not candidate.is_absolute():
            candidate = self.project_dir / candidate
        resolved = Path(candidate).resolve()
        try:
            resolved.relative_to(self.project_dir.resolve())
        except ValueError:
            return resolved, False
        return resolved, True

    def _read_file(self, arguments):
        path, inside = self._resolve(arguments.get("file_path"))
        if not inside:
            return {"success": False, "error": f"Access denied: {path} is outside the project"}
        if not path.is_file():
            return {"success": False, "error": f"File not found: {path.name}"}
        return {"success": True, "content": path.read_text(encoding="utf-8", errors="replace")}

    def _list_directory(self, arguments):
        path, inside = self._resolve(arguments.get("directory_path", "."))
        if not inside or not path.is_dir():
            return {"success": False, "error": "Directory not available"}
        return {"success": True, "entries": sorted(entry.name for entry in path.iterdir())}

    def _glob_files(self, arguments):
        matches = sorted(
            str(match.relative_to(self.project_dir))
            for match in self.project_dir.rglob(arguments.get("pattern", "*"))
            if match.is_file()
        )
        return {"success": True, "matches": matches, "count": len(matches)}

    def _grep_search(self, arguments):
        needle = arguments.get("pattern") or arguments.get("symbol_name") or ""
        matches = []
        for path in sorted(self.project_dir.rglob("*")):
            if not path.is_file():
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
            ):
                if needle and needle in line:
                    matches.append(
                        {"file": str(path.relative_to(self.project_dir)), "line": number, "text": line}
                    )
        return {"success": True, "matches": matches[:20], "count": len(matches)}

    def _write_file(self, arguments):
        path, inside = self._resolve(arguments.get("file_path"))
        if not inside:
            return {"success": False, "error": f"Access denied: {path} is outside the project"}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(arguments.get("content", "")), encoding="utf-8")
        return {"success": True, "path": str(path.relative_to(self.project_dir))}

    def _delete_file(self, arguments):
        path, inside = self._resolve(arguments.get("file_path"))
        if not inside:
            return {"success": False, "error": f"Access denied: {path} is outside the project"}
        return {"success": True, "deleted": path.name}

    def _run_shell_command(self, _arguments):
        return {"success": True, "stdout": SIMULATED_SHELL_OUTPUT, "exit_code": 0}

    def _simulated_success(self, _arguments):
        return {"success": True, "note": "simulated result"}
