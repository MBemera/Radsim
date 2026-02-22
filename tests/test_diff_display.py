"""Tests for the diff display module."""


from radsim.diff_display import count_changes, get_diff_summary, show_diff


class TestCountChanges:
    """Test line counting."""

    def test_no_changes(self):
        lines = ["a", "b", "c"]
        additions, deletions = count_changes(lines, lines)
        assert additions == 0
        assert deletions == 0

    def test_additions_only(self):
        old = ["a", "b"]
        new = ["a", "b", "c", "d"]
        additions, deletions = count_changes(old, new)
        assert additions == 2
        assert deletions == 0

    def test_deletions_only(self):
        old = ["a", "b", "c", "d"]
        new = ["a", "b"]
        additions, deletions = count_changes(old, new)
        assert additions == 0
        assert deletions == 2

    def test_mixed_changes(self):
        old = ["a", "b", "c"]
        new = ["a", "x", "c"]
        additions, deletions = count_changes(old, new)
        assert additions == 1
        assert deletions == 1

    def test_empty_to_content(self):
        additions, deletions = count_changes([], ["a", "b"])
        assert additions == 2
        assert deletions == 0

    def test_content_to_empty(self):
        additions, deletions = count_changes(["a", "b"], [])
        assert additions == 0
        assert deletions == 2


class TestShowDiff:
    """Test diff output generation."""

    def test_no_changes_returns_empty(self):
        result = show_diff("hello\nworld", "hello\nworld")
        assert result == ""

    def test_none_inputs_handled(self):
        result = show_diff(None, "hello")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_both_none_returns_empty(self):
        result = show_diff(None, None)
        assert result == ""

    def test_additions_shown(self):
        result = show_diff("line1\n", "line1\nline2\n")
        assert "line2" in result

    def test_deletions_shown(self):
        result = show_diff("line1\nline2\n", "line1\n")
        assert "line2" in result

    def test_filename_in_output(self):
        result = show_diff("old", "new", filename="test.py")
        assert "test.py" in result


class TestGetDiffSummary:
    """Test diff summary generation."""

    def test_no_changes(self):
        result = get_diff_summary("same", "same")
        assert result == "No changes"

    def test_additions(self):
        result = get_diff_summary("a\n", "a\nb\n")
        assert "+1" in result

    def test_none_handled(self):
        result = get_diff_summary(None, "hello")
        assert isinstance(result, str)
