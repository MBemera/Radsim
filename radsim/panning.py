# RadSim - AI Coding Agent
# Copyright (c) 2024-2026 Matthew Bright
# Licensed under the MIT License. See LICENSE file for details.

"""Panning session for brain-dump processing.

Brain-dump → structured synthesis. Named after gold panning:
sifting raw material to find nuggets.
"""

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

PANNING_DIR = Path.home() / ".radsim" / "panning_sessions"


class PanningSynthesis:
    """Structured output from a panning session."""

    def __init__(
        self,
        themes: list[dict] | None = None,
        action_items: list[dict] | None = None,
        priorities: list[dict] | None = None,
        connections: list[dict] | None = None,
        open_questions: list[str] | None = None,
    ):
        self.themes = themes or []
        self.action_items = action_items or []
        self.priorities = priorities or []
        self.connections = connections or []
        self.open_questions = open_questions or []

    def to_dict(self) -> dict:
        return {
            "themes": self.themes,
            "action_items": self.action_items,
            "priorities": self.priorities,
            "connections": self.connections,
            "open_questions": self.open_questions,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PanningSynthesis":
        return cls(
            themes=data.get("themes", []),
            action_items=data.get("action_items", []),
            priorities=data.get("priorities", []),
            connections=data.get("connections", []),
            open_questions=data.get("open_questions", []),
        )

    def format_display(self) -> str:
        """Format synthesis for terminal display."""
        lines = []
        width = 55

        lines.append("")
        lines.append(f"  ┌{'─' * width}┐")
        lines.append(f"  │{'PANNING SYNTHESIS':^{width}}│")
        lines.append(f"  ├{'─' * width}┤")

        # Themes
        if self.themes:
            lines.append(f"  │{' THEMES:':>{8}}{' ' * (width - 8)}│")
            for i, theme in enumerate(self.themes, 1):
                title = theme.get("title", "")[:width - 8]
                lines.append(f"  │  {i}. {title:<{width - 6}}│")
                desc = theme.get("description", "")[:width - 11]
                if desc:
                    lines.append(f"  │     {desc:<{width - 6}}│")
            lines.append(f"  │{' ' * width}│")

        # Action Items
        if self.action_items:
            lines.append(f"  │{' ACTION ITEMS:':>{14}}{' ' * (width - 14)}│")
            for item in self.action_items:
                task = item.get("task", "")[:width - 12]
                priority = item.get("priority", "medium")
                icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(priority, "⚪")
                lines.append(f"  │  {icon} [ ] {task:<{width - 12}}│")
            lines.append(f"  │{' ' * width}│")

        # Priorities
        if self.priorities:
            lines.append(f"  │{' PRIORITIES (by signal strength):':>{34}}{' ' * (width - 34)}│")
            for p in sorted(self.priorities, key=lambda x: x.get("rank", 99)):
                item_text = p.get("item", "")[:width - 8]
                signal = p.get("signal", "")[:width - 11]
                lines.append(f"  │  {p.get('rank', '?')}. {item_text:<{width - 7}}│")
                if signal:
                    lines.append(f"  │     ({signal}){' ' * max(0, width - len(signal) - 8)}│")
            lines.append(f"  │{' ' * width}│")

        # Connections
        if self.connections:
            lines.append(f"  │{' CONNECTIONS:':>{13}}{' ' * (width - 13)}│")
            for conn in self.connections:
                items = " + ".join(conn.get("items", []))[:width - 8]
                insight = conn.get("insight", "")[:width - 10]
                lines.append(f"  │  • {items:<{width - 6}}│")
                if insight:
                    lines.append(f"  │    {insight:<{width - 5}}│")
            lines.append(f"  │{' ' * width}│")

        # Open Questions
        if self.open_questions:
            lines.append(f"  │{' OPEN QUESTIONS:':>{16}}{' ' * (width - 16)}│")
            for q in self.open_questions:
                q_text = q[:width - 8] if isinstance(q, str) else str(q)[:width - 8]
                lines.append(f"  │  • {q_text:<{width - 6}}│")

        lines.append(f"  └{'─' * width}┘")
        lines.append("")
        lines.append("  Continue dumping? [y] | Refine? [r] | Bridge to /plan? [p]")
        lines.append("")

        return "\n".join(lines)

    def to_plan_description(self) -> str:
        """Convert synthesis into a description suitable for /plan."""
        parts = []

        if self.themes:
            theme_names = [t.get("title", "") for t in self.themes]
            parts.append(f"Themes: {', '.join(theme_names)}")

        if self.action_items:
            high_priority = [
                a.get("task", "") for a in self.action_items
                if a.get("priority") == "high"
            ]
            if high_priority:
                parts.append(f"High-priority tasks: {'; '.join(high_priority)}")

        if self.priorities:
            top = self.priorities[0] if self.priorities else None
            if top:
                parts.append(f"Top priority: {top.get('item', '')}")

        return ". ".join(parts)


class PanningSession:
    """Manages a brain-dump panning session."""

    def __init__(self):
        self.session_id = f"panning_{int(time.time())}"
        self.dumps: list[str] = []
        self.syntheses: list[PanningSynthesis] = []
        self.active = False
        self.created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        PANNING_DIR.mkdir(parents=True, exist_ok=True)

    def start(self):
        """Start an interactive panning session."""
        self.active = True
        return (
            "\n  🍳 Panning session started!\n"
            "  Dump your thoughts freely — rambling encouraged.\n"
            "  Type '/panning end' when done to generate synthesis.\n"
        )

    def add_dump(self, text: str):
        """Add raw text to the session."""
        self.dumps.append(text)
        self._save()

    def process_file(self, path: str) -> str:
        """Read and add a file's contents to the session."""
        try:
            file_path = Path(path).expanduser()
            if not file_path.exists():
                return f"  ⚠ File not found: {path}"

            content = file_path.read_text(encoding="utf-8")
            self.dumps.append(content)
            self._save()
            return f"  ✓ Added {len(content)} characters from {file_path.name}"
        except Exception as e:
            return f"  ⚠ Error reading file: {e}"

    def get_all_dumps(self) -> str:
        """Get all dumps concatenated for synthesis."""
        return "\n\n---\n\n".join(self.dumps)

    def parse_synthesis(self, response_text: str) -> PanningSynthesis | None:
        """Parse an LLM response into a PanningSynthesis."""
        import re

        # Try to extract JSON from response
        json_patterns = [
            r"```json\s*\n(.*?)\n\s*```",
            r"```\s*\n(.*?)\n\s*```",
            r"\{[\s\S]*\}",
        ]

        for pattern in json_patterns:
            matches = re.findall(pattern, response_text, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
                    synthesis = PanningSynthesis.from_dict(data)
                    self.syntheses.append(synthesis)
                    self._save()
                    return synthesis
                except json.JSONDecodeError:
                    continue

        return None

    def get_latest_synthesis(self) -> PanningSynthesis | None:
        """Get the most recent synthesis."""
        return self.syntheses[-1] if self.syntheses else None

    def end(self):
        """End the panning session."""
        self.active = False
        self._save()

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "dumps": self.dumps,
            "syntheses": [s.to_dict() for s in self.syntheses],
            "active": self.active,
            "created_at": self.created_at,
        }

    def _save(self):
        """Save session to file."""
        try:
            session_file = PANNING_DIR / f"{self.session_id}.json"
            session_file.write_text(json.dumps(self.to_dict(), indent=2))
        except Exception as e:
            logger.debug(f"Failed to save panning session: {e}")


# Singleton instance
_panning_session: PanningSession | None = None


def get_panning_session() -> PanningSession:
    """Get or create the global PanningSession."""
    global _panning_session
    if _panning_session is None:
        _panning_session = PanningSession()
    return _panning_session


def start_new_session() -> PanningSession:
    """Start a fresh panning session."""
    global _panning_session
    _panning_session = PanningSession()
    return _panning_session
