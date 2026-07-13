"""Persistent memory for RadSim Agent.

Stores user preferences, project context, and learned patterns
across sessions using a 3-level hierarchy: Global, Project, and Session.
"""

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from .config import CONFIG_DIR

# Regex patterns for sanitization.
# Covers current key formats: OpenAI (sk-proj-...), Anthropic (sk-ant-...),
# OpenRouter (sk-or-v1-...), Google, GitHub, AWS, Slack, and Telegram bots.
SECRET_PATTERNS = [
    r"sk-[A-Za-z0-9_\-]{20,}",                    # OpenAI/Anthropic/OpenRouter keys
    r"AIza[0-9A-Za-z\-_]{35}",                    # Google API keys
    r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b",         # GitHub tokens (ghp_, gho_, ...)
    r"\bgithub_pat_[A-Za-z0-9_]{22,255}\b",       # GitHub fine-grained PATs
    r"\bAKIA[0-9A-Z]{16}\b",                      # AWS access key IDs
    r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b",         # Slack tokens
    r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b",           # Telegram bot tokens
    r"(?i)(password|secret|bearer|token)[\w\s]*=[\s]*[\"']?([a-zA-Z0-9\-_=]{16,})[\"']?", # Generic secrets
]

SESSION_TIMEOUT_MINUTES = 60


def sanitize_data(data):
    """Recursively strip sensitive information from data before saving."""
    if isinstance(data, dict):
        return {k: sanitize_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_data(v) for v in data]
    elif isinstance(data, str):
        sanitized = data
        for pattern in SECRET_PATTERNS:
            # Replaces the matching string with a redacted indicator
            sanitized = re.sub(pattern, "[REDACTED_SECRET]", sanitized)
        return sanitized
    return data


