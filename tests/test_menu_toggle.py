"""Toggle-menu tests: state handling via the scriptable numbered fallback."""

from radsim.menu import _render_toggle_lines, _toggle_menu_numbered


def make_order_and_states():
    """Two-switch fixture mirroring the security customize menu shape."""
    order = [
        ("tools.docker", "Docker tool"),
        ("confirmations.shell_commands", "Confirm shell commands"),
    ]
    states = {"tools.docker": True, "confirmations.shell_commands": True}
    return order, states


def scripted_input(responses):
    """Return an input function that replays canned responses."""
    queue = list(responses)

    def read_input(_prompt):
        return queue.pop(0)

    return read_input


class TestToggleMenuNumbered:
    """The fallback loop must flip, save, and cancel correctly."""

    def test_toggle_then_save(self):
        order, states = make_order_and_states()
        result = _toggle_menu_numbered(
            "TEST", order, states, (), input_fn=scripted_input(["1", ""])
        )
        assert result == {
            "tools.docker": False,
            "confirmations.shell_commands": True,
        }

    def test_double_toggle_restores_value(self):
        order, states = make_order_and_states()
        result = _toggle_menu_numbered(
            "TEST", order, states, (), input_fn=scripted_input(["2", "2", ""])
        )
        assert result["confirmations.shell_commands"] is True

    def test_cancel_returns_none(self):
        order, states = make_order_and_states()
        result = _toggle_menu_numbered(
            "TEST", order, states, (), input_fn=scripted_input(["1", None])
        )
        assert result is None

    def test_invalid_input_is_ignored(self):
        order, states = make_order_and_states()
        result = _toggle_menu_numbered(
            "TEST", order, states, (), input_fn=scripted_input(["9", "banana", ""])
        )
        assert result == states


class TestToggleMenuRendering:
    """Rendered lines must show cursor position and switch states."""

    def test_render_marks_cursor_and_states(self):
        order, states = make_order_and_states()
        states["tools.docker"] = False
        lines = _render_toggle_lines("TEST", order, states, cursor=1, footer_lines=("note",))
        joined = "\n".join(lines)
        assert "  > [ON ] Confirm shell commands" in joined
        assert "    [OFF] Docker tool" in joined
        assert "  note" in joined
