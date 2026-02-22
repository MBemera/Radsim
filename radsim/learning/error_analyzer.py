"""Error Pattern Detection and Prevention.

Learn from errors to prevent future mistakes. Tracks error patterns,
warns before repeating mistakes, and suggests fixes based on history.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class ErrorRecord:
    """A recorded error with context and correction."""

    error_type: str  # validation, tool_error, syntax, logic, safety
    error_message: str
    context: dict
    correction: str = ""
    timestamp: str = ""
    frequency: int = 1

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class ErrorAnalyzer:
    """Learn from errors to prevent future mistakes.

    Tracks error patterns, detects similar errors before they happen,
    and suggests fixes based on historical corrections.
    """

    def __init__(self, storage_dir: Path = None):
        self.storage_dir = storage_dir or Path.home() / ".radsim" / "learning"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.errors_file = self.storage_dir / "errors.json"
        self.patterns_file = self.storage_dir / "error_patterns.json"

        self._errors: list[dict] = []
        self._patterns: dict[str, dict] = {}
        self._load()

    def _load(self):
        """Load error history from disk."""
        if self.errors_file.exists():
            try:
                self._errors = json.loads(self.errors_file.read_text())
            except (OSError, json.JSONDecodeError):
                self._errors = []

        if self.patterns_file.exists():
            try:
                self._patterns = json.loads(self.patterns_file.read_text())
            except (OSError, json.JSONDecodeError):
                self._patterns = {}

    def _save(self):
        """Persist error history to disk."""
        self.errors_file.write_text(json.dumps(self._errors, indent=2))
        self.patterns_file.write_text(json.dumps(self._patterns, indent=2))

    def _hash_error(self, error_type: str, error_message: str) -> str:
        """Generate a unique hash for an error."""
        content = f"{error_type}:{error_message[:100]}"
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def record_error(
        self,
        error_type: str,
        error_message: str,
        context: dict = None,
        correction: str = "",
    ):
        """Log an error and its fix for future learning.

        Args:
            error_type: Category (validation, tool_error, syntax, logic, safety)
            error_message: The error message
            context: Tool name, file type, task description, etc.
            correction: How the error was fixed
        """
        context = context or {}

        error_record = {
            "error_type": error_type,
            "error_message": error_message,
            "context": {
                "tool_name": context.get("tool_name", ""),
                "file_type": context.get("file_type", ""),
                "task_description": context.get("task_description", ""),
                "tool_input": str(context.get("tool_input", ""))[:500],
            },
            "correction": correction,
            "timestamp": datetime.now().isoformat(),
            "hash": self._hash_error(error_type, error_message),
        }

        self._errors.append(error_record)

        # Update pattern frequency
        pattern_key = f"{error_type}:{error_message[:50]}"
        if pattern_key not in self._patterns:
            self._patterns[pattern_key] = {
                "error_type": error_type,
                "message_prefix": error_message[:100],
                "frequency": 0,
                "corrections": [],
                "contexts": [],
            }

        self._patterns[pattern_key]["frequency"] += 1
        if correction and correction not in self._patterns[pattern_key]["corrections"]:
            self._patterns[pattern_key]["corrections"].append(correction)
        if context.get("tool_name"):
            tool = context["tool_name"]
            if tool not in self._patterns[pattern_key]["contexts"]:
                self._patterns[pattern_key]["contexts"].append(tool)

        # Keep only last 500 errors
        if len(self._errors) > 500:
            self._errors = self._errors[-500:]

        self._save()

    def check_similar_error(self, planned_action: str, tool_name: str = "") -> dict:
        """Check if a planned action might cause a known error.

        Args:
            planned_action: Description of what's about to be done
            tool_name: The tool being used

        Returns:
            Dict with error_found, warning message, and suggested solution
        """
        planned_lower = planned_action.lower()

        # Check recent errors for similar patterns
        for error in reversed(self._errors[-50:]):
            error_context = error.get("context", {})

            # Check tool match
            if tool_name and error_context.get("tool_name") == tool_name:
                # Check for similar task description
                task_desc = error_context.get("task_description", "").lower()
                if task_desc and self._similarity_score(planned_lower, task_desc) > 0.5:
                    return {
                        "error_found": True,
                        "warning": f"Similar error occurred before: {error['error_message'][:100]}",
                        "solution": error.get("correction", "No recorded fix"),
                        "error_type": error["error_type"],
                    }

        # Check pattern frequency
        for _pattern_key, pattern in self._patterns.items():
            if pattern["frequency"] >= 3:
                if tool_name in pattern.get("contexts", []):
                    return {
                        "error_found": True,
                        "warning": f"Frequent error pattern ({pattern['frequency']}x): {pattern['message_prefix']}",
                        "solution": pattern["corrections"][0] if pattern["corrections"] else "Check logs",
                        "error_type": pattern["error_type"],
                    }

        return {"error_found": False}

    def _similarity_score(self, text1: str, text2: str) -> float:
        """Simple word overlap similarity score."""
        words1 = set(text1.split())
        words2 = set(text2.split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)

    def get_error_patterns(self, min_frequency: int = 2) -> list[dict]:
        """Get frequently occurring error patterns.

        Args:
            min_frequency: Minimum occurrences to include

        Returns:
            List of error patterns sorted by frequency
        """
        patterns = [
            {
                "pattern": key,
                "error_type": data["error_type"],
                "message": data["message_prefix"],
                "frequency": data["frequency"],
                "solutions": data["corrections"],
                "tools_affected": data["contexts"],
            }
            for key, data in self._patterns.items()
            if data["frequency"] >= min_frequency
        ]

        return sorted(patterns, key=lambda x: x["frequency"], reverse=True)

    def get_error_stats(self) -> dict:
        """Get error statistics summary."""
        if not self._errors:
            return {
                "total_errors": 0,
                "unique_patterns": 0,
                "by_type": {},
                "most_common": [],
            }

        by_type = {}
        for error in self._errors:
            etype = error["error_type"]
            by_type[etype] = by_type.get(etype, 0) + 1

        most_common = self.get_error_patterns(min_frequency=1)[:5]

        return {
            "total_errors": len(self._errors),
            "unique_patterns": len(self._patterns),
            "by_type": by_type,
            "most_common": most_common,
        }

    def get_prevention_rules(self) -> list[str]:
        """Generate prevention rules from learned patterns."""
        rules = []

        for pattern in self.get_error_patterns(min_frequency=3):
            if pattern["solutions"]:
                rule = f"When using {', '.join(pattern['tools_affected']) or 'tools'}: {pattern['solutions'][0]}"
                rules.append(rule)

        return rules[:10]  # Top 10 rules

    def clear_history(self):
        """Clear all error history."""
        self._errors = []
        self._patterns = {}
        self._save()


# Global instance
_error_analyzer: ErrorAnalyzer | None = None


def get_error_analyzer() -> ErrorAnalyzer:
    """Get or create the global error analyzer."""
    global _error_analyzer
    if _error_analyzer is None:
        _error_analyzer = ErrorAnalyzer()
    return _error_analyzer


def record_error(
    error_type: str,
    error_message: str,
    context: dict = None,
    correction: str = "",
):
    """Convenience function to record an error."""
    get_error_analyzer().record_error(error_type, error_message, context, correction)


def check_similar_error(planned_action: str, tool_name: str = "") -> dict:
    """Convenience function to check for similar errors."""
    return get_error_analyzer().check_similar_error(planned_action, tool_name)


def get_error_patterns(min_frequency: int = 2) -> list[dict]:
    """Convenience function to get error patterns."""
    return get_error_analyzer().get_error_patterns(min_frequency)
