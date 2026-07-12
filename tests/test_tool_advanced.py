"""Cross-platform regressions for advanced process tools."""

from unittest.mock import patch

from radsim.tools.advanced import run_docker
from radsim.tools.definitions import TOOL_DEFINITIONS


def test_docker_tool_schema_requires_explicit_argument_arrays():
    definition = next(tool for tool in TOOL_DEFINITIONS if tool["name"] == "run_docker")
    properties = definition["input_schema"]["properties"]

    assert properties["command"]["type"] == "array"
    assert properties["options"]["type"] == "array"
    assert properties["command"]["items"] == {"type": "string"}


def test_windows_docker_mount_preserves_backslashes():
    """Windows bind-mount paths must reach Docker unchanged."""
    successful_run = {"success": True, "stdout": "", "stderr": ""}
    with patch("radsim.tools.advanced.os.name", "nt"), patch(
        "radsim.tools.advanced.run_process", return_value=successful_run
    ) as mock_run:
        result = run_docker(
            "run",
            image="example",
            options=["--mount", r"type=bind,source=C:\Program Files\work,target=/app"],
        )

    assert result["success"] is True
    assert mock_run.call_args_list[1].args[0] == [
        "docker",
        "run",
        "--mount",
        r"type=bind,source=C:\Program Files\work,target=/app",
        "example",
    ]


def test_windows_docker_rejects_ambiguous_argument_strings():
    successful_run = {"success": True, "stdout": "", "stderr": ""}
    with patch("radsim.tools.advanced.os.name", "nt"), patch(
        "radsim.tools.advanced.run_process", return_value=successful_run
    ) as mock_run:
        result = run_docker("run", image="example", options=r"-v C:\work:/app")

    assert result["success"] is False
    assert "argument lists" in result["error"]
    mock_run.assert_not_called()


def test_docker_exec_is_noninteractive():
    successful_run = {"success": True, "stdout": "", "stderr": ""}
    with patch("radsim.tools.advanced.run_process", return_value=successful_run) as mock_run:
        result = run_docker("exec", container="app", command=["python", "-c", 'print("ok")'])

    assert result["success"] is True
    assert mock_run.call_args_list[1].args[0] == [
        "docker",
        "exec",
        "app",
        "python",
        "-c",
        'print("ok")',
    ]


def test_docker_rejects_invalid_identifiers_before_execution():
    successful_run = {"success": True, "stdout": "", "stderr": ""}
    with patch("radsim.tools.advanced.run_process", return_value=successful_run) as mock_run:
        numeric_result = run_docker("run", image=123)
        control_result = run_docker("run", image="safe\x1b[2Khidden")

    assert numeric_result["success"] is False
    assert control_result["success"] is False
    mock_run.assert_not_called()
