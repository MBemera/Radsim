# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Plan manager for structured plan-confirm-execute workflows.

Provides the /plan command: generate plans, review, approve, execute step-by-step.
"""

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

PLANS_DIR = Path.home() / ".radsim" / "plans"


class PlanStep:
    """A single step in a plan."""

    def __init__(
        self,
        description: str,
        files: list[str] | None = None,
        risk: str = "low",
        scope: str = "",
        checkpoint: bool = False,
    ):
        self.description = description
        self.files = files or []
        self.risk = risk.lower()
        self.scope = scope
        self.checkpoint = checkpoint
        self.status = "pending"  # pending, in_progress, completed, skipped

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "files": self.files,
            "risk": self.risk,
            "scope": self.scope,
            "checkpoint": self.checkpoint,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlanStep":
        step = cls(
            description=data["description"],
            files=data.get("files", []),
            risk=data.get("risk", "low"),
            scope=data.get("scope", ""),
            checkpoint=data.get("checkpoint", False),
        )
        step.status = data.get("status", "pending")
        return step


class Plan:
    """A structured implementation plan."""

    def __init__(
        self,
        title: str,
        goal: str,
        steps: list[PlanStep] | None = None,
        dependencies: list[str] | None = None,
        rollback: str = "",
    ):
        self.plan_id = f"plan_{int(time.time())}"
        self.title = title
        self.goal = goal
        self.steps = steps or []
        self.dependencies = dependencies or []
        self.rollback = rollback
        self.status = "draft"  # draft, approved, in_progress, completed, rejected
        self.created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.current_step = 0

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "dependencies": self.dependencies,
            "rollback": self.rollback,
            "status": self.status,
            "created_at": self.created_at,
            "current_step": self.current_step,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Plan":
        plan = cls(
            title=data["title"],
            goal=data["goal"],
            steps=[PlanStep.from_dict(s) for s in data.get("steps", [])],
            dependencies=data.get("dependencies", []),
            rollback=data.get("rollback", ""),
        )
        plan.plan_id = data.get("plan_id", plan.plan_id)
        plan.status = data.get("status", "draft")
        plan.created_at = data.get("created_at", plan.created_at)
        plan.current_step = data.get("current_step", 0)
        return plan


RISK_ICONS = {"low": "🟢", "medium": "🟡", "med": "🟡", "high": "🔴"}
STATUS_ICONS = {
    "pending": "⬜",
    "in_progress": "🔄",
    "completed": "✅",
    "skipped": "⏭️",
}


class PlanManager:
    """Manages plan creation, storage, and execution."""

    def __init__(self):
        self.active_plan: Plan | None = None
        PLANS_DIR.mkdir(parents=True, exist_ok=True)

    def create_plan_from_response(self, response_text: str) -> Plan | None:
        """Parse an LLM response into a Plan object.

        Expects JSON with: title, goal, steps[], dependencies[], rollback.
        Falls back to a simple plan if parsing fails.
        """
        # Try to extract JSON from the response
        plan_data = self._extract_json(response_text)
        if not plan_data:
            return None

        try:
            steps = []
            for step_data in plan_data.get("steps", []):
                step = PlanStep(
                    description=step_data.get("description", ""),
                    files=step_data.get("files", []),
                    risk=step_data.get("risk", "low"),
                    scope=step_data.get("scope", ""),
                    checkpoint=step_data.get("checkpoint", False),
                )
                steps.append(step)

            if not steps:
                return None

            plan = Plan(
                title=plan_data.get("title", "Untitled Plan"),
                goal=plan_data.get("goal", ""),
                steps=steps,
                dependencies=plan_data.get("dependencies", []),
                rollback=plan_data.get("rollback", ""),
            )

            self.active_plan = plan
            self._save_plan(plan)
            return plan

        except Exception as e:
            logger.debug(f"Failed to parse plan: {e}")
            return None

    def _extract_json(self, text: str) -> dict | None:
        """Extract JSON object from text, handling markdown code blocks."""
        import re

        # Try to find JSON in code blocks first
        json_patterns = [
            r"```json\s*\n(.*?)\n\s*```",
            r"```\s*\n(.*?)\n\s*```",
            r"\{[\s\S]*\}",
        ]

        for pattern in json_patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            for match in matches:
                try:
                    return json.loads(match)
                except json.JSONDecodeError:
                    continue

        return None

    def show_plan(self) -> str:
        """Format the active plan for display."""
        if not self.active_plan:
            return "  No active plan. Use '/plan <description>' to create one."

        plan = self.active_plan
        lines = []
        width = 55

        lines.append("")
        lines.append(f"  ┌{'─' * width}┐")
        lines.append(f"  │{'PLAN: ' + plan.title[:width - 7]:^{width}}│")
        lines.append(f"  │{'Goal: ' + plan.goal[:width - 7]:^{width}}│")
        lines.append(f"  │{'Status: ' + plan.status.upper()[:width - 9]:^{width}}│")
        lines.append(f"  ├{'─' * width}┤")

        for i, step in enumerate(plan.steps, 1):
            risk_icon = RISK_ICONS.get(step.risk, "⚪")
            status_icon = STATUS_ICONS.get(step.status, "⬜")
            checkpoint = " 🔒" if step.checkpoint else ""

            # Step header
            step_header = f"  Step {i}: {step.description[:35]}"
            risk_label = f"[{step.risk.upper()}]"
            lines.append(f"  │ {status_icon} {step_header:<42} {risk_icon} {risk_label:>6} │")

            # Files
            if step.files:
                files_str = ", ".join(step.files[:3])
                if len(step.files) > 3:
                    files_str += f" +{len(step.files) - 3} more"
                lines.append(f"  │    Files: {files_str[:width - 12]:<{width - 6}}│")

            if checkpoint:
                lines.append(f"  │    Checkpoint: Yes (pause for confirmation){' ' * (width - 48)}│")

            lines.append(f"  │{' ' * width}│")

        if plan.dependencies:
            lines.append(f"  ├{'─' * width}┤")
            lines.append(f"  │ Dependencies:{' ' * (width - 15)}│")
            for dep in plan.dependencies:
                lines.append(f"  │   • {dep[:width - 8]:<{width - 6}}│")

        if plan.rollback:
            lines.append(f"  ├{'─' * width}┤")
            rollback_text = f"Rollback: {plan.rollback[:width - 12]}"
            lines.append(f"  │ {rollback_text:<{width - 2}}│")

        lines.append(f"  └{'─' * width}┘")
        lines.append("")

        if plan.status == "draft":
            lines.append("  /plan approve  - Approve and start execution")
            lines.append("  /plan reject   - Discard this plan")
        elif plan.status in ("approved", "in_progress"):
            lines.append("  /plan step     - Execute next step")
            lines.append("  /plan run      - Execute all remaining steps")
        lines.append("")

        return "\n".join(lines)

    def approve_plan(self) -> str:
        """Approve the active plan for execution."""
        if not self.active_plan:
            return "  No active plan to approve."

        if self.active_plan.status != "draft":
            return f"  Plan is already {self.active_plan.status}."

        self.active_plan.status = "approved"
        self._save_plan(self.active_plan)
        return "  ✓ Plan approved! Use '/plan step' or '/plan run' to execute."

    def reject_plan(self) -> str:
        """Reject and discard the active plan."""
        if not self.active_plan:
            return "  No active plan to reject."

        self.active_plan.status = "rejected"
        self._save_plan(self.active_plan)
        self.active_plan = None
        return "  ✗ Plan rejected and discarded."

    def get_next_step(self) -> tuple[int, PlanStep] | None:
        """Get the next pending step."""
        if not self.active_plan:
            return None

        for i, step in enumerate(self.active_plan.steps):
            if step.status == "pending":
                return i, step

        return None

    def mark_step_complete(self, step_index: int):
        """Mark a step as completed."""
        if not self.active_plan:
            return

        if 0 <= step_index < len(self.active_plan.steps):
            self.active_plan.steps[step_index].status = "completed"
            self.active_plan.current_step = step_index + 1

            # Check if all steps are done
            if all(s.status in ("completed", "skipped") for s in self.active_plan.steps):
                self.active_plan.status = "completed"

            self._save_plan(self.active_plan)

    def mark_step_in_progress(self, step_index: int):
        """Mark a step as in progress."""
        if not self.active_plan and 0 <= step_index < len(self.active_plan.steps):
            return
        self.active_plan.steps[step_index].status = "in_progress"
        self.active_plan.status = "in_progress"
        self._save_plan(self.active_plan)

    def get_status(self) -> str:
        """Get a status summary of the active plan."""
        if not self.active_plan:
            return "  No active plan."

        plan = self.active_plan
        total = len(plan.steps)
        completed = sum(1 for s in plan.steps if s.status == "completed")
        in_progress = sum(1 for s in plan.steps if s.status == "in_progress")

        lines = []
        lines.append("")
        lines.append(f"  📋 {plan.title}")
        lines.append(f"  Status: {plan.status.upper()}")
        lines.append(f"  Progress: {completed}/{total} steps completed")

        if in_progress:
            lines.append(f"  In progress: {in_progress} step(s)")

        # Progress bar
        if total > 0:
            pct = completed / total
            bar_len = 30
            filled = int(bar_len * pct)
            bar = "█" * filled + "░" * (bar_len - filled)
            lines.append(f"  [{bar}] {pct:.0%}")

        lines.append("")
        return "\n".join(lines)

    def get_history(self) -> str:
        """Show past plans."""
        plans = self._load_all_plans()
        if not plans:
            return "  No plan history."

        lines = ["", "  ═══ PLAN HISTORY ═══", ""]
        for plan_data in plans[-10:]:  # Last 10
            status_icon = {
                "completed": "✅",
                "rejected": "❌",
                "draft": "📝",
                "approved": "🔄",
                "in_progress": "🔄",
            }.get(plan_data.get("status"), "❓")

            lines.append(f"  {status_icon} {plan_data['title']}")
            lines.append(f"     Created: {plan_data['created_at']}")
            lines.append(f"     Steps: {len(plan_data.get('steps', []))}")
            lines.append("")

        return "\n".join(lines)

    def export_plan(self) -> str:
        """Export the active plan to a markdown file."""
        if not self.active_plan:
            return "  No active plan to export."

        plan = self.active_plan
        md_lines = [
            f"# {plan.title}",
            "",
            f"**Goal:** {plan.goal}",
            f"**Status:** {plan.status}",
            f"**Created:** {plan.created_at}",
            "",
            "## Steps",
            "",
        ]

        for i, step in enumerate(plan.steps, 1):
            checkbox = "x" if step.status == "completed" else " "
            md_lines.append(f"- [{checkbox}] **Step {i}:** {step.description}")
            md_lines.append(f"  - Risk: {step.risk.upper()}")
            if step.files:
                md_lines.append(f"  - Files: {', '.join(step.files)}")
            if step.scope:
                md_lines.append(f"  - Scope: {step.scope}")
            md_lines.append("")

        if plan.dependencies:
            md_lines.append("## Dependencies")
            md_lines.append("")
            for dep in plan.dependencies:
                md_lines.append(f"- {dep}")
            md_lines.append("")

        if plan.rollback:
            md_lines.append("## Rollback Strategy")
            md_lines.append("")
            md_lines.append(plan.rollback)
            md_lines.append("")

        # Write to file
        export_path = Path.cwd() / f"{plan.plan_id}.md"
        export_path.write_text("\n".join(md_lines))

        return f"  ✓ Plan exported to: {export_path}"

    def _save_plan(self, plan: Plan):
        """Save plan to JSON file."""
        try:
            PLANS_DIR.mkdir(parents=True, exist_ok=True)
            plan_file = PLANS_DIR / f"{plan.plan_id}.json"
            plan_file.write_text(json.dumps(plan.to_dict(), indent=2))
        except Exception as e:
            logger.debug(f"Failed to save plan: {e}")

    def _load_all_plans(self) -> list[dict]:
        """Load all plan files."""
        plans = []
        try:
            for f in sorted(PLANS_DIR.glob("plan_*.json")):
                try:
                    plans.append(json.loads(f.read_text()))
                except Exception:
                    continue
        except Exception:
            pass
        return plans

    def load_latest_plan(self):
        """Load the most recent active plan if any."""
        plans = self._load_all_plans()
        for plan_data in reversed(plans):
            if plan_data.get("status") in ("draft", "approved", "in_progress"):
                self.active_plan = Plan.from_dict(plan_data)
                return self.active_plan
        return None


# Singleton instance
_plan_manager: PlanManager | None = None


def get_plan_manager() -> PlanManager:
    """Get or create the global PlanManager instance."""
    global _plan_manager
    if _plan_manager is None:
        _plan_manager = PlanManager()
        _plan_manager.load_latest_plan()
    return _plan_manager
