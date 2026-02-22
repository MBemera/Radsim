"""Few-Shot Learning from Conversation History.

Automatically include relevant past examples in prompts to leverage
the LLM's in-context learning capabilities.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class TaskExample:
    """A past task example for few-shot learning."""

    task_description: str
    approach_taken: str
    outcome: str
    success: bool
    timestamp: str = ""
    tools_used: list = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
        if self.tools_used is None:
            self.tools_used = []


class FewShotAssembler:
    """Assemble few-shot examples from conversation history.

    Retrieves semantically similar past examples and formats them
    for inclusion in the system prompt.
    """

    def __init__(self, storage_dir: Path = None):
        self.storage_dir = storage_dir or Path.home() / ".radsim" / "learning"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.examples_file = self.storage_dir / "task_examples.json"

        self._examples: list[dict] = []
        self._load()

    def _load(self):
        """Load examples from disk."""
        if self.examples_file.exists():
            try:
                self._examples = json.loads(self.examples_file.read_text())
            except (OSError, json.JSONDecodeError):
                self._examples = []

    def _save(self):
        """Persist examples to disk."""
        self.examples_file.write_text(json.dumps(self._examples, indent=2))

    def record_task_completion(
        self,
        task_description: str,
        approach: str,
        outcome: str,
        success: bool,
        tools_used: list = None,
    ):
        """Record a completed task as a potential example.

        Args:
            task_description: What the user asked for
            approach: How it was solved
            outcome: What happened
            success: Whether it worked
            tools_used: Tools that were used
        """
        example = {
            "task_description": task_description[:500],
            "approach": approach[:1000],
            "outcome": outcome[:500],
            "success": success,
            "tools_used": tools_used or [],
            "timestamp": datetime.now().isoformat(),
            "keywords": self._extract_keywords(task_description),
        }

        self._examples.append(example)

        # Keep only last 100 examples
        if len(self._examples) > 100:
            self._examples = self._examples[-100:]

        self._save()

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract keywords from task description."""
        # Common programming terms to match
        keywords = []

        # Language keywords
        languages = ["python", "javascript", "typescript", "go", "rust", "java", "sql"]
        for lang in languages:
            if lang in text.lower():
                keywords.append(lang)

        # Framework keywords
        frameworks = [
            "flask", "django", "fastapi", "react", "vue", "express", "rails",
            "pytest", "jest", "docker", "kubernetes", "aws", "terraform"
        ]
        for fw in frameworks:
            if fw in text.lower():
                keywords.append(fw)

        # Task type keywords
        task_types = [
            "fix", "bug", "test", "refactor", "create", "add", "remove",
            "update", "api", "endpoint", "function", "class", "database"
        ]
        for tt in task_types:
            if tt in text.lower():
                keywords.append(tt)

        return list(set(keywords))

    def get_examples_for_task(self, task_description: str, top_k: int = 3) -> list[dict]:
        """Retrieve similar past examples for few-shot learning.

        Args:
            task_description: The current task
            top_k: Number of examples to return

        Returns:
            List of similar past examples
        """
        if not self._examples:
            return []

        task_keywords = set(self._extract_keywords(task_description))
        task_words = set(task_description.lower().split())

        scored_examples = []
        for example in self._examples:
            # Prefer successful examples
            if not example.get("success", False):
                continue

            # Calculate similarity score
            example_keywords = set(example.get("keywords", []))
            example_words = set(example["task_description"].lower().split())

            keyword_overlap = len(task_keywords & example_keywords)
            word_overlap = len(task_words & example_words) / max(len(task_words), 1)

            score = keyword_overlap * 2 + word_overlap

            if score > 0:
                scored_examples.append((score, example))

        # Sort by score descending
        scored_examples.sort(key=lambda x: x[0], reverse=True)

        return [ex for _, ex in scored_examples[:top_k]]

    def format_examples_for_prompt(self, examples: list[dict]) -> str:
        """Format examples as few-shot learning context.

        Args:
            examples: List of task examples

        Returns:
            Formatted string for inclusion in prompt
        """
        if not examples:
            return ""

        formatted = "\n\n## Similar Past Tasks (Learn from these):\n"

        for i, example in enumerate(examples, 1):
            success_icon = "✓" if example.get("success") else "✗"
            tools = ", ".join(example.get("tools_used", [])) or "various"

            formatted += f"""
### Example {i}: {example['task_description'][:100]}
- **Approach:** {example['approach'][:200]}
- **Tools used:** {tools}
- **Result:** {success_icon} {example['outcome'][:100]}
"""

        formatted += "\nUse these examples to inform your approach.\n"

        return formatted

    def inject_examples_into_prompt(
        self,
        base_prompt: str,
        task_description: str,
        max_examples: int = 2,
    ) -> str:
        """Enhance system prompt with few-shot examples.

        Args:
            base_prompt: The original system prompt
            task_description: Current task to find examples for
            max_examples: Maximum number of examples to include

        Returns:
            Enhanced prompt with examples
        """
        examples = self.get_examples_for_task(task_description, top_k=max_examples)

        if not examples:
            return base_prompt

        few_shot_context = self.format_examples_for_prompt(examples)

        # Find a good insertion point (before capabilities section if it exists)
        insertion_markers = [
            "## Your Capabilities",
            "## Available Tools",
            "## Tools",
        ]

        for marker in insertion_markers:
            if marker in base_prompt:
                insertion_point = base_prompt.find(marker)
                enhanced = (
                    base_prompt[:insertion_point]
                    + few_shot_context
                    + base_prompt[insertion_point:]
                )
                return enhanced

        # Otherwise append at the end
        return base_prompt + few_shot_context

    def get_examples_stats(self) -> dict:
        """Get statistics about stored examples."""
        if not self._examples:
            return {"total": 0, "successful": 0, "keywords": []}

        successful = sum(1 for ex in self._examples if ex.get("success"))

        # Collect all keywords
        all_keywords = []
        for ex in self._examples:
            all_keywords.extend(ex.get("keywords", []))

        # Count keyword frequency
        keyword_counts = {}
        for kw in all_keywords:
            keyword_counts[kw] = keyword_counts.get(kw, 0) + 1

        top_keywords = sorted(
            keyword_counts.items(), key=lambda x: x[1], reverse=True
        )[:10]

        return {
            "total": len(self._examples),
            "successful": successful,
            "success_rate": successful / len(self._examples) if self._examples else 0,
            "top_keywords": top_keywords,
        }

    def clear_examples(self):
        """Clear all stored examples."""
        self._examples = []
        self._save()


# Global instance
_few_shot_assembler: FewShotAssembler | None = None


def get_few_shot_assembler() -> FewShotAssembler:
    """Get or create the global few-shot assembler."""
    global _few_shot_assembler
    if _few_shot_assembler is None:
        _few_shot_assembler = FewShotAssembler()
    return _few_shot_assembler


def get_examples_for_task(task_description: str, top_k: int = 3) -> list[dict]:
    """Convenience function to get examples for a task."""
    return get_few_shot_assembler().get_examples_for_task(task_description, top_k)


def inject_examples_into_prompt(
    base_prompt: str,
    task_description: str,
    max_examples: int = 2,
) -> str:
    """Convenience function to inject examples into prompt."""
    return get_few_shot_assembler().inject_examples_into_prompt(
        base_prompt, task_description, max_examples
    )
