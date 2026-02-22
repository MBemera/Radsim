"""Tests for the interactive menu utility module."""

from unittest.mock import patch

from radsim.menu import interactive_menu, interactive_menu_loop, safe_input


class TestSafeInput:
    def test_returns_user_input(self):
        with patch("builtins.input", return_value="hello"):
            result = safe_input("prompt: ")
            assert result == "hello"

    def test_strips_whitespace(self):
        with patch("builtins.input", return_value="  hello  "):
            result = safe_input("prompt: ")
            assert result == "hello"

    def test_returns_none_on_q(self):
        with patch("builtins.input", return_value="q"):
            result = safe_input("prompt: ")
            assert result is None

    def test_returns_none_on_quit(self):
        with patch("builtins.input", return_value="quit"):
            result = safe_input("prompt: ")
            assert result is None

    def test_returns_none_on_exit(self):
        with patch("builtins.input", return_value="exit"):
            result = safe_input("prompt: ")
            assert result is None

    def test_returns_none_on_back(self):
        with patch("builtins.input", return_value="back"):
            result = safe_input("prompt: ")
            assert result is None

    def test_returns_none_on_keyboard_interrupt(self):
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            result = safe_input("prompt: ")
            assert result is None

    def test_returns_none_on_eof(self):
        with patch("builtins.input", side_effect=EOFError):
            result = safe_input("prompt: ")
            assert result is None

    def test_case_insensitive_quit(self):
        with patch("builtins.input", return_value="Q"):
            result = safe_input("prompt: ")
            assert result is None

        with patch("builtins.input", return_value="QUIT"):
            result = safe_input("prompt: ")
            assert result is None


class TestInteractiveMenu:
    OPTIONS = [
        ("overview", "Score overview"),
        ("budget", "Set budget"),
        ("report", "Full report"),
    ]

    def test_select_by_number(self):
        with patch("radsim.menu.safe_input", return_value="1"):
            result = interactive_menu("TEST", self.OPTIONS)
            assert result == "overview"

    def test_select_second_option(self):
        with patch("radsim.menu.safe_input", return_value="2"):
            result = interactive_menu("TEST", self.OPTIONS)
            assert result == "budget"

    def test_select_third_option(self):
        with patch("radsim.menu.safe_input", return_value="3"):
            result = interactive_menu("TEST", self.OPTIONS)
            assert result == "report"

    def test_select_by_key_name(self):
        with patch("radsim.menu.safe_input", return_value="budget"):
            result = interactive_menu("TEST", self.OPTIONS)
            assert result == "budget"

    def test_select_by_key_case_insensitive(self):
        with patch("radsim.menu.safe_input", return_value="REPORT"):
            result = interactive_menu("TEST", self.OPTIONS)
            assert result == "report"

    def test_returns_none_on_cancel(self):
        with patch("radsim.menu.safe_input", return_value=None):
            result = interactive_menu("TEST", self.OPTIONS)
            assert result is None

    def test_invalid_number_returns_none(self):
        with patch("radsim.menu.safe_input", return_value="99"):
            result = interactive_menu("TEST", self.OPTIONS)
            assert result is None

    def test_invalid_text_returns_none(self):
        with patch("radsim.menu.safe_input", return_value="garbage"):
            result = interactive_menu("TEST", self.OPTIONS)
            assert result is None

    def test_zero_returns_none(self):
        with patch("radsim.menu.safe_input", return_value="0"):
            result = interactive_menu("TEST", self.OPTIONS)
            assert result is None

    def test_negative_returns_none(self):
        with patch("radsim.menu.safe_input", return_value="-1"):
            result = interactive_menu("TEST", self.OPTIONS)
            assert result is None


class TestInteractiveMenuLoop:
    def test_loops_until_quit(self):
        calls = []

        def handler(choice):
            calls.append(choice)
            return True

        # First call: select option 1, second call: quit
        with patch("radsim.menu.interactive_menu", side_effect=["opt1", None]):
            interactive_menu_loop("TEST", [("opt1", "Option 1")], handler)

        assert calls == ["opt1"]

    def test_handler_returns_false_exits(self):
        calls = []

        def handler(choice):
            calls.append(choice)
            return False  # Signal to exit

        with patch("radsim.menu.interactive_menu", return_value="opt1"):
            interactive_menu_loop("TEST", [("opt1", "Option 1")], handler)

        assert calls == ["opt1"]

    def test_multiple_selections(self):
        calls = []

        def handler(choice):
            calls.append(choice)

        with patch("radsim.menu.interactive_menu", side_effect=["a", "b", None]):
            interactive_menu_loop("TEST", [("a", "A"), ("b", "B")], handler)

        assert calls == ["a", "b"]
