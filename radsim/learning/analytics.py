"""Learning Analytics and Dashboard.

Provides visibility into what the agent has learned and allows
users to audit, control, and reset learned behaviors.
"""

import json
from datetime import datetime
from pathlib import Path

from .error_analyzer import get_error_analyzer
from .few_shot_assembler import get_few_shot_assembler
from .preference_learner import get_preference_learner
from .reflection_engine import get_reflection_engine
from .tool_optimizer import get_tool_optimizer


class LearningAnalytics:
    """Provides insights into learned preferences and patterns.

    Aggregates data from all learning modules and provides:
    - Statistics summaries
    - Learning reports
    - Audit trails
    - Reset capabilities
    """

    VALID_CATEGORIES = [
        "all",
        "preferences",
        "errors",
        "examples",
        "tools",
        "reflections",
    ]

    def __init__(self, storage_dir: Path = None):
        self.storage_dir = storage_dir or Path.home() / ".radsim" / "learning"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def get_learning_stats(self) -> dict:
        """Return comprehensive learning metrics."""
        error_analyzer = get_error_analyzer()
        preference_learner = get_preference_learner()
        few_shot = get_few_shot_assembler()
        tool_optimizer = get_tool_optimizer()
        reflection_engine = get_reflection_engine()

        error_stats = error_analyzer.get_error_stats()
        pref_summary = preference_learner.get_feedback_summary()
        example_stats = few_shot.get_examples_stats()
        tool_rankings = tool_optimizer.get_tool_rankings()
        success_rates = reflection_engine.get_success_rate_by_category()

        # Calculate overall success rate
        total_success = sum(
            r["success_rate"] * r["total_tasks"]
            for r in success_rates.values()
        )
        total_tasks = sum(r["total_tasks"] for r in success_rates.values())
        overall_success_rate = total_success / total_tasks if total_tasks > 0 else 0

        # Self-improvement stats
        self_improvement_stats = {}
        try:
            from .self_improver import get_self_improver
            self_improvement_stats = get_self_improver().get_stats()
        except Exception:
            self_improvement_stats = {"total_proposals": 0}

        return {
            "summary": {
                "total_errors_tracked": error_stats["total_errors"],
                "total_feedback_received": pref_summary["total"],
                "total_examples_stored": example_stats["total"],
                "total_tools_tracked": len(tool_rankings),
                "overall_task_success_rate": overall_success_rate,
                "total_tasks_completed": total_tasks,
            },
            "errors": error_stats,
            "feedback": pref_summary,
            "examples": example_stats,
            "tools": {
                "top_tools": tool_rankings[:5] if tool_rankings else [],
                "slow_tools": tool_optimizer.get_slow_tools(),
                "unreliable_tools": tool_optimizer.get_unreliable_tools(),
            },
            "task_categories": success_rates,
            "learned_preferences": preference_learner.get_learned_preferences(),
            "improvement_opportunities": reflection_engine.get_improvement_opportunities(),
            "self_improvement": self_improvement_stats,
        }

    def export_learning_report(self, format: str = "text") -> str:
        """Generate human-readable learning report.

        Args:
            format: Output format ('text' or 'json')

        Returns:
            Formatted report string
        """
        stats = self.get_learning_stats()

        if format == "json":
            return json.dumps(stats, indent=2, default=str)

        # Text format
        report = f"""
╔══════════════════════════════════════════════════════════════════╗
║                    RADSIM LEARNING REPORT                        ║
║                    Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}                    ║
╚══════════════════════════════════════════════════════════════════╝

═══ SUMMARY ═══════════════════════════════════════════════════════
  Total Tasks Completed:     {stats['summary']['total_tasks_completed']}
  Overall Success Rate:      {stats['summary']['overall_task_success_rate']:.1%}
  Errors Tracked:            {stats['summary']['total_errors_tracked']}
  Feedback Received:         {stats['summary']['total_feedback_received']}
  Examples Stored:           {stats['summary']['total_examples_stored']}
  Tools Tracked:             {stats['summary']['total_tools_tracked']}

═══ LEARNED PREFERENCES ═══════════════════════════════════════════
{self._format_preferences(stats['learned_preferences'])}

═══ TOP PERFORMING TOOLS ══════════════════════════════════════════
{self._format_tools(stats['tools']['top_tools'])}

═══ IMPROVEMENT OPPORTUNITIES ═════════════════════════════════════
{self._format_improvements(stats['improvement_opportunities'])}

═══ ERROR PATTERNS ════════════════════════════════════════════════
  Total Errors:      {stats['errors']['total_errors']}
  Unique Patterns:   {stats['errors']['unique_patterns']}
  By Type:           {self._format_dict(stats['errors']['by_type'])}

═══ TASK SUCCESS BY CATEGORY ══════════════════════════════════════
{self._format_categories(stats['task_categories'])}

═══ SELF-IMPROVEMENT ═════════════════════════════════════════════
{self._format_self_improvement(stats.get('self_improvement', {}))}

══════════════════════════════════════════════════════════════════
                          END OF REPORT
══════════════════════════════════════════════════════════════════
"""
        return report

    def _format_preferences(self, prefs: dict) -> str:
        """Format preferences for display."""
        if not prefs:
            return "  No preferences learned yet."

        lines = []
        style = prefs.get("code_style", {})

        lines.append(f"  Code Indentation:    {style.get('indentation', 4)} spaces")
        lines.append(f"  Naming Convention:   {style.get('naming_convention', 'snake_case')}")
        lines.append(f"  Prefers Comments:    {'Yes' if style.get('prefers_comments') else 'No'}")
        lines.append(f"  Prefers Type Hints:  {'Yes' if style.get('prefers_type_hints') else 'No'}")
        lines.append(f"  Verbosity:           {prefs.get('verbosity', 'medium')}")

        preferred_tools = prefs.get("preferred_tools", [])
        if preferred_tools:
            lines.append(f"  Preferred Tools:     {', '.join(preferred_tools[:5])}")

        return "\n".join(lines)

    def _format_tools(self, tools: list) -> str:
        """Format tool rankings for display."""
        if not tools:
            return "  No tool data yet."

        lines = []
        for i, tool in enumerate(tools[:5], 1):
            lines.append(
                f"  {i}. {tool['tool_name']:<20} "
                f"Success: {tool['success_rate']:.0%}  "
                f"Avg: {tool['avg_duration_ms']:.0f}ms  "
                f"Uses: {tool['total_uses']}"
            )
        return "\n".join(lines)

    def _format_improvements(self, opportunities: list) -> str:
        """Format improvement opportunities for display."""
        if not opportunities:
            return "  No improvement areas identified."

        lines = []
        for opp in opportunities[:3]:
            lines.append(f"  • {opp['category'].upper()}: {opp['suggestion']}")
            if opp.get('failure_count'):
                lines.append(f"    ({opp['failure_count']} failures in this category)")

        return "\n".join(lines)

    def _format_dict(self, d: dict) -> str:
        """Format a dictionary for display."""
        if not d:
            return "None"
        return ", ".join(f"{k}: {v}" for k, v in d.items())

    def _format_categories(self, categories: dict) -> str:
        """Format task categories for display."""
        if not categories:
            return "  No task data yet."

        lines = []
        for cat, data in sorted(
            categories.items(),
            key=lambda x: x[1]["total_tasks"],
            reverse=True,
        ):
            lines.append(
                f"  {cat:<12} "
                f"Success: {data['success_rate']:.0%}  "
                f"Tasks: {data['total_tasks']}"
            )
        return "\n".join(lines)

    def _format_self_improvement(self, si_stats: dict) -> str:
        """Format self-improvement statistics for display."""
        if not si_stats or si_stats.get("total_proposals", 0) == 0:
            return "  No self-improvement data yet. Enable with /settings self_improvement.enabled true"

        lines = []
        lines.append(f"  Total Proposals:  {si_stats.get('total_proposals', 0)}")
        lines.append(f"  Approved:         {si_stats.get('approved_count', 0)}")
        lines.append(f"  Rejected:         {si_stats.get('rejected_count', 0)}")
        lines.append(f"  Pending:          {si_stats.get('pending_count', 0)}")
        lines.append(f"  Approval Rate:    {si_stats.get('approval_rate', 0):.0%}")
        return "\n".join(lines)

    def audit_learned_preferences(self) -> dict:
        """Show user exactly what was learned and allow corrections.

        Returns:
            Dictionary of all learned items with metadata
        """
        preference_learner = get_preference_learner()
        prefs = preference_learner.get_learned_preferences()

        audit_report = {}

        for category, values in prefs.items():
            if isinstance(values, dict):
                for key, value in values.items():
                    audit_report[f"{category}.{key}"] = {
                        "current_value": value,
                        "category": category,
                        "can_reset": True,
                    }
            else:
                audit_report[category] = {
                    "current_value": values,
                    "category": "general",
                    "can_reset": True,
                }

        return audit_report

    def reset_learning_category(self, category: str) -> dict:
        """Reset a specific category of learned data.

        Args:
            category: One of 'all', 'preferences', 'errors', 'examples',
                     'tools', 'reflections'

        Returns:
            Status dict with success/failure message
        """
        if category not in self.VALID_CATEGORIES:
            return {
                "success": False,
                "error": f"Invalid category: {category}",
                "valid_categories": self.VALID_CATEGORIES,
            }

        try:
            if category in ("all", "preferences"):
                get_preference_learner().clear_preferences()

            if category in ("all", "errors"):
                get_error_analyzer().clear_history()

            if category in ("all", "examples"):
                get_few_shot_assembler().clear_examples()

            if category in ("all", "tools"):
                get_tool_optimizer().clear_data()

            if category in ("all", "reflections"):
                get_reflection_engine().clear_data()

            return {
                "success": True,
                "message": f"Successfully reset '{category}' learning data.",
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def get_learning_timeline(self, days: int = 7) -> list[dict]:
        """Get learning activity over recent days.

        Args:
            days: Number of days to include

        Returns:
            List of daily learning summaries
        """
        # This would aggregate timestamps from all modules
        # For now, return a placeholder
        return [
            {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "tasks_completed": 0,
                "errors_recorded": 0,
                "feedback_received": 0,
            }
        ]


# Global instance
_analytics: LearningAnalytics | None = None


def get_analytics() -> LearningAnalytics:
    """Get or create the global analytics instance."""
    global _analytics
    if _analytics is None:
        _analytics = LearningAnalytics()
    return _analytics


def get_learning_stats() -> dict:
    """Convenience function to get learning stats."""
    return get_analytics().get_learning_stats()


def export_learning_report(format: str = "text") -> str:
    """Convenience function to export learning report."""
    return get_analytics().export_learning_report(format)


def reset_learning_category(category: str) -> dict:
    """Convenience function to reset a learning category."""
    return get_analytics().reset_learning_category(category)
