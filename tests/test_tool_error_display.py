"""Failed tool calls must show the human the reason, readably."""

from radsim.output import _extract_error_text, _result_summary, _truncate_at_word


class TestErrorExtraction:
    """Errors keep their actionable detail instead of a mid-word cut."""

    def test_short_error_passes_through_whole(self):
        result = {"success": False, "error": "File not found: config.json"}
        assert _extract_error_text(result) == "File not found: config.json"

    def test_long_error_keeps_words_intact(self):
        long_reason = (
            "Package validation failed: this package was published 3 days ago "
            "by a maintainer with no other packages; verify the exact name on "
            "npmjs.com before installing " + "x" * 200
        )
        extracted = _extract_error_text({"success": False, "error": long_reason})
        assert "npmjs.com" in extracted
        assert not extracted.split("\n")[0].endswith("x")  # no mid-word cut

    def test_multiline_errors_show_up_to_three_lines(self):
        error = "line one\nline two\nline three\nline four\nline five"
        extracted = _extract_error_text({"success": False, "error": error})
        lines = extracted.split("\n")
        assert lines[:3] == ["line one", "line two", "line three"]
        assert "(2 more lines)" in lines[3]

    def test_stderr_used_when_no_error_key(self):
        result = {"success": False, "stderr": "npm ERR! code E404"}
        assert "E404" in _extract_error_text(result)

    def test_no_error_returns_none(self):
        assert _extract_error_text({"success": True}) is None


class TestWordBoundaryTruncation:
    def test_short_text_unchanged(self):
        assert _truncate_at_word("hello world", 50) == "hello world"

    def test_cut_lands_on_a_word_boundary(self):
        text = "the quick brown fox jumps over the lazy dog"
        truncated = _truncate_at_word(text, 20)
        assert len(truncated) <= 20
        remainder = truncated.rstrip("….")
        assert text.startswith(remainder)
        assert remainder.endswith(("the", "quick", "brown", "fox"))

    def test_single_long_word_still_truncates(self):
        truncated = _truncate_at_word("a" * 100, 20)
        assert len(truncated) <= 20


class TestResultSummary:
    """The result column never renders empty on failure."""

    def test_failure_without_returncode_says_error(self):
        assert _result_summary("read_file", {"success": False, "error": "nope"}) == "error"

    def test_failure_with_returncode_keeps_exit_code(self):
        summary = _result_summary("run_shell_command", {"success": False, "returncode": 1})
        assert summary == "exit 1"


class TestHelpHeaderAlignment:
    def test_help_box_borders_line_up(self, capsys, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        from radsim.output import print_help

        print_help()
        lines = capsys.readouterr().out.splitlines()
        box_lines = [line for line in lines if any(ch in line for ch in "╭│╰")][:3]
        assert len(box_lines) == 3
        top, middle, bottom = (line.rstrip() for line in box_lines)
        assert len(top) == len(middle) == len(bottom)

    def test_help_detail_box_borders_line_up(self, capsys, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        from radsim.output import print_help_detail

        print_help_detail("hook")
        lines = capsys.readouterr().out.splitlines()
        box_lines = [line for line in lines if any(ch in line for ch in "╭│╰")][:4]
        assert len(box_lines) == 4
        widths = {len(line.rstrip()) for line in box_lines}
        assert len(widths) == 1
