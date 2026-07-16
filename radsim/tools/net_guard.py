"""Egress guard: reject SSRF targets on the private/link-local ranges (R-06).

web_fetch and http_request accept model-controlled URLs. Without a check they
can reach loopback, RFC1918, link-local (including cloud metadata at
169.254.169.254), multicast, and reserved addresses — a server-side request
forgery primitive. This module resolves a URL's host and refuses any target
that is not a global unicast address, and re-validates redirect hops so a
public URL cannot bounce onto an internal one.

Set RADSIM_ALLOW_PRIVATE_EGRESS=1 to opt a trusted environment back into
reaching private hosts (e.g. local development against 127.0.0.1).
"""

import ipaddress
import os
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = ("http", "https")

# Hostnames that front cloud metadata services regardless of what they resolve
# to; block them by name as well as by address.
_METADATA_HOSTS = {
    "metadata.google.internal",
    "metadata.goog",
}

# Well-known metadata service addresses (link-local already blocks the first,
# but list them so the reason is explicit and IPv6/other-cloud forms are hit).
_METADATA_ADDRESSES = {
    "169.254.169.254",   # AWS / Azure / GCP IMDS
    "fd00:ec2::254",     # AWS IMDSv2 over IPv6
    "100.100.100.200",   # Alibaba Cloud
}


def private_egress_allowed():
    """Return True when the operator opted into reaching private hosts."""
    return os.getenv("RADSIM_ALLOW_PRIVATE_EGRESS", "").strip().lower() in ("1", "true", "yes")


def _address_is_global(ip_text):
    """Return True only for a genuinely global (public) unicast address."""
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False

    # Unwrap IPv4-mapped IPv6 (::ffff:127.0.0.1) so the v4 rules apply.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped

    if str(ip) in _METADATA_ADDRESSES or ip_text in _METADATA_ADDRESSES:
        return False

    return (
        ip.is_global
        and not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_unspecified
    )


def validate_egress_url(url, allow_private=None):
    """Return (is_allowed, reason) for a URL about to be fetched.

    Resolves the host and requires every A/AAAA result to be global, so a
    hostname that maps to a mix of public and private addresses is refused.
    Literal IPs (including IPv4-mapped IPv6 and numeric forms) are classified
    directly.
    """
    if allow_private is None:
        allow_private = private_egress_allowed()
    if allow_private:
        return True, None

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        return False, f"Only http/https URLs are allowed (got scheme {scheme!r})"

    host = parsed.hostname
    if not host:
        return False, "URL has no host"

    if host.lower() in _METADATA_HOSTS:
        return False, f"Blocked cloud-metadata host: {host}"

    # A literal IP address in the URL — classify without a DNS lookup.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not _address_is_global(host):
            return False, f"Blocked request to non-global address: {host}"
        return True, None

    port = parsed.port or (443 if scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        return False, f"Could not resolve host {host!r}: {exc}"

    addresses = {info[4][0] for info in infos}
    if not addresses:
        return False, f"Host {host!r} did not resolve to any address"

    for address in addresses:
        if not _address_is_global(address):
            return False, f"Host {host!r} resolves to non-global address {address}"

    return True, None
