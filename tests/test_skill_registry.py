"""Tests for the Dynamic Skill Registry."""

from pathlib import Path

from radsim.skill_registry import SkillRegistry


class TestSkillRegistry:
    """Test skill loading and caching."""

    def setup_method(self):
        # Use the real skills directory
        self.real_skills_dir = Path(__file__).parent.parent / "radsim" / "skills"
        self.registry = SkillRegistry(skills_dir=self.real_skills_dir)

    def test_list_available_skills(self):
        skills = self.registry.list_available_skills()
        assert isinstance(skills, list)
        assert len(skills) > 0
        assert "file_operations" in skills
        assert "search" in skills
        assert "git_operations" in skills

    def test_get_skill_docs(self):
        docs = self.registry.get_skill_docs("file_operations")
        assert docs is not None
        assert isinstance(docs, str)
        assert len(docs) > 0

    def test_get_nonexistent_skill(self):
        docs = self.registry.get_skill_docs("completely_fake_skill")
        assert docs is None

    def test_skill_caching(self):
        # Load once
        docs1 = self.registry.get_skill_docs("search")
        # Load again (should hit cache)
        docs2 = self.registry.get_skill_docs("search")
        assert docs1 is docs2  # Same object (cached)

    def test_clear_cache(self):
        self.registry.get_skill_docs("search")
        assert "search" in self.registry._cache

        self.registry.clear_cache()
        assert "search" not in self.registry._cache

    def test_get_skill_for_tool_direct_match(self):
        docs = self.registry.get_skill_for_tool("file_operations")
        assert docs is not None

    def test_get_skill_for_tool_prefix_mapping(self):
        """Tool names with prefixes should map to skill categories."""
        mappings = {
            "read_file": "file_operations",
            "write_file": "file_operations",
            "glob_files": "search",
            "grep_search": "search",
            "git_status": "git_operations",
            "run_shell_command": "shell_commands",
            "web_fetch": "web_tools",
            "browser_open": "browser_automation",
        }
        for tool_name, _expected_skill in mappings.items():
            docs = self.registry.get_skill_for_tool(tool_name)
            assert docs is not None, f"No docs found for tool: {tool_name}"

    def test_inject_context(self):
        prompt = "Original prompt"
        injected = self.registry.inject_context("read_file", prompt)
        assert "Original prompt" in injected
        assert "skill-context" in injected

    def test_inject_context_unknown_tool(self):
        prompt = "Original prompt"
        result = self.registry.inject_context("unknown_tool_xyz", prompt)
        assert result == prompt  # No injection for unknown tools


class TestSkillRegistryWithFakeDir:
    """Test with temporary skills directory."""

    def test_empty_skills_dir(self, tmp_path):
        registry = SkillRegistry(skills_dir=tmp_path)
        skills = registry.list_available_skills()
        assert skills == []

    def test_custom_skill_file(self, tmp_path):
        skill_file = tmp_path / "custom.md"
        skill_file.write_text("# Custom Skill\nDo the thing.")

        registry = SkillRegistry(skills_dir=tmp_path)
        skills = registry.list_available_skills()
        assert "custom" in skills

        docs = registry.get_skill_docs("custom")
        assert "Custom Skill" in docs

    def test_nonexistent_skills_dir(self, tmp_path):
        fake_dir = tmp_path / "nonexistent"
        registry = SkillRegistry(skills_dir=fake_dir)
        skills = registry.list_available_skills()
        assert skills == []
