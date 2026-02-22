"Browser automation tools using Playwright."

import time
from pathlib import Path

# Global browser state
_BROWSER_INSTANCE = None
_PLAYWRIGHT_INSTANCE = None
_CONTEXT_INSTANCE = None
_PAGE_INSTANCE = None


def _ensure_browser():
    """Ensure browser is open and ready.

    Returns:
        page object
    """
    global _BROWSER_INSTANCE, _PLAYWRIGHT_INSTANCE, _CONTEXT_INSTANCE, _PAGE_INSTANCE

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ImportError(
            "Playwright is not installed. Run: pip install playwright && playwright install chromium"
        ) from None

    if _PAGE_INSTANCE and not _PAGE_INSTANCE.is_closed():
        return _PAGE_INSTANCE

    if not _PLAYWRIGHT_INSTANCE:
        _PLAYWRIGHT_INSTANCE = sync_playwright().start()

    if not _BROWSER_INSTANCE:
        _BROWSER_INSTANCE = _PLAYWRIGHT_INSTANCE.chromium.launch(headless=False)

    if not _CONTEXT_INSTANCE:
        _CONTEXT_INSTANCE = _BROWSER_INSTANCE.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

    if not _PAGE_INSTANCE or _PAGE_INSTANCE.is_closed():
        _PAGE_INSTANCE = _CONTEXT_INSTANCE.new_page()

    return _PAGE_INSTANCE


def browser_open(url):
    """Visit a URL.

    Args:
        url: URL to visit

    Returns:
        dict with title, url, content preview, screenshot path
    """
    try:
        page = _ensure_browser()
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(1)  # Brief wait for dynamic content

        # Take screenshot
        screenshots_dir = Path.home() / ".radsim" / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        filename = f"screenshot_{int(time.time())}.png"
        path = screenshots_dir / filename
        page.screenshot(path=path)

        # Get content
        title = page.title()
        content = page.evaluate("document.body.innerText")

        # Clean up content
        content = "\n".join([line.strip() for line in content.splitlines() if line.strip()])
        if len(content) > 5000:
            content = content[:5000] + "\n... [truncated]"

        return {
            "success": True,
            "title": title,
            "url": page.url,
            "screenshot": str(path),
            "content": content,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def browser_click(selector):
    """Click an element.

    Args:
        selector: CSS selector or text to click

    Returns:
        dict with success status
    """
    try:
        page = _ensure_browser()

        # Try to click
        try:
            page.click(selector, timeout=2000)
        except Exception:
            # Try finding by text if selector fails
            page.get_by_text(selector).first.click()

        time.sleep(1)
        return {"success": True, "message": f"Clicked '{selector}'"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def browser_type(selector, text):
    """Type text into an input.

    Args:
        selector: CSS selector for input
        text: Text to type

    Returns:
        dict with success status
    """
    try:
        page = _ensure_browser()
        page.fill(selector, text)
        return {"success": True, "message": f"Typed into '{selector}'"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def browser_screenshot(filename=None):
    """Take a screenshot of current page.

    Args:
        filename: Optional filename

    Returns:
        dict with path
    """
    try:
        page = _ensure_browser()
        screenshots_dir = Path.home() / ".radsim" / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        if not filename:
            filename = f"screenshot_{int(time.time())}.png"

        path = screenshots_dir / filename
        page.screenshot(path=path)
        return {"success": True, "path": str(path)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def close_browser():
    """Close the browser instance."""
    global _BROWSER_INSTANCE, _PLAYWRIGHT_INSTANCE, _CONTEXT_INSTANCE, _PAGE_INSTANCE

    if _BROWSER_INSTANCE:
        _BROWSER_INSTANCE.close()
        _BROWSER_INSTANCE = None

    if _PLAYWRIGHT_INSTANCE:
        _PLAYWRIGHT_INSTANCE.stop()
        _PLAYWRIGHT_INSTANCE = None

    _CONTEXT_INSTANCE = None
    _PAGE_INSTANCE = None

    return {"success": True}