class BaseMemory:
    """Base class for memory managers."""

    def _load_json(self, path: Path):
        """Load JSON data from a file."""
        if path.exists():
            try:
                content = path.read_text()
                if content.strip():
                    return json.loads(content)
            except (OSError, json.JSONDecodeError):
                return {}
        return {}

    def _save_json(self, path: Path, data: dict):
        """Save JSON data to a file securely."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            sanitized = sanitize_data(data)
            path.write_text(json.dumps(sanitized, indent=2, default=str))
            return True
        except OSError:
            return False


class GlobalMemory(BaseMemory):
    """Level 1: Global Memory. Manages ~/.radsim/global_memory.json."""

    def __init__(self):
        self.file_path = CONFIG_DIR / "global_memory.json"
        self.data = self._load_json(self.file_path)

        # Initialize defaults if empty
        if not self.data:
            self.data = {
                "created_at": datetime.now().isoformat(),
                "preferences": {},
                "frameworks": {"commonly_used": []},
                "learned_patterns": [],
                "common_projects": []
            }

    def get_preference(self, key, default=None):
        return self.data.get("preferences", {}).get(key, default)

    def set_preference(self, key, value):
        if "preferences" not in self.data:
            self.data["preferences"] = {}
        self.data["preferences"][key] = value
        self.data["last_updated"] = datetime.now().isoformat()
        return self._save_json(self.file_path, self.data)

    def get_all_preferences(self):
        return dict(self.data.get("preferences", {}))

    def record_pattern(self, pattern, confidence="medium"):
        """Record a global learned behavior with confidence scoring."""
        if "learned_patterns" not in self.data:
            self.data["learned_patterns"] = []

        # Check if already exists, and if so, upgrade confidence
        for existing in self.data["learned_patterns"]:
            if isinstance(existing, dict) and existing.get("pattern") == pattern:
                existing["confidence"] = "high"
                existing["last_seen"] = datetime.now().isoformat()
                self.data["last_updated"] = datetime.now().isoformat()
                return self._save_json(self.file_path, self.data)
            elif isinstance(existing, str) and existing == pattern:
                # Upgrade string to dict
                idx = self.data["learned_patterns"].index(existing)
                self.data["learned_patterns"][idx] = {
                    "pattern": pattern,
                    "confidence": "high",
                    "last_seen": datetime.now().isoformat()
                }
                self.data["last_updated"] = datetime.now().isoformat()
                return self._save_json(self.file_path, self.data)

        # Append new
        self.data["learned_patterns"].append({
            "pattern": pattern,
            "confidence": confidence,
            "last_seen": datetime.now().isoformat()
        })

        # Keep only last 100 entries
        if len(self.data["learned_patterns"]) > 100:
            self.data["learned_patterns"] = self.data["learned_patterns"][-100:]

        self.data["last_updated"] = datetime.now().isoformat()
        return self._save_json(self.file_path, self.data)

    def add_project(self, project_path: str, project_name: str):
        """Track a common project."""
        if "common_projects" not in self.data:
            self.data["common_projects"] = []

        # Update if exists, else add
        for proj in self.data["common_projects"]:
            if proj.get("path") == project_path:
                proj["last_accessed"] = datetime.now().isoformat()
                self._save_json(self.file_path, self.data)
                return True

        self.data["common_projects"].append({
            "path": project_path,
            "name": project_name,
            "last_accessed": datetime.now().isoformat()
        })
        return self._save_json(self.file_path, self.data)


class ProjectMemory(BaseMemory):
    """Level 2: Project Memory. Manages [pwd]/.radsim/agents.md and .radsim/memory.json."""

    def __init__(self, project_dir: Path = None):
        if project_dir is None:
            project_dir = Path.cwd()

        self.project_dir = project_dir
        self.radsim_dir = self.project_dir / ".radsim"

        self.json_file = self.radsim_dir / "memory.json"
        self.agents_file = self.radsim_dir / "agents.md"
        self.gitignore_file = self.radsim_dir / ".gitignore"

        self.data = self._load_json(self.json_file)

        # Initialize defaults if empty
        if not self.data:
            self.data = {
                "project": {
                    "name": project_dir.name,
                    "initialized": datetime.now().isoformat(),
                    "last_session": datetime.now().isoformat(),
                    "session_count": 0
                },
                "decisions": [],
                "recent_files": [],
                "tags": []
            }

    def _save_json(self, path: Path, data: dict):
        """Save project memory, creating the .radsim scaffolding on first write.

        Creating .radsim/ lazily (on write, not on construction) prevents
        RadSim from scattering directories into every folder it merely
        reads from or is launched in.
        """
        self._ensure_gitignore()
        return super()._save_json(path, data)

    def _ensure_gitignore(self):
        """Keep the machine layer (memory.json) out of version control."""
        if self.gitignore_file.exists():
            return
        try:
            self.radsim_dir.mkdir(parents=True, exist_ok=True)
            self.gitignore_file.write_text("memory.json\n")
        except OSError:
            pass

    def ensure_initialized(self):
        """Explicitly create the project memory scaffolding.

        Called by user-initiated actions (e.g. /memory edit) — never as a
        hidden side effect of constructing a Memory object.
        """
        self._ensure_gitignore()

        # Create skeleton agents.md if not exists
        if not self.agents_file.exists():
            skeleton = f"""# RadSim Agents Memory: {self.project_dir.name}

## Project Overview
- Describe the project architecture here.

## Recent Context
- What are we currently working on?

## User Preferences
- Project-specific instructions go here.

## Key Decisions
- Document major architectural decisions here.

