"""Tests for teach mode inline comment system.

Tests the three core behaviors:
1. is_teach_comment() correctly identifies teaching comment lines
2. strip_teach_comments() removes teaching lines and cleans up whitespace
3. print_code_content() with highlight_teach renders correctly
4. style_teach_content() highlights teach lines in streamed responses
5. TEACH_MODE_PROMPT contains correct inline instructions
"""

from radsim.output import (
    is_teach_comment,
    print_code_content,
    strip_teach_comments,
    style_teach_content,
)


class TestIsTeachComment:
    """Test detection of teaching comment lines."""

    def test_python_teach_comment(self):
        assert is_teach_comment("# 🎓 This is a teaching comment") is True

    def test_python_teach_comment_indented(self):
        assert is_teach_comment("    # 🎓 Indented teaching comment") is True

    def test_javascript_teach_comment(self):
        assert is_teach_comment("// 🎓 JS teaching comment") is True

    def test_sql_teach_comment(self):
        assert is_teach_comment("-- 🎓 SQL teaching comment") is True

    def test_css_teach_comment(self):
        assert is_teach_comment("/* 🎓 CSS teaching comment */") is True

    def test_html_teach_comment(self):
        assert is_teach_comment("<!-- 🎓 HTML teaching comment -->") is True

    def test_regular_comment_not_teach(self):
        assert is_teach_comment("# This is a normal comment") is False

    def test_regular_code_not_teach(self):
        assert is_teach_comment("x = 42") is False

    def test_empty_line_not_teach(self):
        assert is_teach_comment("") is False

    def test_whitespace_only_not_teach(self):
        assert is_teach_comment("   ") is False

    def test_graduation_cap_in_string_not_teach(self):
        assert is_teach_comment('print("🎓 hello")') is False

    def test_hash_without_emoji_not_teach(self):
        assert is_teach_comment("# regular comment here") is False


class TestStripTeachComments:
    """Test removal of teaching comments from code content."""

    def test_strips_python_teach_comments(self):
        content = """import os

# 🎓 load_dotenv reads .env into environment
from dotenv import load_dotenv

load_dotenv()
"""
        result = strip_teach_comments(content)
        assert "🎓" not in result
        assert "import os" in result
        assert "load_dotenv()" in result

    def test_strips_javascript_teach_comments(self):
        content = """const express = require('express');
// 🎓 Express is the most popular Node.js web framework
const app = express();
"""
        result = strip_teach_comments(content)
        assert "🎓" not in result
        assert "const express" in result
        assert "const app" in result

    def test_preserves_regular_comments(self):
        content = """# Regular comment stays
# 🎓 Teaching comment goes
x = 42  # Inline comment stays
"""
        result = strip_teach_comments(content)
        assert "Regular comment stays" in result
        assert "🎓" not in result
        assert "x = 42  # Inline comment stays" in result

    def test_removes_consecutive_blank_lines(self):
        content = """line_one = 1

# 🎓 Teaching comment

line_two = 2
"""
        result = strip_teach_comments(content)
        # Should not have double blank lines where teach comment was removed
        assert "\n\n\n" not in result
        assert "line_one = 1" in result
        assert "line_two = 2" in result

    def test_empty_content(self):
        assert strip_teach_comments("") == ""

    def test_content_with_no_teach_comments(self):
        content = "x = 1\ny = 2\n"
        assert strip_teach_comments(content) == content

    def test_all_teach_comments(self):
        content = "# 🎓 line one\n# 🎓 line two\n# 🎓 line three"
        result = strip_teach_comments(content)
        assert result.strip() == ""

    def test_mixed_languages(self):
        content = """# 🎓 Python style
import os
// 🎓 JS style
const x = 1;
-- 🎓 SQL style
SELECT * FROM users;
"""
        result = strip_teach_comments(content)
        assert "🎓" not in result
        assert "import os" in result
        assert "const x = 1;" in result
        assert "SELECT * FROM users;" in result


class TestStyleTeachContent:
    """Test styling of teach comments in agent responses."""

    def test_no_teach_content_unchanged(self):
        text = "Hello, here is some code."
        assert style_teach_content(text) == text

    def test_teach_lines_get_styled(self, monkeypatch):
        # Force color support for this test
        monkeypatch.setattr("radsim.output.supports_color", lambda: True)
        text = "# 🎓 This is a teaching line\nx = 42"
        result = style_teach_content(text)
        # The teach line should be wrapped in ANSI magenta
        assert "\033[95m" in result  # bright_magenta
        assert "x = 42" in result

    def test_non_teach_lines_unchanged(self):
        text = "regular line\n# 🎓 teach line\nanother regular"
        result = style_teach_content(text)
        lines = result.split("\n")
        assert lines[0] == "regular line"
        assert lines[2] == "another regular"


