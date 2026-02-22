"""Comprehensive Task Logging - Observable by Default.

RadSim Principle: Observable by Default
Every action should be traceable. Log what happened, not just do it.

Features:
- Structured JSON logging for all LLM request/response cycles
- Tool execution tracking (input vs output)
- Timestamped audit trail for review
- SQLite storage for queryable history
"""

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

# Default log directory
LOG_DIR = Path.home() / ".radsim" / "logs"

# Patterns that should never appear in logs (case-insensitive)
SENSITIVE_PATTERNS = [
    "access_code",
    "api_key",
    "password",
    "secret",
    "token",
    "credential",
    "private_key",
]


def _sanitize_for_logging(data: str) -> str:
    """Remove sensitive values from log data.

    RadSim Principle: Security by Default
    Never log secrets, even accidentally.
    """
    if not data:
        return data

    sanitized = data
    for pattern in SENSITIVE_PATTERNS:
        # Match pattern followed by separator and value
        sanitized = re.sub(
            rf'({pattern}["\'\s:=]+)[^\s",}}\]\n]+', r"\1[REDACTED]", sanitized, flags=re.IGNORECASE
        )
    return sanitized


@dataclass
class LogEntry:
    """A single log entry for the audit trail."""

    timestamp: str
    event_type: str  # api_call, tool_execution, error, user_input, agent_response
    session_id: str

    # Event-specific data
    tool_name: str = ""
    tool_input: str = ""  # JSON string
    tool_output: str = ""  # JSON string

    api_model: str = ""
    api_provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    api_duration_ms: float = 0.0

    message_role: str = ""  # user, assistant
    message_content: str = ""

    error_type: str = ""
    error_message: str = ""

    metadata: str = ""  # JSON string for extra data


class TaskLogger:
    """Structured logging system for RadSim.

    Logs all agent activities to:
    1. JSON files (human-readable, one per session)
    2. SQLite database (queryable history)
    """

    def __init__(self, session_id: str = None, log_dir: Path = None):
        self.log_dir = log_dir or LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.session_id = session_id or self._generate_session_id()
        self.db_path = self.log_dir / "radsim_logs.db"
        self.json_path = self.log_dir / f"session_{self.session_id}.json"

        self._init_db()
        self._entries: list[LogEntry] = []

    def _generate_session_id(self) -> str:
        """Generate a unique session ID."""
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _init_db(self):
        """Initialize SQLite database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                session_id TEXT NOT NULL,
                tool_name TEXT,
                tool_input TEXT,
                tool_output TEXT,
                api_model TEXT,
                api_provider TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                api_duration_ms REAL,
                message_role TEXT,
                message_content TEXT,
                error_type TEXT,
                error_message TEXT,
                metadata TEXT
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_session
            ON logs(session_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_event_type
            ON logs(event_type)
        """)

        conn.commit()
        conn.close()

    def _now(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.now().isoformat()

    def _save_entry(self, entry: LogEntry):
        """Save entry to both JSON and SQLite."""
        self._entries.append(entry)

        # Save to JSON file
        with open(self.json_path, "w") as f:
            json.dump([asdict(e) for e in self._entries], f, indent=2)

        # Save to SQLite
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO logs (
                timestamp, event_type, session_id,
                tool_name, tool_input, tool_output,
                api_model, api_provider, input_tokens, output_tokens, api_duration_ms,
                message_role, message_content,
                error_type, error_message, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                entry.timestamp,
                entry.event_type,
                entry.session_id,
                entry.tool_name,
                entry.tool_input,
                entry.tool_output,
                entry.api_model,
                entry.api_provider,
                entry.input_tokens,
                entry.output_tokens,
                entry.api_duration_ms,
                entry.message_role,
                entry.message_content,
                entry.error_type,
                entry.error_message,
                entry.metadata,
            ),
        )

        conn.commit()
        conn.close()

    # Logging methods

    def log_tool_execution(
        self, tool_name: str, tool_input: dict, tool_output: dict, duration_ms: float = 0.0
    ):
        """Log a tool execution."""
        entry = LogEntry(
            timestamp=self._now(),
            event_type="tool_execution",
            session_id=self.session_id,
            tool_name=tool_name,
            tool_input=json.dumps(tool_input),
            tool_output=json.dumps(tool_output),
            api_duration_ms=duration_ms,
        )
        self._save_entry(entry)

    def log_api_call(
        self, model: str, provider: str, input_tokens: int, output_tokens: int, duration_ms: float
    ):
        """Log an API call."""
        entry = LogEntry(
            timestamp=self._now(),
            event_type="api_call",
            session_id=self.session_id,
            api_model=model,
            api_provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            api_duration_ms=duration_ms,
        )
        self._save_entry(entry)

    def log_message(self, role: str, content: str):
        """Log a conversation message."""
        entry = LogEntry(
            timestamp=self._now(),
            event_type="message",
            session_id=self.session_id,
            message_role=role,
            message_content=content[:10000],  # Truncate long messages
        )
        self._save_entry(entry)

    def log_error(self, error_type: str, error_message: str, metadata: dict = None):
        """Log an error."""
        entry = LogEntry(
            timestamp=self._now(),
            event_type="error",
            session_id=self.session_id,
            error_type=error_type,
            error_message=error_message,
            metadata=json.dumps(metadata or {}),
        )
        self._save_entry(entry)

    # Query methods

    def get_session_logs(self) -> list[LogEntry]:
        """Get all logs for current session."""
        return self._entries

    def get_tool_stats(self) -> dict:
        """Get statistics on tool usage."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT tool_name, COUNT(*) as count,
                   AVG(api_duration_ms) as avg_duration
            FROM logs
            WHERE event_type = 'tool_execution'
            AND session_id = ?
            GROUP BY tool_name
        """,
            (self.session_id,),
        )

        stats = {}
        for row in cursor.fetchall():
            stats[row[0]] = {"count": row[1], "avg_duration_ms": row[2]}

        conn.close()
        return stats

    def get_token_usage(self) -> dict:
        """Get total token usage for session."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT SUM(input_tokens), SUM(output_tokens)
            FROM logs
            WHERE event_type = 'api_call'
            AND session_id = ?
        """,
            (self.session_id,),
        )

        row = cursor.fetchone()
        conn.close()

        return {
            "input_tokens": row[0] or 0,
            "output_tokens": row[1] or 0,
            "total_tokens": (row[0] or 0) + (row[1] or 0),
        }


# Global logger instance
_logger: TaskLogger | None = None


def get_logger(session_id: str = None) -> TaskLogger:
    """Get or create the global logger instance."""
    global _logger
    if _logger is None or (session_id and _logger.session_id != session_id):
        _logger = TaskLogger(session_id)
    return _logger


def log_tool(tool_name: str, tool_input: dict, tool_output: dict, duration_ms: float = 0.0):
    """Convenience function to log tool execution."""
    get_logger().log_tool_execution(tool_name, tool_input, tool_output, duration_ms)


def log_api(model: str, provider: str, input_tokens: int, output_tokens: int, duration_ms: float):
    """Convenience function to log API call."""
    get_logger().log_api_call(model, provider, input_tokens, output_tokens, duration_ms)


def log_error(error_type: str, error_message: str, metadata: dict = None):
    """Convenience function to log error."""
    get_logger().log_error(error_type, error_message, metadata)