## Active Task
- Current focus.
"""
            try:
                self.agents_file.write_text(skeleton)
            except OSError:
                pass

    def get_context(self, key=None):
        if key:
            return self.data.get(key)
        return self.data

    def set_context(self, key, value):
        self.data[key] = value
        if "project" not in self.data:
            self.data["project"] = {}
        self.data["project"]["last_session"] = datetime.now().isoformat()
        return self._save_json(self.json_file, self.data)

    def record_decision(self, decision: str, rationale: str = "", confidence: str = "high"):
        if "decisions" not in self.data:
            self.data["decisions"] = []

        self.data["decisions"].append({
            "date": datetime.now().isoformat(),
            "decision": decision,
            "rationale": rationale,
            "confidence": confidence
        })
        return self._save_json(self.json_file, self.data)

    def update_recent_file(self, file_path: str, intent: str = "accessed"):
        if "recent_files" not in self.data:
            self.data["recent_files"] = []

        # Find and update, or add
        for entry in self.data["recent_files"]:
            if entry.get("path") == file_path:
                entry["last_accessed"] = datetime.now().isoformat()
                entry["access_count"] = entry.get("access_count", 0) + 1
                entry["last_intent"] = intent
                intents = entry.setdefault("intents", {})
                intents[intent] = intents.get(intent, 0) + 1
                return self._save_json(self.json_file, self.data)

        self.data["recent_files"].append({
            "path": file_path,
            "last_accessed": datetime.now().isoformat(),
            "access_count": 1,
            "last_intent": intent,
            "intents": {intent: 1},
        })

        # Keep manageable size
        if len(self.data["recent_files"]) > 50:
            self.data["recent_files"] = sorted(
                self.data["recent_files"],
                key=lambda x: x.get("last_accessed", ""),
                reverse=True
            )[:50]

        return self._save_json(self.json_file, self.data)

    def read_agents_md(self) -> str:
        """Read project context: top-level RADSIM.md plus .radsim/agents.md.

        RADSIM.md is the user-authored project brief (like a README for
        the agent); agents.md is RadSim's own project memory. Both are
        untrusted input and size-capped by the prompt builder.
        """
        parts = []
        for candidate in (self.project_dir / "RADSIM.md", self.agents_file):
            if not candidate.exists():
                continue
            try:
                parts.append(candidate.read_text())
            except OSError:
                continue
        return "\n\n".join(parts)


class SessionMemory(BaseMemory):
    """Level 3: Session Memory. Manages ephemeral/short-term state automatically."""

    def __init__(self, session_id: str = None):
        if not session_id:
            # E.g., named by project dir + "session"
            # Include a hash of the full path so two projects with the
            # same folder name (e.g. ~/work/api and ~/personal/api)
            # never share session state.
            cwd = Path.cwd()
            path_hash = hashlib.sha256(str(cwd).encode()).hexdigest()[:8]
            session_id = f"{cwd.name}_{path_hash}"

        self.session_id = session_id
        self.cache_dir = CONFIG_DIR / "cache" / "session_snapshots"
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        self.file_path = self.cache_dir / f"{session_id}.json"

        self.data = self._load_json(self.file_path)
        if not self.data:
             self.data = {
                 "started_at": datetime.now().isoformat(),
                 "last_active": datetime.now().isoformat(),
                 "active_task": "",
                 "conversation_summary": ""
             }

    def update_activity(self):
        """Update last active timestamp."""
        self.data["last_active"] = datetime.now().isoformat()
        self._save_json(self.file_path, self.data)

    def set_active_task(self, task_description: str):
        self.data["active_task"] = task_description
        self.update_activity()

    def is_expired(self, timeout_minutes=SESSION_TIMEOUT_MINUTES):
        """Check if the session has expired beyond the grace period."""
        if "last_active" not in self.data:
            return True
        try:
            last_active = datetime.fromisoformat(self.data["last_active"])
            return datetime.now() - last_active > timedelta(minutes=timeout_minutes)
        except ValueError:
            return True


# =============================================================================
# Facade for backward compatibility and uniform access
# =============================================================================
class Memory:
    """Facade managing Global, Project, and Session memories.
    Maintains api compatibility with legacy single-tier Memory class."""

    def __init__(self):
        self.global_mem = GlobalMemory()
        self.project_mem = ProjectMemory()
        self.session_mem = SessionMemory()

    # Legacy property support for components accessing dictionary directly
    @property
    def preferences(self):
        return self.global_mem.data.setdefault("preferences", {})

    @property
    def context(self):
        # Emulate the dict of project names
        return {self.project_mem.project_dir.name: self.project_mem.data}

    @property
    def patterns(self):
        # We consolidate around 'learned' pattern type
        return {"learned": self.global_mem.data.get("learned_patterns", [])}

    # --- Backward compatible methods ---
    def get_preference(self, key, default=None):
        return self.global_mem.get_preference(key, default)

    def set_preference(self, key, value):
        return self.global_mem.set_preference(key, value)

    def get_all_preferences(self):
        return self.global_mem.get_all_preferences()

    def get_context(self, project_name, key=None):
        # project_name is ignored; it uses current path
        return self.project_mem.get_context(key)

    def set_context(self, project_name, key, value):
        # project_name is ignored; it uses current path
        return self.project_mem.set_context(key, value)

    def clear_context(self, project_name):
        self.project_mem.data = {
           "project": {
               "name": project_name,
               "initialized": datetime.now().isoformat(),
               "last_session": datetime.now().isoformat(),
               "session_count": 0
           },
           "decisions": [],
           "recent_files": [],
           "tags": []
        }
        return self.project_mem._save_json(self.project_mem.json_file, self.project_mem.data)

    def record_pattern(self, pattern_type, pattern_data, confidence="medium"):
        if pattern_type == "code_style" or pattern_type == "preferences":
            return self.global_mem.record_pattern(f"[{pattern_type}] {pattern_data}", confidence)
        return self.global_mem.record_pattern(pattern_data, confidence)

    def get_patterns(self, pattern_type):
        return self.global_mem.data.get("learned_patterns", [])


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
        from .runtime_context import get_runtime_context

        memory = get_runtime_context().get_memory()

        if memory_type == "preference":
            success = memory.set_preference(key, value)
        elif memory_type == "context":
            success = memory.set_context("deprecated", key, value)
        elif memory_type == "pattern":
            success = memory.record_pattern("learned", value)
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
        from .runtime_context import get_runtime_context

        memory = get_runtime_context().get_memory()

        if memory_type == "preference":
            if key:
                data = memory.get_preference(key)
            else:
                data = memory.get_all_preferences()
        elif memory_type == "context":
            data = memory.get_context("deprecated", key)
        elif memory_type == "pattern":
            data = memory.get_patterns(key) if key else memory.get_patterns("all")
        else:
            return {"success": False, "error": f"Unknown memory type: {memory_type}"}

        return {"success": True, "key": key, "memory_type": memory_type, "data": data}
    except Exception as error:
        return {"success": False, "error": str(error)}


def forget_memory(key, memory_type="preference"):
    """Remove a value from persistent memory.

    Args:
        key: The key or pattern text to remove
        memory_type: Type of memory ('preference', 'context', 'pattern')

    Returns:
        dict with success status
    """
    if not key:
        return {"success": False, "error": "Key is required"}

    try:
        from .runtime_context import get_runtime_context

        memory = get_runtime_context().get_memory()

        if memory_type == "preference":
            data = memory.global_mem.data.setdefault("preferences", {})
            saved = _delete_key_and_save(data, key, memory.global_mem.file_path, memory.global_mem)
        elif memory_type == "context":
            saved = _delete_key_and_save(memory.project_mem.data, key, memory.project_mem.json_file, memory.project_mem)
        elif memory_type == "pattern":
            saved = _delete_pattern(memory.global_mem, key)
        else:
            return {"success": False, "error": f"Unknown memory type: {memory_type}"}

        if not saved:
            return {"success": False, "error": f"Memory not found: {key}"}

        return {
            "success": True,
            "key": key,
            "memory_type": memory_type,
            "message": f"Forgot {memory_type} memory",
        }
    except Exception as error:
        return {"success": False, "error": str(error)}


def _delete_key_and_save(data, key, file_path, memory_store):
    """Delete a key from a dictionary-backed memory file."""
    if key not in data:
        return False
    del data[key]
    return memory_store._save_json(file_path, memory_store.data)


def _delete_pattern(global_memory, key):
    """Delete matching learned patterns from global memory."""
    patterns = global_memory.data.get("learned_patterns", [])
    remaining = []
    removed = False

    for pattern in patterns:
        pattern_text = pattern.get("pattern") if isinstance(pattern, dict) else pattern
        if pattern_text == key:
            removed = True
            continue
        remaining.append(pattern)

    if not removed:
        return False

    global_memory.data["learned_patterns"] = remaining
    global_memory.data["last_updated"] = datetime.now().isoformat()
    return global_memory._save_json(global_memory.file_path, global_memory.data)

