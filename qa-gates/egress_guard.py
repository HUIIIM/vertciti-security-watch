"""Outbound address guard shared by gates 2 and 3 (SOTA SEC-A2).

Every outbound hop a gate makes is checked before it connects: the host is
resolved and *every* address it resolves to must be publicly routable
(``ipaddress`` ``is_global``, not multicast). Loopback, private (RFC 1918),
link-local (incl. the 169.254.169.254 cloud-metadata address), CGNAT
(100.64/10), unspecified, reserved and documentation ranges are refused, as are
IPv4-mapped / NAT64-wrapped forms of them. A host that does not resolve is
refused too (fail-closed).

After the connection, callers verify the address actually connected to with
:func:`ip_allowed` (gate 2: curl ``%{remote_ip}``; gate 3: Playwright
``response.server_addr()``), so a DNS answer that changes between the check and
the connection (rebinding) is still caught.

``QA_EGRESS_ALLOW_HOSTS`` (space-separated exact host names or IP literals)
exempts named hosts from the non-public check; it exists for the repo's own
tests, which serve fixtures on 127.0.0.1. Callers log every exemption used.

CLI (used by gate 2, a shell script):
    python3 egress_guard.py resolve <URL>        -> "<host> <port> <ip>" or exit 1
    python3 egress_guard.py verify <HOST> <IP>   -> exit 0 if IP is allowed for HOST
    python3 egress_guard.py exempt <HOST>        -> exit 0 if HOST is in QA_EGRESS_ALLOW_HOSTS
"""

from __future__ import annotations

import ipaddress
import os
import socket
import sys
from urllib.parse import urlsplit

ALLOW_ENV = "QA_EGRESS_ALLOW_HOSTS"
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def allow_hosts() -> set[str]:
    """Hosts exempted from the non-public check via QA_EGRESS_ALLOW_HOSTS."""
    return {h.strip("[]").lower() for h in os.environ.get(ALLOW_ENV, "").split() if h}


def _norm_host(host: str) -> str:
    return host.strip("[]").rstrip(".").lower()


def ip_allowed(ip: str) -> bool:
    """True only for a publicly routable unicast address."""
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        elif addr in _NAT64:
            addr = ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
    return addr.is_global and not addr.is_multicast


def host_exempt(host: str) -> bool:
    return _norm_host(host) in allow_hosts()


def check_host(host: str, port: int) -> tuple[list[str], str | None]:
    """Resolve host; return (addresses, None) if every address is allowed, else (addresses, reason)."""
    host = _norm_host(host)
    if not host:
        return [], "no host"
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        return [], "cannot resolve %s: %s" % (host, exc)
    ips = list(dict.fromkeys(str(info[4][0]) for info in infos))
    if not ips:
        return [], "cannot resolve %s: no addresses" % host
    if host in allow_hosts():
        return ips, None
    bad = [ip for ip in ips if not ip_allowed(ip)]
    if bad:
        return ips, "%s resolves to non-public address(es) %s" % (host, ", ".join(bad))
    return ips, None


def check_url(url: str) -> tuple[str, int, list[str], str | None]:
    """Check an http(s) URL: (host, port, addresses, reason-or-None)."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return "", 0, [], "scheme %r not allowed (http/https only)" % (scheme or "")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        return "", 0, [], "bad port: %s" % exc
    host = _norm_host(parts.hostname or "")
    ips, err = check_host(host, port)
    return host, port, ips, err


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "resolve":
        host, port, ips, err = check_url(argv[2])
        if err:
            print(err, file=sys.stderr)
            return 1
        print(host, port, ips[0])
        return 0
    if len(argv) == 4 and argv[1] == "verify":
        return 0 if host_exempt(argv[2]) or ip_allowed(argv[3]) else 1
    if len(argv) == 3 and argv[1] == "exempt":
        return 0 if host_exempt(argv[2]) else 1
    print(__doc__.split("CLI", 1)[1].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