class TestPrintCodeContent:
    """Test code display with teaching highlights."""

    def test_basic_display(self, capsys):
        content = "x = 1\ny = 2\nz = 3"
        print_code_content(content, file_path="test.py")
        captured = capsys.readouterr()
        assert "test.py" in captured.out
        assert "3 lines" in captured.out

    def test_highlight_teach_shows_indicator(self, capsys):
        content = "# 🎓 Learn this\nx = 42"
        print_code_content(content, file_path="test.py", highlight_teach=True)
        captured = capsys.readouterr()
        assert "teaching annotations shown in magenta" in captured.out

    def test_highlight_teach_applies_color(self, capsys, monkeypatch):
        # Force color support for this test
        monkeypatch.setattr("radsim.output.supports_color", lambda: True)
        content = "# 🎓 Learn this\nx = 42"
        print_code_content(content, file_path="test.py", highlight_teach=True)
        captured = capsys.readouterr()
        # The teach line should have magenta ANSI code
        assert "\033[95m" in captured.out

    def test_no_highlight_no_teach_indicator(self, capsys):
        content = "# 🎓 Learn this\nx = 42"
        print_code_content(content, file_path="test.py", highlight_teach=False)
        captured = capsys.readouterr()
        assert "teaching annotations shown in magenta" not in captured.out

    def test_collapsed_mode(self, capsys):
        lines = [f"line_{i} = {i}" for i in range(20)]
        content = "\n".join(lines)
        print_code_content(content, collapsed=True)
        captured = capsys.readouterr()
        assert "more lines" in captured.out

    def test_max_lines_truncation(self, capsys):
        lines = [f"line_{i} = {i}" for i in range(50)]
        content = "\n".join(lines)
        print_code_content(content, max_lines=10)
        captured = capsys.readouterr()
        assert "more lines" in captured.out
        assert "type S" in captured.out


class TestTeachModePrompt:
    """Test that the teach mode prompt has correct inline instructions."""

    def test_prompt_mentions_inline_comments(self):
        from radsim.modes import TEACH_MODE_PROMPT

        assert "# 🎓" in TEACH_MODE_PROMPT

    def test_prompt_mentions_auto_stripping(self):
        from radsim.modes import TEACH_MODE_PROMPT

        assert "auto" in TEACH_MODE_PROMPT.lower() or "strip" in TEACH_MODE_PROMPT.lower()

    def test_prompt_mentions_multiple_languages(self):
        from radsim.modes import TEACH_MODE_PROMPT

        assert "// 🎓" in TEACH_MODE_PROMPT
        assert "<!-- 🎓" in TEACH_MODE_PROMPT
        assert "/* 🎓" in TEACH_MODE_PROMPT
        assert "-- 🎓" in TEACH_MODE_PROMPT

    def test_prompt_does_not_use_old_teach_tags(self):
        from radsim.modes import TEACH_MODE_PROMPT

        assert "[TEACH]" not in TEACH_MODE_PROMPT
        assert "[/TEACH]" not in TEACH_MODE_PROMPT

    def test_prompt_has_mandatory_language(self):
        from radsim.modes import TEACH_MODE_PROMPT

        # The strengthened prompt should include rejection/mandatory language
        prompt_upper = TEACH_MODE_PROMPT.upper()
        assert "MUST" in prompt_upper
        assert "REJECTED" in prompt_upper or "NON-NEGOTIABLE" in prompt_upper

    def test_mode_manager_registers_teach(self):
        from radsim.modes import ModeManager

        manager = ModeManager()
        mode = manager.get_mode("teach")
        assert mode is not None
        assert mode.name == "teach"
        assert mode.prompt_addition != ""


class TestTeachModeToggle:
    """Test that teach mode toggles correctly."""

    def test_toggle_on_off(self):
        from radsim.modes import ModeManager

        manager = ModeManager()
        is_active, msg = manager.toggle("teach")
        assert is_active is True
        assert "ON" in msg

        is_active, msg = manager.toggle("teach")
        assert is_active is False
        assert "OFF" in msg

    def test_prompt_additions_when_active(self):
        from radsim.modes import ModeManager

        manager = ModeManager()
        manager.toggle("teach")
        additions = manager.get_prompt_additions()
        assert "🎓" in additions
        assert "# 🎓" in additions

    def test_no_prompt_additions_when_inactive(self):
        from radsim.modes import ModeManager

        manager = ModeManager()
        additions = manager.get_prompt_additions()
        assert additions == ""


class TestTeachAnnotationTruncation:
    """Test that teach comment lines get wider display width."""

    def test_teach_comments_not_truncated_at_80(self, capsys, monkeypatch):
        """Teach lines up to 120 chars should NOT be truncated."""
        monkeypatch.setattr("radsim.output.supports_color", lambda: True)
        # Create a teach comment that's over 80 but under 120 chars
        # "# 🎓 " is 5 chars (emoji counts as 1 in Python)
        prefix = "# 🎓 "
        padding = "x" * (100 - len(prefix))
        long_teach = prefix + padding
        assert len(long_teach) == 100
        content = f"x = 1\n{long_teach}\ny = 2"
        print_code_content(content, file_path="test.py", highlight_teach=True)
        captured = capsys.readouterr()
        # The full teach line should appear without "..." truncation
        assert "x" * 94 in captured.out
        assert long_teach[:77] + "..." not in captured.out

    def test_regular_code_still_truncated_at_80(self, capsys):
        """Regular code lines over 80 chars should still be truncated."""
        long_code = "x = " + "1" * 100
        assert len(long_code) > 80
        content = long_code
        print_code_content(content, file_path="test.py", highlight_teach=True)
        captured = capsys.readouterr()
        assert "..." in captured.out

    def test_teach_comments_over_120_are_truncated(self, capsys, monkeypatch):
        """Teach lines over 120 chars should still be truncated (at 120)."""
        monkeypatch.setattr("radsim.output.supports_color", lambda: True)
        long_teach = "# 🎓 " + "x" * 130
        assert len(long_teach) > 120
        content = long_teach
        print_code_content(content, file_path="test.py", highlight_teach=True)
        captured = capsys.readouterr()
        assert "..." in captured.out
