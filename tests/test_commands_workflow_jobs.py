"""Focused tests for scheduled-job slash-command error handling."""

from unittest.mock import patch

from radsim.commands_workflow import WorkflowCommandHandlersMixin


def test_job_list_failure_is_reported_without_escaping():
    handler = WorkflowCommandHandlersMixin()

    with patch("radsim.jobs.list_jobs", side_effect=RuntimeError("crontab unavailable")), patch(
        "radsim.commands_workflow.print_error"
    ) as mock_error:
        handler._cmd_job(agent=None, args=["list"])

    mock_error.assert_called_once_with("Job operation failed: crontab unavailable")
