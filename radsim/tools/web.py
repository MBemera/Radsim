"""Web tools for RadSim.

RadSim Principle: Simple, Obvious Implementation
"""

import logging
import urllib.error
import urllib.request

from .constants import MAX_OUTPUT_SIZE
from .net_guard import validate_egress_url

logger = logging.getLogger(__name__)



class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validate every redirect target so a public URL cannot bounce inward.

    urllib follows 3xx redirects automatically; without this a permitted
    public host could redirect to http://169.254.169.254/ or a loopback
    service (DNS-rebinding / open-redirect SSRF).
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed, reason = validate_egress_url(newurl)
        if not allowed:
            raise urllib.error.HTTPError(newurl, code, f"Blocked redirect: {reason}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _guarded_opener():
    """Build a urllib opener that validates redirect hops."""
    return urllib.request.build_opener(_ValidatingRedirectHandler())


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

        allowed, reason = validate_egress_url(url)
        if not allowed:
            return {"success": False, "error": f"Request blocked: {reason}"}

        headers = {"User-Agent": "RadSim/1.0 (CLI Coding Agent)"}

        request = urllib.request.Request(url, headers=headers)

        with _guarded_opener().open(request, timeout=30) as response:
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


ALLOWED_HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")


def _validate_http_headers(headers):
    """Reject header names/values that could smuggle extra headers."""
    for name, value in headers.items():
        combined = f"{name}{value}"
        if any(ch in combined for ch in "\r\n\x00"):
            return False, f"Header '{name}' contains control characters"
    return True, None


def http_request(url, method="GET", headers=None, body="", timeout=30):
    """Make an HTTP request to an API endpoint.

    Unlike web_fetch (page content), this supports methods with bodies
    for working with JSON/REST APIs. The response body is untrusted
    input. Request headers are never echoed back into the result so an
    Authorization header cannot leak into the transcript.

    Args:
        url: Full http(s) URL
        method: One of GET, POST, PUT, PATCH, DELETE, HEAD
        headers: Optional dict of request headers
        body: Optional request body string (JSON should be pre-encoded)
        timeout: Seconds before the request is abandoned

    Returns:
        dict with success, status, content_type, and body text
    """
    if not url.startswith(("http://", "https://")):
        return {"success": False, "error": "URL must start with http:// or https://"}

    method = str(method).upper()
    if method not in ALLOWED_HTTP_METHODS:
        return {
            "success": False,
            "error": f"Method '{method}' not allowed. Use one of: {', '.join(ALLOWED_HTTP_METHODS)}",
        }

    request_headers = {"User-Agent": "RadSim/1.0 (CLI Coding Agent)"}
    if headers:
        if not isinstance(headers, dict):
            return {"success": False, "error": "headers must be an object of name: value pairs"}
        headers_ok, header_error = _validate_http_headers(headers)
        if not headers_ok:
            return {"success": False, "error": header_error}
        request_headers.update({str(k): str(v) for k, v in headers.items()})

    allowed, reason = validate_egress_url(url)
    if not allowed:
        return {"success": False, "error": f"Request blocked: {reason}"}

    data = str(body).encode("utf-8") if body else None
    if data and "Content-Type" not in {k.title() for k in request_headers}:
        request_headers["Content-Type"] = "application/json"

    try:
        request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        timeout = min(max(int(timeout), 1), 120)
        with _guarded_opener().open(request, timeout=timeout) as response:
            response_body = response.read(MAX_OUTPUT_SIZE + 1).decode("utf-8", errors="ignore")
            truncated = len(response_body) > MAX_OUTPUT_SIZE
            if truncated:
                response_body = response_body[:MAX_OUTPUT_SIZE] + "\n... [Response truncated]"
            return {
                "success": True,
                "status": response.status,
                "content_type": response.headers.get("Content-Type", "unknown"),
                "body": response_body,
            }
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read(2000).decode("utf-8", errors="ignore")
        except Exception:
            logger.debug("Reading the HTTP error body failed", exc_info=True)
        return {"success": False, "status": e.code, "error": f"HTTP {e.code}: {e.reason}", "body": error_body}
    except urllib.error.URLError as e:
        return {"success": False, "error": f"URL Error: {e.reason}"}
    except Exception as error:
        return {"success": False, "error": str(error)}
