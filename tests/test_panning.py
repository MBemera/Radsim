# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Tests for the panning session."""

import json

from radsim.panning import (
    PanningSession,
    PanningSynthesis,
    get_panning_session,
    start_new_session,
)


class TestPanningSynthesis:
    """Tests for PanningSynthesis data model."""

    def test_create_synthesis(self):
        synthesis = PanningSynthesis(
            themes=[{"title": "Auth", "description": "Authentication overhaul"}],
            action_items=[{"task": "Research JWT", "priority": "high"}],
            priorities=[{"item": "Auth", "signal": "mentioned 3x", "rank": 1}],
            connections=[{"items": ["Auth", "Mobile"], "insight": "Login on mobile"}],
            open_questions=["Who are the users?"],
        )
        assert len(synthesis.themes) == 1
        assert len(synthesis.action_items) == 1
        assert synthesis.open_questions[0] == "Who are the users?"

    def test_serialization(self):
        synthesis = PanningSynthesis(
            themes=[{"title": "Perf"}],
            action_items=[{"task": "Profile API", "priority": "medium"}],
        )
        data = synthesis.to_dict()
        restored = PanningSynthesis.from_dict(data)

        assert restored.themes == synthesis.themes
        assert restored.action_items == synthesis.action_items

    def test_format_display(self):
        synthesis = PanningSynthesis(
            themes=[{"title": "Auth", "description": "Needs rework"}],
            action_items=[{"task": "Research JWT", "priority": "high"}],
            priorities=[{"item": "Auth", "signal": "mentioned 3x", "rank": 1}],
        )
        output = synthesis.format_display()
        assert "PANNING SYNTHESIS" in output
        assert "Auth" in output
        assert "Research JWT" in output

    def test_to_plan_description(self):
        synthesis = PanningSynthesis(
            themes=[{"title": "Auth"}, {"title": "Performance"}],
            action_items=[
                {"task": "Add JWT", "priority": "high"},
                {"task": "Fix CSS", "priority": "low"},
            ],
            priorities=[{"item": "Auth", "signal": "urgent", "rank": 1}],
        )
        desc = synthesis.to_plan_description()
        assert "Auth" in desc
        assert "Add JWT" in desc

    def test_empty_synthesis(self):
        synthesis = PanningSynthesis()
        assert synthesis.themes == []
        assert synthesis.format_display()  # Should not crash


class TestPanningSession:
    """Tests for PanningSession lifecycle."""

    def test_start_session(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.panning.PANNING_DIR", tmp_path)
        session = PanningSession()
        result = session.start()
        assert session.active is True
        assert "started" in result.lower()

    def test_add_dump(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.panning.PANNING_DIR", tmp_path)
        session = PanningSession()
        session.start()
        session.add_dump("I think we need better auth")
        session.add_dump("The dashboard is slow too")
        assert len(session.dumps) == 2

    def test_get_all_dumps(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.panning.PANNING_DIR", tmp_path)
        session = PanningSession()
        session.add_dump("Thought 1")
        session.add_dump("Thought 2")
        combined = session.get_all_dumps()
        assert "Thought 1" in combined
        assert "Thought 2" in combined

    def test_process_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.panning.PANNING_DIR", tmp_path)
        session = PanningSession()

        # Create a test file
        test_file = tmp_path / "notes.txt"
        test_file.write_text("My braindump notes here")

        result = session.process_file(str(test_file))
        assert "✓" in result
        assert len(session.dumps) == 1

    def test_process_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.panning.PANNING_DIR", tmp_path)
        session = PanningSession()
        result = session.process_file("/nonexistent/file.txt")
        assert "not found" in result.lower() or "⚠" in result

    def test_parse_synthesis(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.panning.PANNING_DIR", tmp_path)
        session = PanningSession()

        response = '''Here's the synthesis:

```json
{
  "themes": [{"title": "Auth", "description": "Needs rework"}],
  "action_items": [{"task": "Research JWT", "priority": "high"}],
  "priorities": [{"item": "Auth", "signal": "mentioned 3x", "rank": 1}],
  "connections": [],
  "open_questions": ["Who are the users?"]
}
```'''

        synthesis = session.parse_synthesis(response)
        assert synthesis is not None
        assert len(synthesis.themes) == 1
        assert synthesis.themes[0]["title"] == "Auth"
        assert len(session.syntheses) == 1

    def test_parse_invalid_synthesis(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.panning.PANNING_DIR", tmp_path)
        session = PanningSession()
        synthesis = session.parse_synthesis("Not JSON at all")
        assert synthesis is None

    def test_end_session(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.panning.PANNING_DIR", tmp_path)
        session = PanningSession()
        session.start()
        session.end()
        assert session.active is False

    def test_session_persistence(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.panning.PANNING_DIR", tmp_path)
        session = PanningSession()
        session.add_dump("Test thought")
        session._save()

        # Verify file was created
        files = list(tmp_path.glob("panning_*.json"))
        assert len(files) == 1

        data = json.loads(files[0].read_text())
        assert data["dumps"] == ["Test thought"]

    def test_get_latest_synthesis(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.panning.PANNING_DIR", tmp_path)
        session = PanningSession()

        assert session.get_latest_synthesis() is None

        synthesis = PanningSynthesis(themes=[{"title": "Test"}])
        session.syntheses.append(synthesis)

        latest = session.get_latest_synthesis()
        assert latest is not None
        assert latest.themes[0]["title"] == "Test"


class TestSingletons:
    """Tests for singleton accessors."""

    def test_get_panning_session(self, monkeypatch):
        monkeypatch.setattr("radsim.panning._panning_session", None)
        session = get_panning_session()
        assert session is not None
        assert get_panning_session() is session  # Same instance

    def test_start_new_session(self, monkeypatch):
        monkeypatch.setattr("radsim.panning._panning_session", None)
        s1 = get_panning_session()
        s2 = start_new_session()
        assert s1 is not s2  # New instance
