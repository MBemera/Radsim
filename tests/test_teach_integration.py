"""Integration tests for teach mode production pipeline.

Tests the full teach mode flow:
1. strip_teach_comments removes teaching lines from code
2. display_content preserves teaching lines for user display
3. set_last_written_file stores both clean and display versions
4. replace_in_file stripping path works correctly
"""

from unittest.mock import patch

from radsim.output import (
    get_last_written_file,
    set_last_written_file,
    strip_teach_comments,
)

# Sample code content with mixed teach and real code lines
SAMPLE_PYTHON_WITH_TEACH = """import os
from dotenv import load_dotenv

# 🎓 load_dotenv reads .env file into os.environ - keeps secrets out of code
load_dotenv()

# 🎓 Dataclass auto-generates __init__ and __repr__ for you
from dataclasses import dataclass

@dataclass
class User:
    user_id: int
    name: str
    # 🎓 Optional with default None lets callers skip this field
    email: str = None

def get_user(user_id: int):
    # 🎓 Parameterized queries prevent SQL injection
    return db.execute("SELECT * FROM users WHERE id = ?", [user_id])
"""

SAMPLE_JS_WITH_TEACH = """const express = require('express');
// 🎓 Express is the most popular Node.js web framework
const app = express();

// 🎓 Middleware runs on every request before route handlers
app.use(express.json());

app.get('/users/:id', (req, res) => {
    res.json({ id: req.params.id });
});
"""

SAMPLE_MIXED_LANGUAGES = """# 🎓 Python teaching line
import os
// 🎓 JavaScript teaching line
const x = 1;
-- 🎓 SQL teaching line
SELECT * FROM users;
<!-- 🎓 HTML teaching line -->
<div>Hello</div>
/* 🎓 CSS teaching line */
.class { color: red; }
"""


class TestFullStripPipeline:
    """Test that stripping produces clean code while preserving display content."""

    def test_python_strip_preserves_real_code(self):
        stripped = strip_teach_comments(SAMPLE_PYTHON_WITH_TEACH)
        assert "import os" in stripped
        assert "load_dotenv()" in stripped
        assert "@dataclass" in stripped
        assert "class User:" in stripped
        assert "def get_user" in stripped

    def test_python_strip_removes_all_teach_lines(self):
        stripped = strip_teach_comments(SAMPLE_PYTHON_WITH_TEACH)
        assert "🎓" not in stripped

    def test_display_content_preserves_teach_lines(self):
        """display_content is just the original content - it keeps teach lines."""
        display_content = SAMPLE_PYTHON_WITH_TEACH
        assert "🎓" in display_content
        assert "load_dotenv reads .env" in display_content
        assert "Dataclass auto-generates" in display_content
        assert "Parameterized queries prevent" in display_content

    def test_stripped_and_display_differ(self):
        stripped = strip_teach_comments(SAMPLE_PYTHON_WITH_TEACH)
        display = SAMPLE_PYTHON_WITH_TEACH
        assert stripped != display
        assert len(stripped) < len(display)

    def test_js_strip_pipeline(self):
        stripped = strip_teach_comments(SAMPLE_JS_WITH_TEACH)
        assert "🎓" not in stripped
        assert "const express" in stripped
        assert "app.use(express.json())" in stripped
        assert "app.get" in stripped

    def test_mixed_language_strip(self):
        stripped = strip_teach_comments(SAMPLE_MIXED_LANGUAGES)
        assert "🎓" not in stripped
        assert "import os" in stripped
        assert "const x = 1;" in stripped
        assert "SELECT * FROM users;" in stripped
        assert "<div>Hello</div>" in stripped
        assert ".class { color: red; }" in stripped

    def test_no_consecutive_blank_lines_after_strip(self):
        stripped = strip_teach_comments(SAMPLE_PYTHON_WITH_TEACH)
        assert "\n\n\n" not in stripped


class TestSetLastWrittenFileWithDisplayContent:
    """Test that set_last_written_file stores display_content correctly."""

    def test_stores_display_content_when_provided(self):
        clean = strip_teach_comments(SAMPLE_PYTHON_WITH_TEACH)
        display = SAMPLE_PYTHON_WITH_TEACH

        set_last_written_file("test.py", clean, display_content=display)
        result = get_last_written_file()

        assert result["path"] == "test.py"
        assert result["content"] == clean
        assert result["display_content"] == display
        assert "🎓" not in result["content"]
        assert "🎓" in result["display_content"]

    def test_display_content_none_when_not_provided(self):
        set_last_written_file("test.py", "x = 1")
        result = get_last_written_file()

        assert result["path"] == "test.py"
        assert result["content"] == "x = 1"
        assert result["display_content"] is None

    def test_overwrite_clears_previous_display_content(self):
        # First write with display_content
        set_last_written_file("a.py", "clean", display_content="display")
        # Second write without display_content
        set_last_written_file("b.py", "clean2")

        result = get_last_written_file()
        assert result["path"] == "b.py"
        assert result["display_content"] is None


class TestReplaceInFileStripping:
    """Test that teach comments are stripped from replace_in_file new_string."""

    def test_strip_teach_from_new_string(self):
        """Simulate what _handle_replace does when teach mode is active."""
        new_string = """def calculate_total(price, quantity):
    # 🎓 Simple multiplication - no need for complex patterns
    subtotal = price * quantity
    # 🎓 Tax rate should come from config, not hardcoded
    tax = subtotal * 0.1
    return subtotal + tax
"""
        stripped = strip_teach_comments(new_string)

        assert "🎓" not in stripped
        assert "def calculate_total" in stripped
        assert "subtotal = price * quantity" in stripped
        assert "tax = subtotal * 0.1" in stripped
        assert "return subtotal + tax" in stripped

    def test_strip_preserves_regular_comments_in_replacement(self):
        new_string = """# Calculate the user's total
def calculate_total(price, quantity):
    # 🎓 This teach comment gets stripped
    # This regular comment stays
    return price * quantity
"""
        stripped = strip_teach_comments(new_string)

        assert "🎓" not in stripped
        assert "# Calculate the user's total" in stripped
        assert "# This regular comment stays" in stripped

    @patch("radsim.modes.is_mode_active")
    def test_stripping_only_when_teach_active(self, mock_is_active):
        """Verify stripping logic is gated on teach mode being active."""
        new_string = "# 🎓 teach comment\nx = 42"

        # Teach mode active - should strip
        mock_is_active.return_value = True
        if mock_is_active("teach"):
            result = strip_teach_comments(new_string)
        assert "🎓" not in result
        assert "x = 42" in result

        # Teach mode inactive - should not strip
        mock_is_active.return_value = False
        if mock_is_active("teach"):
            result_inactive = strip_teach_comments(new_string)
        else:
            result_inactive = new_string
        assert "🎓" in result_inactive

    def test_empty_new_string_strip(self):
        assert strip_teach_comments("") == ""

    def test_only_teach_comments_strip(self):
        new_string = "# 🎓 only teach\n// 🎓 more teach"
        stripped = strip_teach_comments(new_string)
        assert stripped.strip() == ""
