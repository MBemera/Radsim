"""Terminal markdown rendering: decoration becomes prose, code stays exact."""

import pytest

from radsim import output
from radsim.output import render_markdown_line, render_markdown_text


@pytest.fixture(autouse=True)
def plain_text_colors(monkeypatch):
    """Disable ANSI styling so assertions see the structural transforms."""
    monkeypatch.setattr(output, "supports_color", lambda: False)


class TestMarkdownDecoration:
    """Markdown noise must disappear from terminal output."""

    def test_header_hashes_are_stripped(self):
        assert render_markdown_text("### 1. Persistent Memory") == "1. Persistent Memory"

    def test_horizontal_rule_becomes_blank_line(self):
        assert render_markdown_text("before\n---\nafter") == "before\n\nafter"

    def test_bold_markers_are_removed(self):
        assert render_markdown_text("I can **remember** things") == "I can remember things"

    def test_inline_code_backticks_are_removed(self):
        assert render_markdown_text("run `save_memory` now") == "run save_memory now"

    def test_table_rows_flatten_to_columns(self):
        table = "| # | Skill |\n|---|-------|\n| 1 | Always use pytest |"
        assert render_markdown_text(table) == "#  Skill\n\n1  Always use pytest"

    def test_plain_prose_is_untouched(self):
        text = "Lead with the answer.\n- keep lists simple\n- 3 to 7 items"
        assert render_markdown_text(text) == text

    def test_dash_bullet_is_not_treated_as_rule(self):
        assert render_markdown_text("- one item") == "- one item"


class TestCodeBlocksStayExact:
    """Real code must remain copy-pasteable, byte for byte."""

    def test_code_inside_fences_is_untouched(self):
        block = '```python\nprint("**not bold**")\nvalue = {"a": 1}\n```'
        assert render_markdown_text(block) == block

    def test_header_syntax_inside_fences_is_untouched(self):
        block = "```\n# a shell comment, not a header\n```"
        assert render_markdown_text(block) == block

    def test_fence_state_carries_across_lines(self):
        _, in_code = render_markdown_line("```python", False)
        assert in_code is True
        rendered, in_code = render_markdown_line("### not a header here", True)
        assert rendered == "### not a header here"
        _, in_code = render_markdown_line("```", True)
        assert in_code is False


class TestStreamingState:
    """The streaming path must track fences and flush cleanly."""

    def test_finish_stream_flushes_partial_line(self, capsys):
        output.reset_stream_state()
        output.print_stream_chunk("first line\npartial **bold**")
        output.finish_stream()
        captured = capsys.readouterr().out
        assert "first line\n" in captured
        assert "partial bold" in captured

    def test_reset_clears_code_fence_state(self, capsys):
        output.reset_stream_state()
        output.print_stream_chunk("```\n")
        output.reset_stream_state()
        output.print_stream_chunk("### header\n")
        captured = capsys.readouterr().out
        assert "header\n" in captured
        assert "### header" not in captured
