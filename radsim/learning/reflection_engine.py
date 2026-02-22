"""Reflection Engine - Post-Task Analysis.

Analyze completed tasks to generate improvement insights.
Extracts patterns from successes and failures for continuous improvement.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class TaskReflection:
    """A reflection on a completed task."""

    task_description: str
    approach_taken: str
    result: str
    success: bool
    insights: list
    improvement_suggestions: list
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class ReflectionEngine:
    """Analyze completed tasks and generate improvement insights.

    Reflects on:
    - What approach was used
    - Whether it succeeded or failed
    - What patterns led to success
    - What could be improved
    """

    def __init__(self, storage_dir: Path = None):
        self.storage_dir = storage_dir or Path.home() / ".radsim" / "learning"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.reflections_file = self.storage_dir / "reflections.json"
        self.insights_file = self.storage_dir / "insights.json"

        self._reflections: list[dict] = []
        self._insights: dict = {}
        self._load()

    def _load(self):
        """Load reflection data from disk."""
        if self.reflections_file.exists():
            try:
                self._reflections = json.loads(self.reflections_file.read_text())
            except (OSError, json.JSONDecodeError):
                self._reflections = []

        if self.insights_file.exists():
            try:
                self._insights = json.loads(self.insights_file.read_text())
            except (OSError, json.JSONDecodeError):
                self._insights = {}

    def _save(self):
        """Persist reflection data to disk."""
        self.reflections_file.write_text(json.dumps(self._reflections[-200:], indent=2))
        self.insights_file.write_text(json.dumps(self._insights, indent=2))

    def reflect_on_completion(
        self,
        task_description: str,
        approach_taken: str,
        result: str,
        success: bool,
        tools_used: list = None,
        duration_seconds: float = 0,
    ) -> TaskReflection:
        """Generate insights from a completed task.

        Args:
            task_description: What was requested
            approach_taken: How it was solved
            result: What happened
            success: Whether it worked
            tools_used: List of tools that were used
            duration_seconds: How long it took

        Returns:
            TaskReflection with insights and suggestions
        """
        tools_used = tools_used or []
        insights = []
        suggestions = []

        if success:
            # Analyze success patterns
            success_insight = self._generate_success_insight(
                task_description, approach_taken, tools_used
            )
            insights.append(f"SUCCESS: {success_insight}")

            # Save successful pattern
            self._save_successful_pattern(
                task_description, approach_taken, tools_used, result
            )
        else:
            # Analyze failure
            failure_insight = self._generate_failure_insight(
                task_description, approach_taken, result
            )
            insights.append(f"FAILURE: {failure_insight}")

            # Suggest improvements
            better_approach = self._suggest_better_approach(task_description, result)
            if better_approach:
                suggestions.append(better_approach)

        # Time-based insights
        if duration_seconds > 120:  # More than 2 minutes
            insights.append("SLOW: Task took longer than expected. Consider breaking into smaller steps.")
        elif duration_seconds < 10 and success:
            insights.append("FAST: Quick resolution - approach was effective.")

        # Tool-based insights
        if len(tools_used) > 10:
            suggestions.append("Consider combining steps to reduce tool calls.")
        elif "write_file" in tools_used and "run_tests" not in tools_used:
            suggestions.append("Consider running tests after writing code.")

        reflection = {
            "task_description": task_description[:500],
            "approach_taken": approach_taken[:1000],
            "result": result[:500],
            "success": success,
            "insights": insights,
            "suggestions": suggestions,
            "tools_used": tools_used,
            "duration_seconds": duration_seconds,
            "timestamp": datetime.now().isoformat(),
        }

        self._reflections.append(reflection)
        self._update_insights(reflection)
        self._save()

        return TaskReflection(
            task_description=task_description,
            approach_taken=approach_taken,
            result=result,
            success=success,
            insights=insights,
            improvement_suggestions=suggestions,
        )

    def _generate_success_insight(
        self,
        task: str,
        approach: str,
        tools: list,
    ) -> str:
        """Explain why this approach succeeded."""
        approach_lower = approach.lower()

        # Check for good patterns
        if "read" in approach_lower and "write" in approach_lower:
            return "Read-before-write approach ensured understanding of existing structure."

        if "test" in approach_lower:
            return "Testing-included approach caught potential issues."

        if len(tools) <= 5:
            return "Efficient approach with minimal tool usage."

        if "incremental" in approach_lower or "step" in approach_lower:
            return "Incremental changes made debugging easier."

        return "Task completed successfully."

    def _generate_failure_insight(
        self,
        task: str,
        approach: str,
        result: str,
    ) -> str:
        """Explain why this approach failed."""
        result_lower = result.lower()

        if "permission" in result_lower:
            return "Permission issue - check file/directory access rights."

        if "not found" in result_lower:
            return "Resource not found - verify paths and names before operating."

        if "timeout" in result_lower:
            return "Operation timed out - consider breaking into smaller operations."

        if "syntax" in result_lower:
            return "Syntax error - validate code before writing."

        if "import" in result_lower:
            return "Import/dependency issue - check requirements."

        return "Task failed - review approach and error details."

    def _suggest_better_approach(self, task: str, result: str) -> str | None:
        """Suggest what might have worked better."""
        # Search for similar successful tasks
        task_lower = task.lower()
        task_words = set(task_lower.split())

        for reflection in reversed(self._reflections[-50:]):
            if not reflection.get("success"):
                continue

            past_task = reflection.get("task_description", "").lower()
            past_words = set(past_task.split())

            overlap = len(task_words & past_words)
            if overlap >= 3:  # Similar task
                return f"Similar task succeeded with: {reflection.get('approach_taken', '')[:100]}"

        return None

    def _save_successful_pattern(
        self,
        task: str,
        approach: str,
        tools: list,
        result: str,
    ):
        """Save a successful pattern for future reference."""
        pattern_key = self._classify_task(task)

        if pattern_key not in self._insights:
            self._insights[pattern_key] = {
                "success_count": 0,
                "failure_count": 0,
                "effective_approaches": [],
                "common_tools": {},
            }

        insight = self._insights[pattern_key]
        insight["success_count"] += 1

        if approach and approach not in insight["effective_approaches"]:
            insight["effective_approaches"].append(approach[:200])
            # Keep only top 5
            insight["effective_approaches"] = insight["effective_approaches"][-5:]

        for tool in tools:
            insight["common_tools"][tool] = insight["common_tools"].get(tool, 0) + 1

    def _classify_task(self, task: str) -> str:
        """Classify a task into a category."""
        task_lower = task.lower()

        categories = {
            "bug_fix": ["fix", "bug", "error", "issue", "broken"],
            "feature": ["add", "create", "implement", "build", "new"],
            "refactor": ["refactor", "improve", "clean", "optimize"],
            "test": ["test", "testing", "coverage", "spec"],
            "docs": ["document", "readme", "comment", "doc"],
            "config": ["config", "setting", "setup", "install"],
        }

        for category, keywords in categories.items():
            if any(kw in task_lower for kw in keywords):
                return category

        return "general"

    def _update_insights(self, reflection: dict):
        """Update aggregate insights from a reflection."""
        category = self._classify_task(reflection["task_description"])

        if category not in self._insights:
            self._insights[category] = {
                "success_count": 0,
                "failure_count": 0,
                "effective_approaches": [],
                "common_tools": {},
            }

        insight = self._insights[category]

        if reflection["success"]:
            insight["success_count"] += 1
        else:
            insight["failure_count"] += 1

    def get_improvement_opportunities(self) -> list[dict]:
        """Extract top improvement areas from all reflections."""
        if not self._reflections:
            return []

        failures = [r for r in self._reflections if not r.get("success")]

        if not failures:
            return [{"category": "none", "message": "No failures to learn from!"}]

        # Group by failure category
        failure_categories = {}
        for failure in failures:
            category = self._classify_task(failure["task_description"])
            if category not in failure_categories:
                failure_categories[category] = []
            failure_categories[category].append(failure)

        # Return top categories with suggestions
        opportunities = []
        for category, category_failures in sorted(
            failure_categories.items(),
            key=lambda x: len(x[1]),
            reverse=True,
        )[:3]:
            opportunities.append({
                "category": category,
                "failure_count": len(category_failures),
                "common_issues": self._summarize_failures(category_failures),
                "suggestion": self._get_category_suggestion(category),
            })

        return opportunities

    def _summarize_failures(self, failures: list[dict]) -> list[str]:
        """Summarize common issues in failures."""
        issues = []
        for f in failures[-5:]:
            issues.append(f.get("result", "")[:100])
        return issues

    def _get_category_suggestion(self, category: str) -> str:
        """Get improvement suggestion for a category."""
        suggestions = {
            "bug_fix": "Read and understand the code thoroughly before making changes.",
            "feature": "Break features into smaller, testable increments.",
            "refactor": "Make one change at a time and test frequently.",
            "test": "Ensure test environment is properly configured.",
            "docs": "Keep documentation close to the code it describes.",
            "config": "Verify environment variables and paths before running.",
            "general": "Consider the approach carefully before starting.",
        }
        return suggestions.get(category, suggestions["general"])

    def get_success_rate_by_category(self) -> dict:
        """Get success rate breakdown by task category."""
        rates = {}

        for category, insight in self._insights.items():
            total = insight["success_count"] + insight["failure_count"]
            if total > 0:
                rates[category] = {
                    "success_rate": insight["success_count"] / total,
                    "total_tasks": total,
                    "effective_approaches": insight["effective_approaches"][:3],
                }

        return rates

    def get_recent_reflections(self, count: int = 10) -> list[dict]:
        """Get recent reflections for review."""
        return self._reflections[-count:]

    def clear_data(self):
        """Clear all reflection data."""
        self._reflections = []
        self._insights = {}
        self._save()


# Global instance
_reflection_engine: ReflectionEngine | None = None


def get_reflection_engine() -> ReflectionEngine:
    """Get or create the global reflection engine."""
    global _reflection_engine
    if _reflection_engine is None:
        _reflection_engine = ReflectionEngine()
    return _reflection_engine


def reflect_on_completion(
    task_description: str,
    approach_taken: str,
    result: str,
    success: bool,
    tools_used: list = None,
    duration_seconds: float = 0,
) -> TaskReflection:
    """Convenience function to reflect on task completion."""
    return get_reflection_engine().reflect_on_completion(
        task_description, approach_taken, result, success, tools_used, duration_seconds
    )


def get_improvement_opportunities() -> list[dict]:
    """Convenience function to get improvement opportunities."""
    return get_reflection_engine().get_improvement_opportunities()
