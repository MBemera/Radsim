"""Web tools for RadSim.

RadSim Principle: Simple, Obvious Implementation
"""

import urllib.error
import urllib.request

from .constants import MAX_OUTPUT_SIZE


def web_fetch(url, prompt=None):
    """Fetch content from a URL.

    Args:
        url: URL to fetch
        prompt: Optional prompt to extract specific info (ignored for now)

    Returns:
        dict with success, content, url
    """
    try:
        # Basic URL validation
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        headers = {"User-Agent": "RadSim/1.0 (CLI Coding Agent)"}

        request = urllib.request.Request(url, headers=headers)

        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read().decode("utf-8", errors="ignore")

            # Truncate large responses
            if len(content) > MAX_OUTPUT_SIZE:
                content = content[:MAX_OUTPUT_SIZE] + "\n... [Content truncated]"

            return {
                "success": True,
                "url": url,
                "content": content,
                "content_type": response.headers.get("Content-Type", "unknown"),
            }
    except urllib.error.HTTPError as e:
        return {"success": False, "error": f"HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"success": False, "error": f"URL Error: {e.reason}"}
    except Exception as error:
        return {"success": False, "error": str(error)}
