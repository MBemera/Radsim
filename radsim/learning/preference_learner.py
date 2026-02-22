"""Preference Learning from User Feedback.

Learn user preferences from implicit and explicit feedback signals.
Adapts system prompts and suggestions based on learned preferences.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class FeedbackSignal:
    """A user feedback signal."""

    action: str  # accept, modify, reject, good, improve
    suggestion_hash: str
    suggestion_preview: str
    modification: str = ""
    timestamp: str = ""
    quality_score: float = 0.5

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class PreferenceLearner:
    """Learn user preferences from implicit and explicit feedback.

    Tracks:
    - Code style preferences (indentation, naming, comments)
    - Verbosity preferences (brief vs detailed explanations)
    - Tool preferences (which tools user prefers)
    - Domain preferences (web, data, devops, etc.)
    """

    def __init__(self, storage_dir: Path = None):
        self.storage_dir = storage_dir or Path.home() / ".radsim" / "learning"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.prefs_file = self.storage_dir / "preferences.json"
        self.feedback_file = self.storage_dir / "feedback.json"

        self._preferences: dict = {}
        self._feedback: list[dict] = []
        self._load()

    def _load(self):
        """Load preferences from disk."""
        if self.prefs_file.exists():
            try:
                self._preferences = json.loads(self.prefs_file.read_text())
            except (OSError, json.JSONDecodeError):
                self._preferences = {}

        if self.feedback_file.exists():
            try:
                self._feedback = json.loads(self.feedback_file.read_text())
            except (OSError, json.JSONDecodeError):
                self._feedback = []

    def _save(self):
        """Persist preferences to disk."""
        self.prefs_file.write_text(json.dumps(self._preferences, indent=2))
        self.feedback_file.write_text(json.dumps(self._feedback, indent=2))

    def record_feedback(
        self,
        action: str,
        suggestion: str,
        modification: str = "",
        metadata: dict = None,
    ):
        """Record user feedback on a suggestion.

        Args:
            action: accept, modify, reject, good, improve
            suggestion: The original suggestion
            modification: What user changed (if modified)
            metadata: Additional context
        """
        metadata = metadata or {}

        # Calculate implicit quality score
        quality_scores = {
            "accept": 0.9,
            "good": 1.0,
            "modify": 0.6,
            "improve": 0.3,
            "reject": 0.1,
        }
        quality_score = quality_scores.get(action, 0.5)

        feedback_record = {
            "action": action,
            "suggestion_preview": suggestion[:200],
            "modification": modification[:500] if modification else "",
            "quality_score": quality_score,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata,
        }

        self._feedback.append(feedback_record)

        # Learn from feedback
        self._learn_from_feedback(action, suggestion, modification, metadata)

        # Keep only last 200 feedback entries
        if len(self._feedback) > 200:
            self._feedback = self._feedback[-200:]

        self._save()

    def _learn_from_feedback(
        self,
        action: str,
        suggestion: str,
        modification: str,
        metadata: dict,
    ):
        """Extract preferences from feedback."""
        # Learn code style from modifications
        if modification and action == "modify":
            self._learn_code_style(suggestion, modification)

        # Learn verbosity preference
        if action == "good":
            word_count = len(suggestion.split())
            self._update_verbosity_preference(word_count, positive=True)
        elif action == "improve" and "verbose" in modification.lower():
            self._preferences["verbosity"] = "high"
        elif action == "improve" and "brief" in modification.lower():
            self._preferences["verbosity"] = "low"

        # Learn tool preferences from metadata
        if "tool_name" in metadata:
            tool = metadata["tool_name"]
            if action in ("accept", "good"):
                self._increment_tool_preference(tool, positive=True)
            elif action == "reject":
                self._increment_tool_preference(tool, positive=False)

    def _learn_code_style(self, original: str, modified: str):
        """Learn code style preferences from user modifications."""
        # Detect indentation preference
        original_indent = self._detect_indentation(original)
        modified_indent = self._detect_indentation(modified)

        if modified_indent and modified_indent != original_indent:
            self._preferences["code_indentation"] = modified_indent

        # Detect naming convention changes
        if self._uses_snake_case(modified) and not self._uses_snake_case(original):
            self._preferences["naming_convention"] = "snake_case"
        elif self._uses_camel_case(modified) and not self._uses_camel_case(original):
            self._preferences["naming_convention"] = "camelCase"

        # Detect comment style preference
        if "# " in modified and "# " not in original:
            self._preferences["prefers_comments"] = True
        elif "# " not in modified and "# " in original:
            self._preferences["prefers_comments"] = False

        # Detect type hints preference
        if ": " in modified and "->" in modified:
            self._preferences["prefers_type_hints"] = True

    def _detect_indentation(self, code: str) -> int | None:
        """Detect indentation size from code."""
        lines = code.split("\n")
        indents = []

        for line in lines:
            if line and line[0] == " ":
                spaces = len(line) - len(line.lstrip(" "))
                if spaces > 0:
                    indents.append(spaces)

        if not indents:
            return None

        # Find most common indent unit
        min_indent = min(indents) if indents else 4
        return min_indent if min_indent in (2, 4) else 4

    def _uses_snake_case(self, text: str) -> bool:
        """Check if text uses snake_case naming."""
        return bool(re.search(r"\b[a-z]+_[a-z]+\b", text))

    def _uses_camel_case(self, text: str) -> bool:
        """Check if text uses camelCase naming."""
        return bool(re.search(r"\b[a-z]+[A-Z][a-z]+\b", text))

    def _update_verbosity_preference(self, word_count: int, positive: bool):
        """Update verbosity preference based on feedback."""
        current = self._preferences.get("verbosity_scores", [])
        current.append({"count": word_count, "liked": positive})

        # Keep last 20
        current = current[-20:]
        self._preferences["verbosity_scores"] = current

        # Calculate preference
        liked_counts = [s["count"] for s in current if s["liked"]]
        if liked_counts:
            avg = sum(liked_counts) / len(liked_counts)
            if avg > 200:
                self._preferences["verbosity"] = "high"
            elif avg < 50:
                self._preferences["verbosity"] = "low"
            else:
                self._preferences["verbosity"] = "medium"

    def _increment_tool_preference(self, tool_name: str, positive: bool):
        """Track tool preference scores."""
        tool_scores = self._preferences.get("tool_scores", {})

        if tool_name not in tool_scores:
            tool_scores[tool_name] = {"positive": 0, "negative": 0}

        if positive:
            tool_scores[tool_name]["positive"] += 1
        else:
            tool_scores[tool_name]["negative"] += 1

        self._preferences["tool_scores"] = tool_scores

    def get_learned_preferences(self) -> dict:
        """Get all learned user preferences."""
        preferences = {
            "code_style": {
                "indentation": self._preferences.get("code_indentation", 4),
                "naming_convention": self._preferences.get("naming_convention", "snake_case"),
                "prefers_comments": self._preferences.get("prefers_comments", False),
                "prefers_type_hints": self._preferences.get("prefers_type_hints", False),
            },
            "verbosity": self._preferences.get("verbosity", "medium"),
            "preferred_tools": self._get_preferred_tools(),
            "feedback_quality_avg": self._calculate_avg_quality(),
        }

        return preferences

    def _get_preferred_tools(self) -> list[str]:
        """Get list of preferred tools based on feedback."""
        tool_scores = self._preferences.get("tool_scores", {})

        ranked = []
        for tool, scores in tool_scores.items():
            total = scores["positive"] + scores["negative"]
            if total >= 3:
                ratio = scores["positive"] / total
                ranked.append((tool, ratio))

        ranked.sort(key=lambda x: x[1], reverse=True)
        return [tool for tool, _ in ranked[:5]]

    def _calculate_avg_quality(self) -> float:
        """Calculate average quality score from feedback."""
        if not self._feedback:
            return 0.5

        scores = [f["quality_score"] for f in self._feedback[-50:]]
        return sum(scores) / len(scores)

    def adjust_prompt_for_preferences(self, base_prompt: str) -> str:
        """Modify system prompt based on learned preferences."""
        prefs = self.get_learned_preferences()
        additions = []

        # Code style preferences
        style = prefs["code_style"]
        if style["indentation"] == 2:
            additions.append("Use 2-space indentation.")
        elif style["indentation"] == 4:
            additions.append("Use 4-space indentation.")

        if style["naming_convention"] == "camelCase":
            additions.append("Use camelCase for variable and function names.")

        if style["prefers_comments"]:
            additions.append("Include helpful comments in code.")

        if style["prefers_type_hints"]:
            additions.append("Include type hints in Python code.")

        # Verbosity preference
        verbosity = prefs["verbosity"]
        if verbosity == "high":
            additions.append("Provide detailed explanations for each step.")
        elif verbosity == "low":
            additions.append("Keep explanations brief and to the point.")

        if not additions:
            return base_prompt

        preference_section = "\n\n## User Preferences (Learned)\n" + "\n".join(
            f"- {a}" for a in additions
        )

        return base_prompt + preference_section

    def set_preference(self, key: str, value):
        """Manually set a preference."""
        self._preferences[key] = value
        self._save()

    def get_preference(self, key: str, default=None):
        """Get a specific preference."""
        return self._preferences.get(key, default)

    def clear_preferences(self):
        """Clear all learned preferences."""
        self._preferences = {}
        self._feedback = []
        self._save()

    def get_feedback_summary(self) -> dict:
        """Get summary of feedback received."""
        if not self._feedback:
            return {"total": 0, "by_action": {}}

        by_action = {}
        for fb in self._feedback:
            action = fb["action"]
            by_action[action] = by_action.get(action, 0) + 1

        return {
            "total": len(self._feedback),
            "by_action": by_action,
            "avg_quality": self._calculate_avg_quality(),
        }


# Global instance
_preference_learner: PreferenceLearner | None = None


def get_preference_learner() -> PreferenceLearner:
    """Get or create the global preference learner."""
    global _preference_learner
    if _preference_learner is None:
        _preference_learner = PreferenceLearner()
    return _preference_learner


def record_feedback(
    action: str,
    suggestion: str,
    modification: str = "",
    metadata: dict = None,
):
    """Convenience function to record feedback."""
    get_preference_learner().record_feedback(action, suggestion, modification, metadata)


def get_learned_preferences() -> dict:
    """Convenience function to get learned preferences."""
    return get_preference_learner().get_learned_preferences()


def adjust_prompt_for_preferences(base_prompt: str) -> str:
    """Convenience function to adjust prompt for preferences."""
    return get_preference_learner().adjust_prompt_for_preferences(base_prompt)
