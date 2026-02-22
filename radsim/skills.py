"""User-configurable skills for RadSim.

Skills are custom instructions that users can add to customize
how the agent behaves. They get injected into the system prompt.
"""

import json
from datetime import datetime
from pathlib import Path

# Storage location
SKILLS_FILE = Path.home() / ".radsim" / "skills.json"


def _ensure_dir():
    """Ensure the .radsim directory exists."""
    SKILLS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_skills() -> list:
    """Load skills from disk."""
    _ensure_dir()
    if SKILLS_FILE.exists():
        try:
            return json.loads(SKILLS_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            return []
    return []


def _save_skills(skills: list):
    """Save skills to disk."""
    _ensure_dir()
    SKILLS_FILE.write_text(json.dumps(skills, indent=2))


def add_skill(instruction: str, category: str = None) -> dict:
    """Add a new skill instruction.

    Args:
        instruction: The instruction text
        category: Optional category (e.g., 'code_style', 'language')

    Returns:
        dict with success status
    """
    if not instruction or not instruction.strip():
        return {"success": False, "error": "Instruction cannot be empty"}

    instruction = instruction.strip()

    # Check for duplicates
    skills = _load_skills()
    for skill in skills:
        if skill["instruction"].lower() == instruction.lower():
            return {"success": False, "error": "This skill already exists"}

    # Auto-detect category if not provided
    if not category:
        category = _detect_category(instruction)

    skill = {
        "instruction": instruction,
        "category": category,
        "added_at": datetime.now().isoformat(),
    }

    skills.append(skill)
    _save_skills(skills)

    return {"success": True, "skill": skill}


def _detect_category(instruction: str) -> str:
    """Auto-detect skill category from instruction text."""
    instruction_lower = instruction.lower()

    categories = {
        "code_style": ["indent", "spacing", "format", "style", "quote", "semicolon"],
        "language": ["typescript", "javascript", "python", "rust", "go", "java"],
        "framework": ["react", "vue", "angular", "django", "flask", "express"],
        "testing": ["test", "pytest", "jest", "spec", "coverage"],
        "documentation": ["comment", "docstring", "readme", "document"],
        "error_handling": ["error", "exception", "try", "catch", "handle"],
        "naming": ["naming", "snake_case", "camelcase", "variable", "function name"],
        "verbosity": ["concise", "brief", "detailed", "explain", "verbose"],
    }

    for category, keywords in categories.items():
        if any(kw in instruction_lower for kw in keywords):
            return category

    return "general"


def list_skills() -> list:
    """List all active skills.

    Returns:
        List of skill dictionaries
    """
    return _load_skills()


def remove_skill(index: int) -> dict:
    """Remove a skill by index.

    Args:
        index: 0-based index of skill to remove

    Returns:
        dict with success status and removed skill
    """
    skills = _load_skills()

    if index < 0 or index >= len(skills):
        return {"success": False, "error": f"Invalid index. Valid range: 1-{len(skills)}"}

    removed = skills.pop(index)
    _save_skills(skills)

    return {"success": True, "removed": removed["instruction"]}


def clear_skills() -> dict:
    """Remove all skills.

    Returns:
        dict with success status
    """
    _save_skills([])
    return {"success": True}


def get_skill_categories() -> list:
    """Get list of skill categories.

    Returns:
        List of category names
    """
    return [
        "code_style",
        "language",
        "framework",
        "testing",
        "documentation",
        "error_handling",
        "naming",
        "verbosity",
        "general",
    ]


def get_skills_for_prompt() -> str:
    """Get skills formatted for injection into system prompt.

    Returns:
        Formatted string of skills, or empty string if none
    """
    skills = _load_skills()
    if not skills:
        return ""

    lines = ["\n## User Skills & Preferences\n"]
    lines.append("The user has configured the following instructions:\n")

    for skill in skills:
        lines.append(f"- {skill['instruction']}")

    lines.append("\nFollow these instructions in all responses.\n")

    return "\n".join(lines)


def get_skills_summary() -> dict:
    """Get summary of skills for display.

    Returns:
        dict with count and categories
    """
    skills = _load_skills()
    categories = {}
    for skill in skills:
        cat = skill.get("category", "general")
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "total": len(skills),
        "by_category": categories,
    }


