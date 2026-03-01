# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Tests for the plan manager."""



from radsim.planner import (
    Plan,
    PlanManager,
    PlanStep,
)


class TestPlanStep:
    """Tests for PlanStep data model."""

    def test_create_step(self):
        step = PlanStep("Install dependencies", files=["pyproject.toml"], risk="low")
        assert step.description == "Install dependencies"
        assert step.risk == "low"
        assert step.status == "pending"
        assert step.files == ["pyproject.toml"]

    def test_step_serialization(self):
        step = PlanStep("Create auth module", files=["src/auth.py"], risk="medium", checkpoint=True)
        data = step.to_dict()
        restored = PlanStep.from_dict(data)

        assert restored.description == step.description
        assert restored.files == step.files
        assert restored.risk == step.risk
        assert restored.checkpoint == step.checkpoint

    def test_default_values(self):
        step = PlanStep("Simple task")
        assert step.files == []
        assert step.risk == "low"
        assert step.scope == ""
        assert step.checkpoint is False


class TestPlan:
    """Tests for Plan data model."""

    def test_create_plan(self):
        steps = [
            PlanStep("Step 1", risk="low"),
            PlanStep("Step 2", risk="medium", checkpoint=True),
        ]
        plan = Plan("Test Plan", "Test goal", steps=steps)

        assert plan.title == "Test Plan"
        assert plan.goal == "Test goal"
        assert len(plan.steps) == 2
        assert plan.status == "draft"

    def test_plan_serialization(self):
        steps = [PlanStep("Step 1"), PlanStep("Step 2")]
        plan = Plan("Test", "Goal", steps=steps, dependencies=["Python 3.10+"])
        plan.rollback = "git revert"

        data = plan.to_dict()
        restored = Plan.from_dict(data)

        assert restored.title == plan.title
        assert restored.goal == plan.goal
        assert len(restored.steps) == 2
        assert restored.dependencies == ["Python 3.10+"]
        assert restored.rollback == "git revert"


class TestPlanManager:
    """Tests for PlanManager lifecycle."""

    def test_approve_draft_plan(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.planner.PLANS_DIR", tmp_path)
        pm = PlanManager()

        plan = Plan("Test", "Goal", steps=[PlanStep("S1")])
        pm.active_plan = plan

        result = pm.approve_plan()
        assert "approved" in result.lower() or "✓" in result
        assert pm.active_plan.status == "approved"

    def test_reject_plan(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.planner.PLANS_DIR", tmp_path)
        pm = PlanManager()

        plan = Plan("Test", "Goal", steps=[PlanStep("S1")])
        pm.active_plan = plan

        result = pm.reject_plan()
        assert pm.active_plan is None
        assert "rejected" in result.lower() or "✗" in result

    def test_approve_no_plan(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.planner.PLANS_DIR", tmp_path)
        pm = PlanManager()
        result = pm.approve_plan()
        assert "No active plan" in result

    def test_get_next_step(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.planner.PLANS_DIR", tmp_path)
        pm = PlanManager()

        steps = [PlanStep("S1"), PlanStep("S2"), PlanStep("S3")]
        plan = Plan("Test", "Goal", steps=steps)
        pm.active_plan = plan

        idx, step = pm.get_next_step()
        assert idx == 0
        assert step.description == "S1"

    def test_mark_step_complete(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.planner.PLANS_DIR", tmp_path)
        pm = PlanManager()

        steps = [PlanStep("S1"), PlanStep("S2")]
        plan = Plan("Test", "Goal", steps=steps)
        pm.active_plan = plan

        pm.mark_step_complete(0)
        assert plan.steps[0].status == "completed"
        assert plan.current_step == 1

        idx, step = pm.get_next_step()
        assert idx == 1

    def test_all_steps_completed(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.planner.PLANS_DIR", tmp_path)
        pm = PlanManager()

        steps = [PlanStep("S1")]
        plan = Plan("Test", "Goal", steps=steps)
        plan.status = "approved"
        pm.active_plan = plan

        pm.mark_step_complete(0)
        assert plan.status == "completed"
        assert pm.get_next_step() is None

    def test_show_plan(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.planner.PLANS_DIR", tmp_path)
        pm = PlanManager()

        steps = [PlanStep("Install deps", risk="low"), PlanStep("Create module", risk="high", checkpoint=True)]
        plan = Plan("JWT Auth", "Add authentication", steps=steps)
        pm.active_plan = plan

        output = pm.show_plan()
        assert "JWT Auth" in output
        assert "Install deps" in output
        assert "approve" in output.lower()

    def test_show_plan_no_plan(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.planner.PLANS_DIR", tmp_path)
        pm = PlanManager()
        output = pm.show_plan()
        assert "No active plan" in output

    def test_create_plan_from_response(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.planner.PLANS_DIR", tmp_path)
        pm = PlanManager()

        response = '''Here's the plan:

```json
{
  "title": "Add Authentication",
  "goal": "Secure the API",
  "steps": [
    {"description": "Install JWT library", "files": ["requirements.txt"], "risk": "low", "checkpoint": false},
    {"description": "Create auth module", "files": ["src/auth.py"], "risk": "medium", "checkpoint": true}
  ],
  "dependencies": ["Python 3.10+"],
  "rollback": "git revert"
}
```'''

        plan = pm.create_plan_from_response(response)
        assert plan is not None
        assert plan.title == "Add Authentication"
        assert len(plan.steps) == 2
        assert plan.steps[1].checkpoint is True

    def test_create_plan_from_invalid_response(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.planner.PLANS_DIR", tmp_path)
        pm = PlanManager()
        plan = pm.create_plan_from_response("This is not JSON")
        assert plan is None

    def test_get_status(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.planner.PLANS_DIR", tmp_path)
        pm = PlanManager()

        steps = [PlanStep("S1"), PlanStep("S2")]
        plan = Plan("Test", "Goal", steps=steps)
        pm.active_plan = plan

        pm.mark_step_complete(0)
        status = pm.get_status()
        assert "1/2" in status
        assert "Test" in status

    def test_export_plan(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.planner.PLANS_DIR", tmp_path)
        pm = PlanManager()

        steps = [PlanStep("S1", files=["a.py"])]
        plan = Plan("Export Test", "Test export", steps=steps)
        pm.active_plan = plan

        # Export to tmp_path
        monkeypatch.chdir(tmp_path)
        result = pm.export_plan()
        assert "exported" in result.lower() or "✓" in result

    def test_plan_persistence(self, tmp_path, monkeypatch):
        monkeypatch.setattr("radsim.planner.PLANS_DIR", tmp_path)

        # Create and save
        pm1 = PlanManager()
        plan = Plan("Persistent", "Test", steps=[PlanStep("S1")])
        pm1.active_plan = plan
        pm1._save_plan(plan)

        # Load in new instance
        pm2 = PlanManager()
        loaded = pm2.load_latest_plan()
        assert loaded is not None
        assert loaded.title == "Persistent"
