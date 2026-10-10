"""The token-free reachability probe."""

from __future__ import annotations

import socket

from unattended.network import online


def test_online_when_a_listener_answers() -> None:
    with socket.create_server(("127.0.0.1", 0)) as server:
        assert online(server.getsockname()[:2])


def test_offline_when_nothing_listens() -> None:
    with socket.create_server(("127.0.0.1", 0)) as server:
        address = server.getsockname()[:2]
    assert not online(address)
