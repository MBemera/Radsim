"""Screen capture tool: photograph the screen so the model can see it.

macOS only. Uses the system `screencapture` binary (argv form, no shell)
and reuses read_image so the pixels travel as a private image payload.
Capturing the screen is privacy-sensitive, so the tool is
confirmation-gated in agent_constants.CONFIRMATION_TOOLS.
"""

import platform
import subprocess
import time
from pathlib import Path

from .documents import MAX_IMAGE_BYTES, read_image
from .validation import validate_path

CAPTURE_TIMEOUT_SECONDS = 15
RESIZE_MAX_DIMENSION = "1500"


def screen_capture(save_path=""):
    """Capture the full screen to an image the model can interpret.

    Args:
        save_path: Optional filename for the screenshot (inside the
            project directory). Defaults to a timestamped name.

    Returns:
        dict with success, file_path, and a private _image payload.
    """
    if platform.system() != "Darwin":
        return {"success": False, "error": "screen_capture is only available on macOS"}

    if not save_path:
        save_path = f"screenshot-{time.strftime('%Y%m%d-%H%M%S')}.png"
    if not save_path.endswith(".png"):
        save_path += ".png"

    is_safe, resolved_path, path_error = validate_path(save_path)
    if not is_safe:
        return {"success": False, "error": path_error}
    save_path = str(resolved_path)

    try:
        completed = subprocess.run(
            ["screencapture", "-x", save_path],
            capture_output=True,
            text=True,
            timeout=CAPTURE_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError) as error:
        return {"success": False, "error": f"screencapture failed: {error}"}

    capture_file = Path(save_path)
    if completed.returncode != 0 or not capture_file.exists() or capture_file.stat().st_size == 0:
        return {
            "success": False,
            "error": (
                "Screen capture produced no image. On macOS, grant Screen "
                "Recording permission to your terminal in System Settings > "
                "Privacy & Security > Screen Recording, then retry."
            ),
        }

    if capture_file.stat().st_size > MAX_IMAGE_BYTES:
        _shrink_in_place(save_path)

    result = read_image(save_path)
    if result.get("success"):
        result["file_path"] = save_path
        result["note"] = f"Screenshot saved to {save_path}. " + result.get("note", "")
    return result


def _shrink_in_place(image_path):
    """Downscale a too-large capture with sips (present on every macOS)."""
    try:
        subprocess.run(
            ["sips", "-Z", RESIZE_MAX_DIMENSION, image_path],
            capture_output=True,
            timeout=CAPTURE_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass  # read_image will reject with its own size guidance