def extract_skills_from_markdown(content: str) -> list[str]:
    """Extract actionable skill instructions from markdown content.

    Parses headings, bullet points, numbered lists, and code blocks
    to find discrete, actionable instructions that can be saved as skills.

    Args:
        content: Raw markdown text

    Returns:
        List of extracted instruction strings
    """
    instructions = []
    lines = content.split("\n")

    for line in lines:
        stripped = line.strip()

        # Skip empty lines, headings, code fences, and non-instruction lines
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("```"):
            continue
        if stripped.startswith("---"):
            continue
        if stripped.startswith("!["):
            continue

        # Extract bullet point content (-, *, +)
        if stripped.startswith(("-", "*", "+")) and len(stripped) > 2:
            instruction = stripped[1:].strip()
            # Remove sub-bullet markers like "- [ ]" or "- [x]"
            if instruction.startswith("[ ]") or instruction.startswith("[x]"):
                instruction = instruction[3:].strip()
            if _is_actionable_instruction(instruction):
                instructions.append(instruction)
            continue

        # Extract numbered list items (1., 2., etc.)
        if len(stripped) > 2 and stripped[0].isdigit() and "." in stripped[:4]:
            dot_index = stripped.index(".")
            instruction = stripped[dot_index + 1 :].strip()
            if _is_actionable_instruction(instruction):
                instructions.append(instruction)
            continue

    return instructions


def _is_actionable_instruction(text: str) -> bool:
    """Check if a text string is an actionable skill instruction.

    Filters out descriptions, examples, and non-actionable content.
    An actionable instruction tells the agent HOW to behave.

    Args:
        text: The candidate instruction text

    Returns:
        True if the text looks like an actionable instruction
    """
    if len(text) < 10:
        return False
    if len(text) > 200:
        return False

    # Must contain action-oriented words
    action_words = [
        "use", "always", "never", "prefer", "avoid", "ensure", "include",
        "add", "write", "follow", "keep", "make", "apply", "require",
        "should", "must", "do not", "don't",
    ]
    text_lower = text.lower()
    has_action = any(word in text_lower for word in action_words)

    return has_action


def learn_skills_from_file(file_path: str) -> dict:
    """Read a markdown file and extract learnable skills.

    Does NOT save anything - returns extracted skills for user confirmation.

    Args:
        file_path: Path to the markdown file

    Returns:
        dict with extracted skills list or error
    """
    target_path = Path(file_path).expanduser()

    if not target_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    if target_path.suffix.lower() not in (".md", ".markdown", ".txt"):
        return {"success": False, "error": "Only .md, .markdown, and .txt files are supported"}

    try:
        content = target_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return {"success": False, "error": f"Failed to read file: {error}"}

    extracted = extract_skills_from_markdown(content)

    if not extracted:
        return {
            "success": True,
            "skills": [],
            "message": "No actionable skills found in this file.",
        }

    # Filter out duplicates against existing skills
    existing_skills = _load_skills()
    existing_instructions = {s["instruction"].lower() for s in existing_skills}
    new_skills = [s for s in extracted if s.lower() not in existing_instructions]

    return {
        "success": True,
        "skills": new_skills,
        "total_found": len(extracted),
        "duplicates_skipped": len(extracted) - len(new_skills),
    }


def confirm_and_save_skill(instruction: str, source: str = "learned") -> dict:
    """Save a single skill after user confirmation.

    This is called one-at-a-time after the user confirms each skill.

    Args:
        instruction: The skill instruction text
        source: Where the skill came from (learned, markdown, user)

    Returns:
        dict with success status
    """
    category = _detect_category(instruction)

    skills = _load_skills()

    # Double-check for duplicates
    for skill in skills:
        if skill["instruction"].lower() == instruction.lower():
            return {"success": False, "error": "This skill already exists"}

    skill = {
        "instruction": instruction,
        "category": category,
        "source": source,
        "added_at": datetime.now().isoformat(),
    }

    skills.append(skill)
    _save_skills(skills)

    return {"success": True, "skill": skill}
