"""Is the Claude API reachable? A plain TCP connect, so checking costs no tokens."""

from __future__ import annotations

import socket

API_HOST = ("api.anthropic.com", 443)
PROBE_TIMEOUT = 5.0


def online(address: tuple[str, int] = API_HOST) -> bool:
    """True when a TCP connection to ``address`` opens (DNS included)."""
    try:
        socket.create_connection(address, timeout=PROBE_TIMEOUT).close()
    except OSError:
        return False
    return True
