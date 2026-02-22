"""Dynamic Skill Registry - Just-in-time context loading.

RadSim Principle: Just-In-Time Context Loading
Only load what you need, when you need it. Don't preload everything.

Skills are markdown files in the skills/ directory that contain:
- Tool usage instructions
- Examples
- Best practices
- Common patterns

When a tool is invoked, its skill docs are loaded into context.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Skills directory location
SKILLS_DIR = Path(__file__).parent / "skills"


class SkillRegistry:
    """Registry for dynamically loading skill documentation.

    Loads tool/skill documentation only when needed to save context window.
    """

    def __init__(self, skills_dir: Path = None):
        self.skills_dir = skills_dir or SKILLS_DIR
        self._cache: dict[str, str] = {}
        self._available_skills: list[str] | None = None

    def list_available_skills(self) -> list[str]:
        """List all available skill names."""
        if self._available_skills is None:
            self._available_skills = []
            if self.skills_dir.exists():
                for file in self.skills_dir.glob("*.md"):
                    skill_name = file.stem
                    self._available_skills.append(skill_name)
        return self._available_skills

    def get_skill_docs(self, skill_name: str) -> str | None:
        """Load skill documentation by name.

        Returns None if skill doesn't exist.
        Uses caching to avoid re-reading files.
        """
        # Check cache first
        if skill_name in self._cache:
            return self._cache[skill_name]

        # Look for skill file
        skill_file = self.skills_dir / f"{skill_name}.md"

        if not skill_file.exists():
            return None

        try:
            content = skill_file.read_text(encoding="utf-8")
            self._cache[skill_name] = content
            return content
        except Exception:
            logger.debug(f"Failed to load skill file: {skill_file}")
            return None

    def get_skill_for_tool(self, tool_name: str) -> str | None:
        """Get skill docs for a specific tool.

        Maps tool names to their skill documentation.
        """
        # Direct match
        docs = self.get_skill_docs(tool_name)
        if docs:
            return docs

        # Try common prefixes/categories
        category_mappings = {
            "read_": "file_operations",
            "write_": "file_operations",
            "replace_": "file_operations",
            "delete_": "file_operations",
            "rename_": "file_operations",
            "list_": "directory_operations",
            "create_": "directory_operations",
            "glob_": "search",
            "grep_": "search",
            "search_": "search",
            "git_": "git_operations",
            "run_": "shell_commands",
            "web_": "web_tools",
            "browser_": "browser_automation",
        }

        for prefix, category in category_mappings.items():
            if tool_name.startswith(prefix):
                return self.get_skill_docs(category)

        return None

    def inject_context(self, tool_name: str, current_prompt: str) -> str:
        """Inject relevant skill docs into the prompt.

        Called before tool execution to provide context.
        """
        skill_docs = self.get_skill_for_tool(tool_name)

        if not skill_docs:
            return current_prompt

        # Inject skill docs as context
        injected = f"""
<skill-context tool="{tool_name}">
{skill_docs}
</skill-context>

{current_prompt}
"""
        return injected

    def clear_cache(self):
        """Clear the skill documentation cache."""
        self._cache = {}
        self._available_skills = None


# Global registry instance
_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    """Get the global skill registry instance."""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry


def load_skill(skill_name: str) -> str | None:
    """Convenience function to load a skill by name."""
    return get_skill_registry().get_skill_docs(skill_name)


def load_skill_for_tool(tool_name: str) -> str | None:
    """Convenience function to load skill docs for a tool."""
    return get_skill_registry().get_skill_for_tool(tool_name)
