"""Persistent memory for RadSim Agent.

Stores user preferences, project context, and learned patterns
across sessions.
"""

import json
from datetime import datetime
from pathlib import Path

from .config import MEMORY_DIR


class Memory:
    """Persistent memory storage for the agent."""

    def __init__(self):
        """Initialize the memory system."""
        self.memory_dir = MEMORY_DIR
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        self.preferences_file = self.memory_dir / "preferences.json"
        self.context_file = self.memory_dir / "context.json"
        self.patterns_file = self.memory_dir / "patterns.json"

        # Load existing data
        self.preferences = self._load_file(self.preferences_file)
        self.context = self._load_file(self.context_file)
        self.patterns = self._load_file(self.patterns_file)

    def _load_file(self, path):
        """Load JSON data from a file."""
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                return {}
        return {}

    def _save_file(self, path, data):
        """Save JSON data to a file."""
        try:
            path.write_text(json.dumps(data, indent=2, default=str))
            return True
        except OSError:
            return False

    # ==========================================================================
    # Preferences API
    # ==========================================================================

    def get_preference(self, key, default=None):
        """Get a user preference.

        Args:
            key: The preference key
            default: Default value if not found

        Returns:
            The preference value or default
        """
        return self.preferences.get(key, default)

    def set_preference(self, key, value):
        """Set a user preference.

        Args:
            key: The preference key
            value: The value to store

        Returns:
            bool: True if saved successfully
        """
        self.preferences[key] = value
        self.preferences["_updated_at"] = datetime.now().isoformat()
        return self._save_file(self.preferences_file, self.preferences)

    def get_all_preferences(self):
        """Get all user preferences.

        Returns:
            dict: All preferences
        """
        return dict(self.preferences)

    # ==========================================================================
    # Context API (Project-specific memory)
    # ==========================================================================

    def get_context(self, project_name, key=None):
        """Get context for a project.

        Args:
            project_name: The project identifier
            key: Optional specific key within project context

        Returns:
            The context data
        """
        project_ctx = self.context.get(project_name, {})
        if key:
            return project_ctx.get(key)
        return project_ctx

    def set_context(self, project_name, key, value):
        """Set context for a project.

        Args:
            project_name: The project identifier
            key: The context key
            value: The value to store

        Returns:
            bool: True if saved successfully
        """
        if project_name not in self.context:
            self.context[project_name] = {}

        self.context[project_name][key] = value
        self.context[project_name]["_updated_at"] = datetime.now().isoformat()
        return self._save_file(self.context_file, self.context)

    def clear_context(self, project_name):
        """Clear all context for a project.

        Args:
            project_name: The project identifier

        Returns:
            bool: True if cleared successfully
        """
        if project_name in self.context:
            del self.context[project_name]
            return self._save_file(self.context_file, self.context)
        return True

    # ==========================================================================
    # Patterns API (Learned behaviors)
    # ==========================================================================

    def record_pattern(self, pattern_type, pattern_data):
        """Record a learned pattern.

        Args:
            pattern_type: Type of pattern (e.g., 'code_style', 'preferences')
            pattern_data: The pattern information

        Returns:
            bool: True if saved successfully
        """
        if pattern_type not in self.patterns:
            self.patterns[pattern_type] = []

        entry = {
            "data": pattern_data,
            "recorded_at": datetime.now().isoformat(),
        }
        self.patterns[pattern_type].append(entry)

        # Keep only last 100 entries per type
        self.patterns[pattern_type] = self.patterns[pattern_type][-100:]

        return self._save_file(self.patterns_file, self.patterns)

    def get_patterns(self, pattern_type):
        """Get all patterns of a type.

        Args:
            pattern_type: Type of pattern to retrieve

        Returns:
            list: Pattern entries
        """
        return self.patterns.get(pattern_type, [])


# =============================================================================
# Tool Functions
# =============================================================================


def save_memory(key, value, memory_type="preference"):
    """Save a value to persistent memory.

    Args:
        key: The key to store under
        value: The value to store
        memory_type: Type of memory ('preference', 'context', 'pattern')

    Returns:
        dict with success status
    """
    try:
        memory = Memory()

        if memory_type == "preference":
            success = memory.set_preference(key, value)
        elif memory_type == "context":
            # Use current directory as project name
            project = Path.cwd().name
            success = memory.set_context(project, key, value)
        elif memory_type == "pattern":
            success = memory.record_pattern(key, value)
        else:
            return {"success": False, "error": f"Unknown memory type: {memory_type}"}

        return {
            "success": success,
            "key": key,
            "memory_type": memory_type,
            "message": f"Saved to {memory_type} memory",
        }
    except Exception as error:
        return {"success": False, "error": str(error)}


def load_memory(key=None, memory_type="preference"):
    """Load a value from persistent memory.

    Args:
        key: The key to load (None for all)
        memory_type: Type of memory ('preference', 'context', 'pattern')

    Returns:
        dict with success status and data
    """
    try:
        memory = Memory()

        if memory_type == "preference":
            if key:
                data = memory.get_preference(key)
            else:
                data = memory.get_all_preferences()
        elif memory_type == "context":
            project = Path.cwd().name
            data = memory.get_context(project, key)
        elif memory_type == "pattern":
            data = memory.get_patterns(key) if key else {}
        else:
            return {"success": False, "error": f"Unknown memory type: {memory_type}"}

        return {"success": True, "key": key, "memory_type": memory_type, "data": data}
    except Exception as error:
        return {"success": False, "error": str(error)}


def clear_memory(key=None, memory_type="context"):
    """Clear memory.

    Args:
        key: Specific key to clear (or project name for context)
        memory_type: Type of memory to clear

    Returns:
        dict with success status
    """
    try:
        memory = Memory()

        if memory_type == "context":
            project = key or Path.cwd().name
            success = memory.clear_context(project)
        elif memory_type == "preference" and key:
            if key in memory.preferences:
                del memory.preferences[key]
                success = memory._save_file(memory.preferences_file, memory.preferences)
            else:
                success = True
        else:
            return {"success": False, "error": "Specify key for preference or project for context"}

        return {"success": success, "cleared": key or "project context", "memory_type": memory_type}
    except Exception as error:
        return {"success": False, "error": str(error)}
