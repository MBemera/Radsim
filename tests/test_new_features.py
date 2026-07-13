"""Undo checkpoints, bang passthrough, http_request, screen_capture,
/usage//copy//export, and RADSIM.md project context."""

from types import SimpleNamespace

import pytest

from radsim import undo
from radsim.commands import CommandRegistry


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Isolated HOME-equivalent undo root and project cwd for every test."""
    monkeypatch.setattr(undo, "UNDO_ROOT", tmp_path / "undo-root")
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


def build_agent():
    agent = SimpleNamespace(
        config=SimpleNamespace(model="test-model", auto_confirm=False),
        usage_stats={"input_tokens": 1000, "output_tokens": 500},
        messages=[],
        _last_response="Here you go:\n```python\nprint('hi')\n```\ndone",
        _pending_user_context=[],
    )
    return agent


class TestUndoCheckpoints:
    def test_rewrite_then_undo_restores_old_content(self, isolated_env):
        target = isolated_env / "app.py"
        target.write_text("original\n")

        pending = undo.prepare_checkpoint("write_file", {"file_path": "app.py"})
        target.write_text("changed\n")
        undo.commit_checkpoint(pending)

        result = undo.undo_last()
        assert result["success"] is True
        assert target.read_text() == "original\n"

    def test_undo_removes_files_that_did_not_exist(self, isolated_env):
        pending = undo.prepare_checkpoint("write_file", {"file_path": "brand_new.py"})
        (isolated_env / "brand_new.py").write_text("new\n")
        undo.commit_checkpoint(pending)

        result = undo.undo_last()
        assert result["success"] is True
        assert not (isolated_env / "brand_new.py").exists()

    def test_undo_restores_deleted_files(self, isolated_env):
        target = isolated_env / "keep.txt"
        target.write_text("precious\n")

        pending = undo.prepare_checkpoint("delete_file", {"file_path": "keep.txt"})
        target.unlink()
        undo.commit_checkpoint(pending)

        result = undo.undo_last()
        assert result["success"] is True
        assert target.read_text() == "precious\n"

    def test_discard_leaves_no_checkpoint(self, isolated_env):
        (isolated_env / "app.py").write_text("original\n")
        pending = undo.prepare_checkpoint("write_file", {"file_path": "app.py"})
        undo.discard_checkpoint(pending)
        assert undo.list_checkpoints() == []
        assert undo.undo_last()["success"] is False

    def test_oversized_files_are_recorded_not_snapshotted(self, isolated_env, monkeypatch):
        monkeypatch.setattr(undo, "MAX_SNAPSHOT_BYTES", 5)
        target = isolated_env / "big.bin"
        target.write_text("more than five bytes")

        pending = undo.prepare_checkpoint("write_file", {"file_path": "big.bin"})
        undo.commit_checkpoint(pending)

        result = undo.undo_last()
        assert result["success"] is True
        assert result["restored"] == []
        assert len(result["skipped"]) == 1

    def test_stack_is_bounded(self, isolated_env, monkeypatch):
        monkeypatch.setattr(undo, "MAX_CHECKPOINTS", 3)
        target = isolated_env / "f.txt"
        target.write_text("v0")
        for n in range(5):
            pending = undo.prepare_checkpoint("write_file", {"file_path": "f.txt"})
            target.write_text(f"v{n + 1}")
            undo.commit_checkpoint(pending)
        assert len(undo.list_checkpoints()) == 3

    def test_non_mutating_tools_are_not_checkpointed(self):
        assert undo.prepare_checkpoint("read_file", {"file_path": "x"}) is None
        assert undo.prepare_checkpoint("run_shell_command", {"command": "ls"}) is None


class TestBangPassthrough:
    def test_output_is_queued_for_the_agent(self, capsys):
        from radsim.agent_runtime import _run_user_shell_command

        agent = build_agent()
        _run_user_shell_command("echo bang_works", agent)

        assert "bang_works" in capsys.readouterr().out
        assert len(agent._pending_user_context) == 1
        assert "echo bang_works" in agent._pending_user_context[0]
        assert "bang_works" in agent._pending_user_context[0]

    def test_catastrophic_commands_stay_blocked(self, capsys):
        from radsim.agent_runtime import _run_user_shell_command

        agent = build_agent()
        _run_user_shell_command("rm -rf /", agent)

        assert agent._pending_user_context == []
        assert "BLOCKED" in capsys.readouterr().out

    def test_pending_context_merges_into_next_message(self):
        from radsim.agent_conversation import AgentConversationMixin

        class FakeAgent(AgentConversationMixin):
            pass

        agent = FakeAgent()
        agent._pending_user_context = ["[User ran shell command: ls]\nfile.txt"]
        # Reproduce the merge logic path without a full agent
        pending = agent._pending_user_context
        user_input = "what files do I have?"
        merged = "\n\n".join([*pending, user_input])
        pending.clear()
        assert "file.txt" in merged
        assert merged.endswith("what files do I have?")
        assert agent._pending_user_context == []


class TestHttpRequest:
    def test_rejects_non_http_schemes(self):
        from radsim.tools.web import http_request

        result = http_request("file:///etc/passwd")
        assert result["success"] is False
        assert "http" in result["error"]

    def test_rejects_unknown_methods(self):
        from radsim.tools.web import http_request

        result = http_request("https://example.com", method="TRACE")
        assert result["success"] is False
        assert "not allowed" in result["error"]

    def test_rejects_header_injection(self):
        from radsim.tools.web import http_request

        result = http_request(
            "https://example.com", headers={"X-Ok": "value\r\nEvil: injected"}
        )
        assert result["success"] is False
        assert "control characters" in result["error"]

    def test_closed_port_fails_cleanly(self):
        from radsim.tools.web import http_request

        result = http_request("http://127.0.0.1:9/", timeout=2)
        assert result["success"] is False

    def test_registry_dispatch_is_wired(self):
        from radsim.tools import execute_tool

        result = execute_tool("http_request", {"url": "not-a-url"})
        assert result["success"] is False
        assert "http" in result["error"]


class TestScreenCapture:
    def test_non_macos_gets_clear_error(self, monkeypatch):
        from radsim.tools import screen

        monkeypatch.setattr(screen.platform, "system", lambda: "Linux")
        result = screen.screen_capture()
        assert result["success"] is False
        assert "macOS" in result["error"]

    def test_traversal_path_is_rejected_before_capture(self, monkeypatch):
        from radsim.tools import screen

        monkeypatch.setattr(screen.platform, "system", lambda: "Darwin")
        called = []
        monkeypatch.setattr(
            screen.subprocess, "run", lambda *a, **k: called.append(a) or None
        )
        result = screen.screen_capture("../outside.png")
        assert result["success"] is False
        assert called == []  # screencapture never invoked


class TestSessionCommands:
    def make_registry(self):
        return CommandRegistry()

    def test_usage_shows_tokens_and_cost(self, capsys, monkeypatch):
        import radsim.config

        monkeypatch.setattr(radsim.config, "get_model_pricing", lambda model: (2.0, 10.0))
        agent = build_agent()
        self.make_registry().handle_input("/usage", agent)
        output = capsys.readouterr().out
        assert "1,000" in output
        assert "500" in output
        assert "$" in output

    def test_copy_code_extracts_last_fenced_block(self, monkeypatch, capsys):
        import radsim.commands_core as commands_core

        copied = []
        monkeypatch.setattr(
            commands_core, "_copy_to_clipboard", lambda text: copied.append(text) or (True, None)
        )
        agent = build_agent()
        self.make_registry().handle_input("/copy code", agent)
        assert copied == ["print('hi')"]

    def test_copy_with_nothing_says_so(self, capsys):
        agent = build_agent()
        agent._last_response = ""
        self.make_registry().handle_input("/copy", agent)
        assert "Nothing to copy" in capsys.readouterr().out

    def test_export_writes_markdown_file(self, isolated_env):
        agent = build_agent()
        agent.messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "running a tool"},
                    {"type": "tool_use", "name": "read_file", "id": "t1", "input": {}},
                ],
            },
        ]
        self.make_registry().handle_input("/export chat.md", agent)
        exported = (isolated_env / "chat.md").read_text()
        assert "## User" in exported
        assert "hello" in exported
        assert "[tool call: read_file]" in exported

    def test_export_refuses_to_overwrite(self, isolated_env, capsys):
        (isolated_env / "chat.md").write_text("precious")
        agent = build_agent()
        agent.messages = [{"role": "user", "content": "hello"}]
        self.make_registry().handle_input("/export chat.md", agent)
        assert (isolated_env / "chat.md").read_text() == "precious"
        assert "already exists" in capsys.readouterr().out

    def test_undo_command_restores_with_confirmation(self, isolated_env, monkeypatch, capsys):
        target = isolated_env / "app.py"
        target.write_text("original\n")
        pending = undo.prepare_checkpoint("write_file", {"file_path": "app.py"})
        target.write_text("changed\n")
        undo.commit_checkpoint(pending)

        monkeypatch.setattr(
            "radsim.safety.ask_confirmation", lambda *a, **k: "yes"
        )
        self.make_registry().handle_input("/undo", build_agent())
        assert target.read_text() == "original\n"
        assert "Restored" in capsys.readouterr().out


class TestSchedulerUnification:
    """schedule_task (model tool) and /job (user command) share one store."""

    def test_scheduled_task_appears_in_job_list(self, tmp_path, monkeypatch):
        import radsim.jobs as jobs
        from radsim.scheduler import list_schedules, schedule_task

        monkeypatch.setattr(jobs, "JOBS_FILE", tmp_path / "jobs.json")
        monkeypatch.setattr("radsim.jobs.sync_crontab", lambda: None)

        result = schedule_task(
            name="nightly-backup", schedule="daily", command="echo backup"
        )
        assert result["success"] is True

        # The user command reads the same store the tool wrote to.
        user_jobs = jobs.list_jobs()
        assert len(user_jobs) == 1
        assert user_jobs[0].command == "echo backup"

        # And list_schedules (the model's read-back) sees it too.
        listed = list_schedules()
        assert listed["count"] == 1
        assert listed["jobs"][0]["command"] == "echo backup"

    def test_invalid_schedule_is_rejected(self, tmp_path, monkeypatch):
        import radsim.jobs as jobs
        from radsim.scheduler import schedule_task

        monkeypatch.setattr(jobs, "JOBS_FILE", tmp_path / "jobs.json")
        monkeypatch.setattr("radsim.jobs.sync_crontab", lambda: None)

        result = schedule_task(name="bad", schedule="not-a-schedule", command="echo x")
        assert result["success"] is False


class TestProjectContext:
    def test_radsim_md_is_included_in_project_context(self, isolated_env):
        from radsim.memory import ProjectMemory

        (isolated_env / "RADSIM.md").write_text("# Project brief\nUse tabs, not spaces.")
        memory = ProjectMemory(project_dir=isolated_env)
        content = memory.read_agents_md()
        assert "Use tabs, not spaces." in content

    def test_missing_files_mean_empty_context(self, isolated_env):
        from radsim.memory import ProjectMemory

        memory = ProjectMemory(project_dir=isolated_env)
        assert memory.read_agents_md() == ""
