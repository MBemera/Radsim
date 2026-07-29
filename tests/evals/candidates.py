"""The two prompt candidates the behavioural matrix compares.

Candidate A is the prompt as it shipped before the policy-first rewrite, read
straight out of Git so it cannot drift. Candidate B is what the working tree
ships today. Both are the repository-controlled surface only: no skills, no
project memory, no custom text.
"""

import ast
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# The commit the hardening plan pins as the pre-rewrite baseline.
PINNED_BASELINE_COMMIT = "76b2ec7"

# The fragments that existed at the baseline commit, in composition order.
PINNED_FRAGMENT_NAMES = ("personality.md", "tool_use.md", "response_style.md")

CANDIDATE_NAMES = ("A", "B")


class CandidateError(RuntimeError):
    """Raised when a candidate prompt cannot be reconstructed."""


def read_file_at_commit(path, commit=PINNED_BASELINE_COMMIT):
    """Return one repository file's contents as of a commit."""
    result = subprocess.run(
        ["git", "-C", str(REPOSITORY_ROOT), "show", f"{commit}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise CandidateError(f"Cannot read {path} at {commit}: {result.stderr.strip()}")
    return result.stdout


def read_string_constant(source, name):
    """Return one module-level string constant without importing the module.

    Importing two versions of ``radsim.prompts`` into one process is not
    possible, and executing an old revision's code to read a string is more
    trust than this needs.
    """
    module = ast.parse(source)
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return node.value.value
    raise CandidateError(f"No string constant named {name}")


def build_candidate_a(commit=PINNED_BASELINE_COMMIT):
    """Compose the pre-rewrite prompt: base policy plus the three fragments."""
    base = read_string_constant(read_file_at_commit("radsim/prompts.py", commit), "RADSIM_SYSTEM_PROMPT")
    fragments = [
        read_file_at_commit(f"radsim/prompt_fragments/{name}", commit)
        for name in PINNED_FRAGMENT_NAMES
    ]
    return "\n".join([base, *fragments])


def build_candidate_b():
    """Return the repository-controlled prompt the working tree ships."""
    from radsim.prompts import get_static_prompt

    return get_static_prompt()


def get_candidate(name):
    """Return one candidate prompt by name.

    Returns:
        (label: str, prompt: str)
    """
    builders = {"A": build_candidate_a, "B": build_candidate_b}
    if name not in builders:
        raise CandidateError(f"Unknown candidate '{name}'. Choose from: {', '.join(CANDIDATE_NAMES)}")
    return name, builders[name]()
