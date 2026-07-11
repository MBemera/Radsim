"""Shell command execution for RadSim Agent.

Compatibility shim. The real implementation now lives in ``radsim.tools``
so there is a single source of truth for shell validation and execution.
Importing from here keeps older call sites working.
"""

from .tools.constants import DESTRUCTIVE_COMMANDS
from .tools.shell import run_shell_command
from .tools.validation import _check_for_dangerous_characters, validate_shell_command

__all__ = [
    "DESTRUCTIVE_COMMANDS",
    "run_shell_command",
    "validate_shell_command",
    "_check_for_dangerous_characters",
]
