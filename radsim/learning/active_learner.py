"""Active Learning - Smart Question Asking.

Ask strategic clarifying questions when uncertain about user intent.
Reduces misunderstandings and learns from answers.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class UncertaintyAssessment:
    """Assessment of uncertainty about a task."""

    uncertainty_score: float  # 0.0 to 1.0
    factors: dict
    should_ask: bool
    suggested_questions: list


class ActiveLearner:
    """Ask clarifying questions when uncertain about user intent.

    Assesses uncertainty based on:
    - Ambiguous language in the request
    - Multiple valid approaches
    - Missing context
    - Conflicting with learned preferences
    """

    # Threshold above which to ask clarifying questions
    UNCERTAINTY_THRESHOLD = 0.4

    def __init__(self, storage_dir: Path = None):
        self.storage_dir = storage_dir or Path.home() / ".radsim" / "learning"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.qa_file = self.storage_dir / "clarifications.json"

        self._qa_history: list[dict] = []
        self._load()

    def _load(self):
        """Load Q&A history from disk."""
        if self.qa_file.exists():
            try:
                self._qa_history = json.loads(self.qa_file.read_text())
            except (OSError, json.JSONDecodeError):
                self._qa_history = []

    def _save(self):
        """Persist Q&A history to disk."""
        self.qa_file.write_text(json.dumps(self._qa_history, indent=2))

    def assess_uncertainty(
        self,
        user_input: str,
        task_context: dict = None,
    ) -> UncertaintyAssessment:
        """Measure how uncertain we are about the task.

        Args:
            user_input: The user's request
            task_context: Additional context (preferences, history)

        Returns:
            UncertaintyAssessment with score and suggested questions
        """
        task_context = task_context or {}

        factors = {
            "ambiguous_language": self._check_ambiguity(user_input),
            "multiple_approaches": self._count_valid_approaches(user_input),
            "missing_context": self._assess_missing_info(user_input, task_context),
            "vague_scope": self._check_scope_clarity(user_input),
        }

        # Calculate weighted uncertainty score
        weights = {
            "ambiguous_language": 0.25,
            "multiple_approaches": 0.30,
            "missing_context": 0.30,
            "vague_scope": 0.15,
        }

        total_uncertainty = sum(
            factors[k] * weights[k] for k in factors
        )

        should_ask = total_uncertainty > self.UNCERTAINTY_THRESHOLD

        suggested_questions = []
        if should_ask:
            suggested_questions = self._generate_questions(user_input, factors)

        return UncertaintyAssessment(
            uncertainty_score=total_uncertainty,
            factors=factors,
            should_ask=should_ask,
            suggested_questions=suggested_questions,
        )

    def _check_ambiguity(self, text: str) -> float:
        """Check for ambiguous language."""
        ambiguous_terms = [
            "simple", "basic", "quick", "easy", "good", "better",
            "nice", "clean", "proper", "appropriate", "standard",
            "normal", "usual", "typical", "common", "general",
            "some", "few", "several", "various", "multiple",
            "etc", "and so on", "or something", "kind of", "sort of",
        ]

        text_lower = text.lower()
        matches = sum(1 for term in ambiguous_terms if term in text_lower)

        # Normalize: 0-3 matches = proportional, 4+ = max
        return min(matches / 3, 1.0)

    def _count_valid_approaches(self, text: str) -> float:
        """Estimate number of valid approaches for the task."""
        approach_indicators = {
            # Multiple technology choices
            "api": ["rest", "graphql", "grpc", "soap"],
            "database": ["sql", "nosql", "postgresql", "mongodb", "sqlite"],
            "auth": ["jwt", "oauth", "session", "api key"],
            "frontend": ["react", "vue", "svelte", "vanilla"],
            "backend": ["flask", "fastapi", "django", "express"],
            "testing": ["pytest", "unittest", "jest", "mocha"],
            "deploy": ["docker", "kubernetes", "serverless", "vm"],
        }

        text_lower = text.lower()
        choices_available = 0

        for category, options in approach_indicators.items():
            # If the category is mentioned but specific option isn't
            if category in text_lower:
                option_mentioned = any(opt in text_lower for opt in options)
                if not option_mentioned:
                    choices_available += 1

        # Normalize: 0 choices = 0, 3+ = 1.0
        return min(choices_available / 3, 1.0)

    def _assess_missing_info(self, text: str, context: dict) -> float:
        """Assess how much context is missing."""
        missing_factors = 0
        total_factors = 0

        # Check for file/path specification
        total_factors += 1
        if not re.search(r"[./\\][\w]+\.\w+", text):  # No file path
            if "file" in text.lower() or "code" in text.lower():
                missing_factors += 1

        # Check for language specification
        total_factors += 1
        languages = ["python", "javascript", "typescript", "go", "rust", "java", "ruby"]
        if not any(lang in text.lower() for lang in languages):
            if "function" in text.lower() or "class" in text.lower():
                missing_factors += 1

        # Check for scope specification
        total_factors += 1
        scope_words = ["all", "every", "entire", "whole", "single", "one", "specific"]
        if not any(word in text.lower() for word in scope_words):
            if "change" in text.lower() or "update" in text.lower():
                missing_factors += 1

        # Check if we have learned preferences
        total_factors += 1
        if not context.get("has_preferences"):
            missing_factors += 0.5

        return missing_factors / total_factors if total_factors > 0 else 0

    def _check_scope_clarity(self, text: str) -> float:
        """Check if the scope of work is clear."""
        unclear_patterns = [
            r"\bmaybe\b",
            r"\bperhaps\b",
            r"\bpossibly\b",
            r"\bcould\b",
            r"\bmight\b",
            r"\bif needed\b",
            r"\bif necessary\b",
            r"\bwhen appropriate\b",
            r"\bas needed\b",
        ]

        text_lower = text.lower()
        matches = sum(1 for pattern in unclear_patterns if re.search(pattern, text_lower))

        return min(matches / 2, 1.0)

    def _generate_questions(self, text: str, factors: dict) -> list[str]:
        """Generate clarifying questions based on uncertainty factors."""
        questions = []
        text_lower = text.lower()

        # Question about ambiguous scope
        if factors["ambiguous_language"] > 0.5:
            if "simple" in text_lower:
                questions.append(
                    "When you say 'simple', do you mean: (a) minimal code, (b) easy to understand, or (c) both?"
                )
            elif "good" in text_lower or "better" in text_lower:
                questions.append(
                    "What's most important: performance, readability, or maintainability?"
                )
            elif "clean" in text_lower:
                questions.append(
                    "By 'clean', do you mean: (a) well-formatted, (b) well-structured, or (c) minimal dependencies?"
                )

        # Question about approach choices
        if factors["multiple_approaches"] > 0.5:
            if "api" in text_lower:
                questions.append(
                    "API style preference: REST (simple, widely used) or GraphQL (flexible queries)?"
                )
            elif "database" in text_lower:
                questions.append(
                    "Database preference: SQL (structured, relations) or NoSQL (flexible, scalable)?"
                )
            elif "test" in text_lower:
                questions.append(
                    "Testing approach: unit tests only, or also integration tests?"
                )

        # Question about missing context
        if factors["missing_context"] > 0.5:
            if "function" in text_lower or "code" in text_lower:
                questions.append(
                    "Which programming language should I use?"
                )
            if "file" in text_lower:
                questions.append(
                    "Which file should I modify, or should I create a new one?"
                )

        # Question about scope
        if factors["vague_scope"] > 0.5:
            questions.append(
                "Should I make minimal changes, or is a larger refactor acceptable?"
            )

        # Limit to 2 questions max
        return questions[:2]

    def generate_clarifying_questions(
        self,
        user_input: str,
        max_questions: int = 2,
    ) -> list[str]:
        """Generate clarifying questions for a user request.

        Args:
            user_input: The user's request
            max_questions: Maximum questions to return

        Returns:
            List of clarifying questions
        """
        assessment = self.assess_uncertainty(user_input)
        return assessment.suggested_questions[:max_questions]

    def record_clarification(self, question: str, answer: str, context: str = ""):
        """Record a Q&A pair for learning.

        Args:
            question: The clarifying question asked
            answer: The user's answer
            context: Original request context
        """
        record = {
            "question": question,
            "answer": answer,
            "context": context,
            "timestamp": datetime.now().isoformat(),
        }

        self._qa_history.append(record)

        # Keep only last 100
        if len(self._qa_history) > 100:
            self._qa_history = self._qa_history[-100:]

        self._save()

        # Extract and save any preferences from the answer
        self._learn_from_answer(question, answer)

    def _learn_from_answer(self, question: str, answer: str):
        """Extract preferences from user answers."""
        # This would ideally update the PreferenceLearner
        # For now, just store the pattern
        pass

    def get_common_clarifications(self) -> list[dict]:
        """Get commonly asked clarifications."""
        if not self._qa_history:
            return []

        # Group by question similarity
        question_groups = {}
        for qa in self._qa_history:
            q = qa["question"][:50]  # Group by first 50 chars
            if q not in question_groups:
                question_groups[q] = []
            question_groups[q].append(qa)

        # Sort by frequency
        common = sorted(
            question_groups.items(),
            key=lambda x: len(x[1]),
            reverse=True,
        )

        return [
            {
                "question_pattern": q,
                "count": len(answers),
                "sample_answers": [a["answer"] for a in answers[:3]],
            }
            for q, answers in common[:5]
        ]

    def clear_history(self):
        """Clear Q&A history."""
        self._qa_history = []
        self._save()


# Global instance
_active_learner: ActiveLearner | None = None


def get_active_learner() -> ActiveLearner:
    """Get or create the global active learner."""
    global _active_learner
    if _active_learner is None:
        _active_learner = ActiveLearner()
    return _active_learner


def assess_uncertainty(user_input: str, task_context: dict = None) -> UncertaintyAssessment:
    """Convenience function to assess uncertainty."""
    return get_active_learner().assess_uncertainty(user_input, task_context)


def generate_clarifying_questions(user_input: str, max_questions: int = 2) -> list[str]:
    """Convenience function to generate clarifying questions."""
    return get_active_learner().generate_clarifying_questions(user_input, max_questions)
