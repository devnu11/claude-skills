"""s82 end to end: the stop frees the service's port before it returns (real OS)."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest
import tomli_w
from agile_team import config as config_mod
from agile_team import sandbox, system
from agile_team.sandbox import Order, Preparer, port_in_use

from ..conftest import PY_CONFIG, git

SERVER = """\
import http.server, signal, sys, time

ignore = sys.argv[2] == "ignore"
handler = http.server.SimpleHTTPRequestHandler
server = http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), handler)


def on_term(*_):
    if ignore:
        return
    time.sleep(1)  # slow shutdown: the socket closes only after the leader shell is gone
    server.server_close()
    sys.exit(0)


signal.signal(signal.SIGTERM, on_term)
server.serve_forever()
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_config(configured: Path, tmp_path: Path, mode: str) -> tuple[config_mod.Config, int]:
    """A repo whose web delivery runs a shell leader that backgrounds a slow server."""
    script = tmp_path / "slow_server.py"
    script.write_text(SERVER)
    port = free_port()
    cfg = dict(PY_CONFIG)
    cfg["delivery"] = [
        {
            "name": "slow",
            "kind": "web",
            "prepare": f"sh -c '{sys.executable} {script} {port} {mode} & wait'",
            "url": f"http://127.0.0.1:{port}/",
            "probe": "",
        }
    ]
    (configured / config_mod.CONFIG_NAME).write_text(tomli_w.dumps(cfg))
    git(configured, "commit", "-qam", "slow delivery")
    return config_mod.load(configured), port


def start(config: config_mod.Config) -> sandbox.Prepared:
    return Preparer().prepare(config, Order(config.deliveries[0]))


def test_stop_waits_until_the_slow_server_frees_its_port(configured: Path, tmp_path: Path) -> None:
    config, port = make_config(configured, tmp_path, "slow")
    prepared = start(config)
    assert port_in_use("127.0.0.1", port)
    assert prepared.stop() is None
    assert not port_in_use("127.0.0.1", port)


def test_stop_kills_a_server_that_ignores_sigterm(
    configured: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, port = make_config(configured, tmp_path, "ignore")
    monkeypatch.setattr(sandbox, "STOP_WAIT_S", 0.2)
    prepared = start(config)
    assert prepared.stop() is None
    assert not port_in_use("127.0.0.1", port)


def test_stop_on_an_already_reaped_leader_sends_no_signal(
    configured: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _port = make_config(configured, tmp_path, "slow")
    prepared = start(config)
    assert prepared.stop() is None
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(system, "killpg", lambda pid, sig: sent.append((pid, sig)))
    sandbox.end_group(prepared.process)
    assert sent == []
