"""Small persistence helpers shared by RadSim state stores."""

import json
import os
import tempfile
from pathlib import Path


def atomic_write_json(
    path: str | Path,
    data,
    secure: bool = False,
    default=None,
) -> None:
    """Serialize data via a same-directory temp file and atomic replace.

    When secure is true, POSIX directory and file modes are restricted to
    0700 and 0600 for secret-bearing state.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if secure:
        _set_posix_mode(destination.parent, 0o700)

    file_descriptor, temp_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as temp_file:
            json.dump(data, temp_file, indent=2, default=default)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_name, destination)
        if secure:
            _set_posix_mode(destination, 0o600)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _set_posix_mode(path: Path, mode: int) -> None:
    """Apply a restrictive POSIX mode without breaking other platforms."""
    if os.name != "posix":
        return
    try:
        os.chmod(path, mode)
    except OSError:
        pass
