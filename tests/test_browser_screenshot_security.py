"""Security regression tests for browser_screenshot path containment (R-04).

browser_screenshot joined a model-controlled filename straight onto
~/.radsim/screenshots, so a filename with parent components resolved outside
that directory and Playwright would write PNG bytes there. These tests prove
only a bare .png basename inside the screenshots directory is accepted.
"""

import pytest

from radsim.browser import _safe_screenshot_path


class TestSafeScreenshotPath:
    def test_default_name_is_inside_dir(self, tmp_path):
        path, error = _safe_screenshot_path(tmp_path, None)
        assert error is None
        assert path.parent == tmp_path.resolve()
        assert path.suffix == ".png"

    def test_plain_png_accepted(self, tmp_path):
        path, error = _safe_screenshot_path(tmp_path, "shot.png")
        assert error is None
        assert path == (tmp_path.resolve() / "shot.png")

    def test_png_suffix_appended(self, tmp_path):
        path, error = _safe_screenshot_path(tmp_path, "shot")
        assert error is None
        assert path.name == "shot.png"

    @pytest.mark.parametrize(
        "bad",
        [
            "../../etc/evil.png",
            "../evil.png",
            "sub/shot.png",
            "/etc/passwd.png",
            "/etc/evil",
            "..",
            ".",
            "dir/../../escape.png",
            "a/b.png",
        ],
    )
    def test_path_components_rejected(self, tmp_path, bad):
        path, error = _safe_screenshot_path(tmp_path, bad)
        assert path is None
        assert error is not None

    def test_null_byte_rejected(self, tmp_path):
        path, error = _safe_screenshot_path(tmp_path, "a\x00.png")
        assert path is None
        assert error is not None

    def test_resolved_path_stays_in_dir(self, tmp_path):
        # Even an accepted name resolves to a direct child of the dir.
        path, error = _safe_screenshot_path(tmp_path, "ok.png")
        assert error is None
        assert path.parent == tmp_path.resolve()
