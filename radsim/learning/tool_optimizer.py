"""Tool Effectiveness Learning.

Learn which tools work best for different tasks and suggest
optimal tool chains based on past success.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class ToolExecution:
    """Record of a tool execution."""

    tool_name: str
    success: bool
    duration_ms: float
    input_size: int
    output_size: int
    error: str = ""
    task_context: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class ToolOptimizer:
    """Learn which tools work best for different tasks.

    Tracks:
    - Tool success rates
    - Tool execution times
    - Effective tool chains (sequences)
    - Context-specific tool performance
    """

    def __init__(self, storage_dir: Path = None):
        self.storage_dir = storage_dir or Path.home() / ".radsim" / "learning"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.executions_file = self.storage_dir / "tool_executions.json"
        self.chains_file = self.storage_dir / "tool_chains.json"
        self.scores_file = self.storage_dir / "tool_scores.json"

        self._executions: list[dict] = []
        self._chains: list[dict] = []
        self._scores: dict = {}
        self._current_chain: list[str] = []
        self._load()

    def _load(self):
        """Load tool data from disk."""
        if self.executions_file.exists():
            try:
                self._executions = json.loads(self.executions_file.read_text())
            except (OSError, json.JSONDecodeError):
                self._executions = []

        if self.chains_file.exists():
            try:
                self._chains = json.loads(self.chains_file.read_text())
            except (OSError, json.JSONDecodeError):
                self._chains = []

        if self.scores_file.exists():
            try:
                self._scores = json.loads(self.scores_file.read_text())
            except (OSError, json.JSONDecodeError):
                self._scores = {}

    def _save(self):
        """Persist tool data to disk."""
        self.executions_file.write_text(json.dumps(self._executions[-500:], indent=2))
        self.chains_file.write_text(json.dumps(self._chains[-100:], indent=2))
        self.scores_file.write_text(json.dumps(self._scores, indent=2))

    def track_tool_execution(
        self,
        tool_name: str,
        success: bool,
        duration_ms: float,
        input_data: dict = None,
        output_data: dict = None,
        error: str = "",
        task_context: str = "",
    ):
        """Record a tool execution.

        Args:
            tool_name: Name of the tool
            success: Whether execution succeeded
            duration_ms: Execution time in milliseconds
            input_data: Tool input (for size calculation)
            output_data: Tool output (for size calculation)
            error: Error message if failed
            task_context: Description of the task being performed
        """
        input_data = input_data or {}
        output_data = output_data or {}

        execution = {
            "tool_name": tool_name,
            "success": success,
            "duration_ms": duration_ms,
            "input_size": len(str(input_data)),
            "output_size": len(str(output_data)),
            "error": error[:200] if error else "",
            "task_context": task_context[:100] if task_context else "",
            "timestamp": datetime.now().isoformat(),
        }

        self._executions.append(execution)
        self._current_chain.append(tool_name)

        # Update tool scores
        self._update_tool_score(tool_name, success, duration_ms)

        self._save()

    def _update_tool_score(self, tool_name: str, success: bool, duration_ms: float):
        """Update running effectiveness score for a tool."""
        if tool_name not in self._scores:
            self._scores[tool_name] = {
                "total_uses": 0,
                "successes": 0,
                "failures": 0,
                "total_duration_ms": 0,
                "success_rate": 0.0,
                "avg_duration_ms": 0.0,
            }

        score = self._scores[tool_name]
        score["total_uses"] += 1
        score["total_duration_ms"] += duration_ms

        if success:
            score["successes"] += 1
        else:
            score["failures"] += 1

        score["success_rate"] = score["successes"] / score["total_uses"]
        score["avg_duration_ms"] = score["total_duration_ms"] / score["total_uses"]

    def complete_task_chain(self, task_description: str, success: bool):
        """Mark current tool chain as complete for a task.

        Args:
            task_description: What task was being performed
            success: Whether the overall task succeeded
        """
        if not self._current_chain:
            return

        chain_record = {
            "tools_used": self._current_chain.copy(),
            "task_description": task_description[:200],
            "success": success,
            "timestamp": datetime.now().isoformat(),
            "tool_count": len(self._current_chain),
        }

        self._chains.append(chain_record)
        self._current_chain = []  # Reset for next task

        self._save()

    def suggest_tool_chain(self, task_description: str) -> list[str]:
        """Suggest a sequence of tools based on past success.

        Args:
            task_description: The task to perform

        Returns:
            List of suggested tool names in order
        """
        if not self._chains:
            return []

        # Find similar successful tasks
        task_lower = task_description.lower()
        task_words = set(task_lower.split())

        best_match = None
        best_score = 0

        for chain in self._chains:
            if not chain.get("success"):
                continue

            chain_desc = chain.get("task_description", "").lower()
            chain_words = set(chain_desc.split())

            # Word overlap score
            if chain_words:
                overlap = len(task_words & chain_words)
                score = overlap / max(len(task_words), len(chain_words))

                if score > best_score:
                    best_score = score
                    best_match = chain

        if best_match and best_score > 0.3:
            return best_match["tools_used"]

        return []

    def get_tool_rankings(self, context: str = "") -> list[dict]:
        """Get tools ranked by effectiveness.

        Args:
            context: Optional context to filter by

        Returns:
            List of tools with their effectiveness scores
        """
        if not self._scores:
            return []

        rankings = []
        for tool_name, score in self._scores.items():
            if score["total_uses"] >= 2:  # Minimum usage threshold
                rankings.append({
                    "tool_name": tool_name,
                    "success_rate": score["success_rate"],
                    "avg_duration_ms": score["avg_duration_ms"],
                    "total_uses": score["total_uses"],
                    "reliability_score": self._calculate_reliability(score),
                })

        # Sort by reliability score
        rankings.sort(key=lambda x: x["reliability_score"], reverse=True)
        return rankings

    def _calculate_reliability(self, score: dict) -> float:
        """Calculate overall reliability score for a tool."""
        # Weight success rate heavily, penalize slow tools slightly
        success_weight = 0.7
        speed_weight = 0.3

        # Normalize duration (assume 5000ms is slow)
        speed_score = max(0, 1 - (score["avg_duration_ms"] / 5000))

        return (score["success_rate"] * success_weight) + (speed_score * speed_weight)

    def get_tool_stats(self, tool_name: str) -> dict:
        """Get detailed statistics for a specific tool."""
        if tool_name not in self._scores:
            return {"tool_name": tool_name, "total_uses": 0, "message": "No data"}

        score = self._scores[tool_name]

        # Get recent executions for this tool
        recent = [
            e for e in self._executions[-100:]
            if e["tool_name"] == tool_name
        ]

        # Calculate trend
        if len(recent) >= 5:
            first_half = recent[:len(recent)//2]
            second_half = recent[len(recent)//2:]

            first_success = sum(1 for e in first_half if e["success"]) / len(first_half)
            second_success = sum(1 for e in second_half if e["success"]) / len(second_half)

            trend = "improving" if second_success > first_success else (
                "declining" if second_success < first_success else "stable"
            )
        else:
            trend = "insufficient_data"

        return {
            "tool_name": tool_name,
            "total_uses": score["total_uses"],
            "success_rate": score["success_rate"],
            "avg_duration_ms": score["avg_duration_ms"],
            "trend": trend,
            "recent_errors": [
                e["error"] for e in recent if e.get("error")
            ][-3:],
        }

    def get_common_chains(self) -> list[dict]:
        """Get commonly used successful tool chains."""
        if not self._chains:
            return []

        # Group by tool sequence
        chain_groups = {}
        for chain in self._chains:
            if not chain.get("success"):
                continue

            key = "->".join(chain["tools_used"])
            if key not in chain_groups:
                chain_groups[key] = {
                    "tools": chain["tools_used"],
                    "count": 0,
                    "sample_tasks": [],
                }
            chain_groups[key]["count"] += 1
            if len(chain_groups[key]["sample_tasks"]) < 3:
                chain_groups[key]["sample_tasks"].append(
                    chain.get("task_description", "")
                )

        # Sort by frequency
        common = sorted(chain_groups.values(), key=lambda x: x["count"], reverse=True)
        return common[:10]

    def get_slow_tools(self, threshold_ms: float = 3000) -> list[dict]:
        """Get tools that are slower than threshold."""
        slow = []
        for tool_name, score in self._scores.items():
            if score["avg_duration_ms"] > threshold_ms:
                slow.append({
                    "tool_name": tool_name,
                    "avg_duration_ms": score["avg_duration_ms"],
                    "total_uses": score["total_uses"],
                })

        return sorted(slow, key=lambda x: x["avg_duration_ms"], reverse=True)

    def get_unreliable_tools(self, threshold: float = 0.7) -> list[dict]:
        """Get tools with success rate below threshold."""
        unreliable = []
        for tool_name, score in self._scores.items():
            if score["total_uses"] >= 3 and score["success_rate"] < threshold:
                unreliable.append({
                    "tool_name": tool_name,
                    "success_rate": score["success_rate"],
                    "total_uses": score["total_uses"],
                })

        return sorted(unreliable, key=lambda x: x["success_rate"])

    def clear_data(self):
        """Clear all tool data."""
        self._executions = []
        self._chains = []
        self._scores = {}
        self._current_chain = []
        self._save()


# Global instance
_tool_optimizer: ToolOptimizer | None = None


def get_tool_optimizer() -> ToolOptimizer:
    """Get or create the global tool optimizer."""
    global _tool_optimizer
    if _tool_optimizer is None:
        _tool_optimizer = ToolOptimizer()
    return _tool_optimizer


def track_tool_execution(
    tool_name: str,
    success: bool,
    duration_ms: float,
    input_data: dict = None,
    output_data: dict = None,
    error: str = "",
    task_context: str = "",
):
    """Convenience function to track tool execution."""
    get_tool_optimizer().track_tool_execution(
        tool_name, success, duration_ms, input_data, output_data, error, task_context
    )


def suggest_tool_chain(task_description: str) -> list[str]:
    """Convenience function to suggest tool chain."""
    return get_tool_optimizer().suggest_tool_chain(task_description)


def get_tool_rankings(context: str = "") -> list[dict]:
    """Convenience function to get tool rankings."""
    return get_tool_optimizer().get_tool_rankings(context)
