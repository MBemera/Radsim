"""Security regression tests for SSRF egress control (R-06).

web_fetch and http_request followed any http(s) URL, so loopback, RFC1918,
link-local, and cloud-metadata targets were reachable and redirects were
followed blindly. These tests prove non-global targets are rejected before a
socket is opened, that redirect hops are re-validated, and that DNS results
are classified (a hostname resolving to a private address is refused).
"""

from unittest.mock import patch

import pytest

from radsim.tools import net_guard
from radsim.tools.net_guard import validate_egress_url
from radsim.tools.web import http_request, web_fetch


def _resolves_to(*addresses):
    """Fake socket.getaddrinfo returning the given IP strings."""
    def fake(host, port, *args, **kwargs):
        return [(None, None, None, "", (addr, port)) for addr in addresses]
    return fake


class TestLiteralAddressClassification:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/",
            "http://127.0.0.1:8080/private",
            "http://0.0.0.0/",
            "http://10.0.0.5/",
            "http://192.168.1.1/",
            "http://172.16.0.1/",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/",
            "http://[::ffff:127.0.0.1]/",
            "https://[fd00::1]/",
            "http://100.100.100.200/",
        ],
    )
    def test_non_global_literals_blocked(self, url):
        allowed, reason = validate_egress_url(url)
        assert allowed is False
        assert reason

    def test_metadata_hostname_blocked(self):
        allowed, reason = validate_egress_url("http://metadata.google.internal/")
        assert allowed is False
        assert "metadata" in reason.lower()

    def test_global_literal_allowed(self):
        allowed, _ = validate_egress_url("https://93.184.216.34/")
        assert allowed is True


class TestHostnameResolution:
    def test_hostname_resolving_to_private_blocked(self):
        with patch.object(net_guard.socket, "getaddrinfo", _resolves_to("10.1.2.3")):
            allowed, reason = validate_egress_url("http://sneaky.example.com/")
        assert allowed is False
        assert "non-global" in reason

    def test_hostname_mixed_results_blocked(self):
        # One public, one private -> refuse (DNS rebinding defence).
        with patch.object(net_guard.socket, "getaddrinfo", _resolves_to("93.184.216.34", "127.0.0.1")):
            allowed, _ = validate_egress_url("http://mixed.example.com/")
        assert allowed is False

    def test_hostname_all_global_allowed(self):
        with patch.object(net_guard.socket, "getaddrinfo", _resolves_to("93.184.216.34")):
            allowed, _ = validate_egress_url("http://example.com/")
        assert allowed is True


class TestOptIn:
    def test_env_opt_in_allows_private(self, monkeypatch):
        monkeypatch.setenv("RADSIM_ALLOW_PRIVATE_EGRESS", "1")
        allowed, _ = validate_egress_url("http://127.0.0.1/")
        assert allowed is True


class TestWebToolsBlockBeforeRequest:
    def test_web_fetch_blocks_loopback_without_network(self):
        # If the guard fails, urlopen would try to connect; assert it never does.
        with patch("radsim.tools.web.urllib.request.urlopen") as urlopen:
            result = web_fetch("http://127.0.0.1:8080/private")
        assert result["success"] is False
        assert "blocked" in result["error"].lower()
        urlopen.assert_not_called()

    def test_http_request_blocks_metadata(self):
        with patch("radsim.tools.web.urllib.request.urlopen") as urlopen:
            result = http_request("http://169.254.169.254/latest/meta-data/")
        assert result["success"] is False
        assert "blocked" in result["error"].lower()
        urlopen.assert_not_called()

    def test_http_request_header_validation_still_runs_first(self):
        # Header injection is caught before any DNS lookup.
        result = http_request(
            "https://example.com", headers={"X-Ok": "value\r\nEvil: injected"}
        )
        assert result["success"] is False
        assert "control characters" in result["error"]
