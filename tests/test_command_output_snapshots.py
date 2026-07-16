"""Character-level snapshots for shared command presentation shapes."""

from types import SimpleNamespace

from radsim.commands_core import CoreCommandHandlersMixin
from radsim.commands_learning import LearningCommandHandlersMixin
from radsim.commands_workflow import WorkflowCommandHandlersMixin


def test_modes_output_snapshot(capsys):
    CoreCommandHandlersMixin()._cmd_modes(None)

    assert capsys.readouterr().out == (
        "\n"
        "  ═══ AVAILABLE MODES ═══\n"
        "\n"
        "  Mode          Status    Shortcut        Description\n"
        "  ────────────────────────────────────────────────────────────\n"
        "  teach         OFF       /t, Shift+T     Explain code like a tutor while completing tasks\n"
        "  verbose       OFF       /v              Show detailed tool execution info\n"
        "  awake         OFF       /awake          Prevent macOS sleep (display, idle, system)\n"
        "\n"
        "  Toggle with: /teach or Shift+T (in supported terminals)\n"
        "\n"
    )


def test_usage_output_snapshot(capsys, monkeypatch):
    agent = SimpleNamespace(
        usage_stats={"input_tokens": 1234, "output_tokens": 567},
        config=SimpleNamespace(model="snapshot-model"),
    )
    monkeypatch.setattr("radsim.config.get_model_pricing", lambda model: (1.0, 2.0))

    CoreCommandHandlersMixin()._cmd_usage(agent)

    assert capsys.readouterr().out == (
        "\n"
        "  Model:          snapshot-model\n"
        "  Input tokens:   1,234\n"
        "  Output tokens:  567\n"
        "  Total tokens:   1,801\n"
        "  Est. cost:      $0.0024  (in $0.0012 / out $0.0011)\n"
        "\n"
    )


def test_learning_summary_output_snapshot(capsys, monkeypatch):
    stats = {
        "summary": {
            "total_tasks_completed": 3,
            "overall_task_success_rate": 0.75,
            "total_errors_tracked": 2,
            "total_feedback_received": 4,
            "total_examples_stored": 5,
            "total_tools_tracked": 6,
        }
    }
    monkeypatch.setattr("radsim.learning.get_learning_stats", lambda: stats)

    LearningCommandHandlersMixin()._show_learning_summary()

    assert capsys.readouterr().out == (
        "\n"
        "  ═══ LEARNING STATISTICS ═══\n"
        "\n"
        "  Tasks Completed:    3\n"
        "  Success Rate:       75.0%\n"
        "  Errors Tracked:     2\n"
        "  Feedback Received:  4\n"
        "  Examples Stored:    5\n"
        "  Tools Tracked:      6\n"
        "\n"
        "  Use /report for full details, /audit to review preferences.\n"
        "\n"
    )


def test_mcp_status_output_snapshot(capsys):
    manager = SimpleNamespace(
        get_connection_status=lambda: [
            {
                "connected": True,
                "tool_count": 2,
                "error": None,
                "auto_connect": True,
                "name": "demo",
                "transport": "stdio",
            }
        ]
    )

    WorkflowCommandHandlersMixin()._mcp_status(manager)

    assert capsys.readouterr().out == (
        "\n"
        " MCP Servers (1):\n"
        "--------------------------------------------------\n"
        "  demo (stdio [auto]): connected (2 tools)\n"
        "\n"
    )
