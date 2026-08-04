"""Undo checkpoints: snapshot files before the agent changes them.

Before a file-mutating tool runs, the affected files are copied into a
per-project stack under ~/.radsim/undo/. /undo restores the most recent
checkpoint (recreating, rewriting, or deleting files to match the state
before the tool ran). Checkpointing is a convenience, not a security
control: a snapshot failure warns and lets the tool proceed.

Bounded by design: 20 checkpoints per project, 5 MB per file; larger
files are recorded but not snapshotted (undo will say so).
"""

import hashlib
import json
import logging
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

UNDO_ROOT = Path.home() / ".radsim" / "undo"
MAX_CHECKPOINTS = 20
MAX_SNAPSHOT_BYTES = 5 * 1024 * 1024

# Tool name -> tool_input keys holding paths this tool may change.
CHECKPOINT_TOOLS = {
    "write_file": ("file_path",),
    "replace_in_file": ("file_path",),
    "delete_file": ("file_path",),
    "multi_edit": ("file_path",),
    "apply_patch": ("file_path",),
    "rename_file": ("old_path", "new_path"),
}


def _project_dir():
    """One undo stack per project so histories never mix."""
    cwd = Path.cwd()
    digest = hashlib.sha256(str(cwd).encode()).hexdigest()[:12]
    return UNDO_ROOT / f"{cwd.name}_{digest}"


def _index_file():
    return _project_dir() / "index.json"


def _load_index():
    index_file = _index_file()
    if not index_file.exists():
        return []
    try:
        entries = json.loads(index_file.read_text())
        return entries if isinstance(entries, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_index(entries):
    project_dir = _project_dir()
    project_dir.mkdir(parents=True, exist_ok=True)
    _index_file().write_text(json.dumps(entries, indent=2) + "\n")


def _snapshot_one_file(path):
    """Record one file's pre-change state.

    Returns:
        Dict describing the file: existed, snapshot filename (when the
        content was saved), and skipped_reason for oversized files.
    """
    record = {"path": str(path)}
    if not path.exists():
        record["existed"] = False
        return record

    record["existed"] = True
    if not path.is_file():
        record["skipped_reason"] = "target is not a regular file"
        return record
    size = path.stat().st_size
    if size > MAX_SNAPSHOT_BYTES:
        record["skipped_reason"] = f"file is {size} bytes (over the snapshot limit)"
        return record

    snapshot_name = uuid.uuid4().hex
    snapshot_path = _project_dir() / snapshot_name
    snapshot_path.write_bytes(path.read_bytes())
    record["snapshot"] = snapshot_name
    return record


def prepare_checkpoint(tool_name, tool_input):
    """Snapshot the files a mutating tool is about to touch.

    The snapshot is only recorded in the undo stack when the caller
    commits it after the tool succeeds — a rejected or failed tool call
    must not leave a phantom checkpoint. Never raises: undo must not be
    able to break the tool it protects.

    Returns:
        A pending entry to pass to commit_checkpoint/discard_checkpoint,
        or None when this tool needs no checkpoint.
    """
    path_keys = CHECKPOINT_TOOLS.get(tool_name)
    if not path_keys:
        try:
            from .tools import get_extension_tool_metadata

            metadata = get_extension_tool_metadata(tool_name)
            if metadata and metadata.get("permission_tier") != "read_only":
                path_keys = metadata.get("path_keys", ())
        except Exception:
            path_keys = None
    if not path_keys or not isinstance(tool_input, dict):
        return None

    try:
        _project_dir().mkdir(parents=True, exist_ok=True)
        files = []
        for key in path_keys:
            raw_path = tool_input.get(key, "")
            if raw_path:
                files.append(_snapshot_one_file(Path(str(raw_path)).resolve()))
        if not files:
            return None
        return {
            "id": uuid.uuid4().hex[:8],
            "tool": tool_name,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": files,
        }
    except Exception as error:
        logger.warning("Undo checkpoint failed for %s: %s", tool_name, error)
        return None


def commit_checkpoint(entry):
    """Record a prepared checkpoint after its tool succeeded."""
    try:
        entries = _load_index()
        entries.append(entry)
        _trim_old_entries(entries)
        _save_index(entries)
    except Exception as error:
        logger.warning("Undo commit failed: %s", error)


def discard_checkpoint(entry):
    """Drop a prepared checkpoint whose tool was rejected or failed."""
    for record in entry.get("files", []):
        _delete_snapshot(record)


def _trim_old_entries(entries):
    """Drop the oldest checkpoints and their snapshot files."""
    while len(entries) > MAX_CHECKPOINTS:
        expired = entries.pop(0)
        for record in expired.get("files", []):
            _delete_snapshot(record)


def _delete_snapshot(record):
    snapshot_name = record.get("snapshot")
    if not snapshot_name:
        return
    try:
        (_project_dir() / snapshot_name).unlink(missing_ok=True)
    except OSError:
        pass


def list_checkpoints():
    """Return checkpoint summaries, newest last."""
    summaries = []
    for entry in _load_index():
        paths = ", ".join(Path(record["path"]).name for record in entry.get("files", []))
        summaries.append(f"[{entry['time']}] {entry['tool']}: {paths}")
    return summaries


def undo_last():
    """Restore every file in the most recent checkpoint.

    Returns:
        dict with success, restored/deleted paths, and any skipped files.
    """
    entries = _load_index()
    if not entries:
        return {"success": False, "error": "Nothing to undo — no checkpoints recorded yet."}

    entry = entries.pop(-1)
    restored, deleted, skipped = [], [], []

    for record in entry.get("files", []):
        path = Path(record["path"])
        if not record.get("existed"):
            # The file did not exist before the tool ran: undo removes it.
            try:
                path.unlink(missing_ok=True)
                deleted.append(str(path))
            except OSError as error:
                skipped.append(f"{path}: {error}")
            continue

        snapshot_name = record.get("snapshot")
        if not snapshot_name:
            skipped.append(f"{path}: {record.get('skipped_reason', 'no snapshot saved')}")
            continue

        snapshot_path = _project_dir() / snapshot_name
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(snapshot_path.read_bytes())
            restored.append(str(path))
        except OSError as error:
            skipped.append(f"{path}: {error}")
        _delete_snapshot(record)

    _save_index(entries)
    return {
        "success": True,
        "tool": entry.get("tool", ""),
        "time": entry.get("time", ""),
        "trust_decision_id": entry.get("trust_decision_id"),
        "restored": restored,
        "deleted": deleted,
        "skipped": skipped,
    }
