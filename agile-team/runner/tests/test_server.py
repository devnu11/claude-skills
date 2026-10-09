"""Read-only dashboard server: routes, SSE stream, helpers (s4, D11-D13)."""

from __future__ import annotations

import http.client
import json
import os
import threading
from collections.abc import Iterator
from importlib import resources
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agile_team.dashboard import server
from agile_team.dashboard.server import Dashboard, DashboardServer

SNAP = {"generated_at": 1.0, "run": {"status": "idle"}}
ALL_INTERFACES = "0.0.0.0"


@pytest.fixture
def box(tmp_path: Path) -> dict[str, Any]:
    watched = tmp_path / "watched.json"
    watched.write_text("one")
    return {"snap": dict(SNAP), "file": watched}


@pytest.fixture
def httpd(box: dict[str, Any]) -> Iterator[DashboardServer]:
    app = Dashboard(lambda: box["snap"], lambda: [box["file"]], poll_seconds=0.01)
    srv = DashboardServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def conn(srv: DashboardServer, timeout: float = 2.0) -> http.client.HTTPConnection:
    return http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=timeout)


def fetch(srv: DashboardServer, path: str, method: str = "GET") -> http.client.HTTPResponse:
    c = conn(srv)
    c.request(method, path)
    return c.getresponse()


# ----- 11-12. routes -----------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/?mock"])
def test_index(httpd: DashboardServer, path: str) -> None:
    resp = fetch(httpd, path)
    assert resp.status == 200
    assert resp.getheader("Content-Type").startswith("text/html")
    want = (resources.files("agile_team.dashboard") / "index.html").read_bytes()
    assert resp.read() == want


def test_snapshot_route(httpd: DashboardServer, box: dict[str, Any]) -> None:
    resp = fetch(httpd, "/api/snapshot?x=1")
    assert resp.status == 200
    assert resp.getheader("Content-Type") == "application/json"
    assert resp.getheader("Cache-Control") == "no-store"
    assert json.loads(resp.read()) == box["snap"]


# ----- 13. 404 / no directory serving -------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/index.html",
        "/api",
        "/api/snapshot/",
        "/api/stream/x",
        "/fixtures/snapshot.json",
        "/dashboard/",
        "/.team/run/state.json",
        "/../.team/run/keyfile",
        "/%2e%2e/keyfile",
    ],
)
def test_other_paths_are_404(httpd: DashboardServer, path: str) -> None:
    resp = fetch(httpd, path)
    assert resp.status == 404
    assert b"secret" not in resp.read()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_other_methods_are_501(httpd: DashboardServer, method: str) -> None:
    assert fetch(httpd, "/", method).status == 501


# ----- 14. SSE ------------------------------------------------------------------


def read_sse(resp: http.client.HTTPResponse, want: int) -> tuple[list[dict[str, Any]], int]:
    """Read lines until ``want`` data events arrive; return them and the keepalive count."""
    events, keepalives = [], 0
    while len(events) < want:
        line = resp.readline().decode()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
        elif line.startswith(": keepalive"):
            keepalives += 1
    return events, keepalives


def test_stream_pushes_on_change_and_keeps_alive(
    httpd: DashboardServer, box: dict[str, Any]
) -> None:
    c = conn(httpd, timeout=3.0)
    c.request("GET", "/api/stream")
    resp = c.getresponse()
    assert resp.status == 200
    assert resp.getheader("Content-Type") == "text/event-stream"
    assert resp.getheader("Cache-Control") == "no-store"
    first, _ = read_sse(resp, 1)
    assert first[0] == SNAP
    box["snap"] = {**SNAP, "generated_at": 2.0}
    box["file"].write_text("changed content")
    stat = box["file"].stat()
    os.utime(box["file"], ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    later, keepalives = read_sse(resp, 1)
    assert later[0]["generated_at"] == 2.0
    assert keepalives >= 1
    c.close()


# ----- 15. _pump / _stream ------------------------------------------------------


class FailingWriter:
    """Accepts the first write, then raises ``exc`` on the next."""

    def __init__(self, exc: type[Exception]) -> None:
        self.exc = exc
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> int:
        if self.writes:
            raise self.exc
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        pass


def stub_app(file: Path) -> Dashboard:
    return Dashboard(lambda: SNAP, lambda: [file], poll_seconds=0.0)


@pytest.mark.parametrize("exc", [BrokenPipeError, ConnectionResetError])
def test_pump_raises_and_stream_ends_cleanly(exc: type[Exception], box: dict[str, Any]) -> None:
    out = FailingWriter(exc)
    with pytest.raises(exc):
        server._pump(out, stub_app(box["file"]))
    assert out.writes == [server.sse_data(SNAP)]
    sent: list[Any] = []
    handler = SimpleNamespace(
        wfile=FailingWriter(exc),
        server=SimpleNamespace(app=stub_app(box["file"])),
        send_response=sent.append,
        send_header=lambda k, v: sent.append((k, v)),
        end_headers=lambda: sent.append("end"),
    )
    assert server._stream(handler) is None
    assert 200 in sent and ("Content-Type", "text/event-stream") in sent


def test_pump_sends_data_once_then_keepalives(box: dict[str, Any]) -> None:
    class Stop(Exception):
        pass

    class Writer:
        def __init__(self) -> None:
            self.writes: list[bytes] = []

        def write(self, data: bytes) -> int:
            self.writes.append(data)
            if len(self.writes) == 3:
                raise Stop
            return len(data)

        def flush(self) -> None:
            pass

    out = Writer()
    with pytest.raises(Stop):
        server._pump(out, stub_app(box["file"]))
    assert out.writes == [server.sse_data(SNAP), server.KEEPALIVE, server.KEEPALIVE]


def test_sse_data_is_one_line() -> None:
    data = server.sse_data({"text": "a\nb"})
    assert data.startswith(b"data: ") and data.endswith(b"\n\n")
    assert data.count(b"\n") == 2


# ----- 16. fingerprint ----------------------------------------------------------


def test_fingerprint(tmp_path: Path) -> None:
    f = tmp_path / "a"
    missing = tmp_path / "missing"
    assert server.fingerprint([missing]) == ()
    f.write_text("x")
    base = server.fingerprint([f, missing])
    assert len(base) == 1 and base[0][0] == str(f)
    f.write_text("xy")
    sized = server.fingerprint([f])
    assert sized != base
    stat = f.stat()
    os.utime(f, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert server.fingerprint([f]) != sized
    assert len(server.fingerprint([f, missing])) == 1
    missing.write_text("now here")
    assert len(server.fingerprint([f, missing])) == 2


# ----- 17. D13 ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "host"),
    [("win32", "127.0.0.1"), ("linux", ALL_INTERFACES), ("darwin", ALL_INTERFACES)],
)
def test_default_host(monkeypatch: pytest.MonkeyPatch, platform: str, host: str) -> None:
    monkeypatch.setattr("sys.platform", platform)
    assert server.default_host() == host


def test_display_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("socket.gethostname", lambda: "labbox")
    assert server.display_url(ALL_INTERFACES, 8765) == "http://labbox:8765/"
    assert server.display_url("", 1) == "http://labbox:1/"
    assert server.display_url("127.0.0.1", 9) == "http://127.0.0.1:9/"


def test_constants() -> None:
    assert server.POLL_SECONDS == 1.0 and server.DEFAULT_PORT == 8765
    assert server.KEEPALIVE == b": keepalive\n\n"


# ----- 18. serve ----------------------------------------------------------------


def test_serve_returns_after_shutdown(box: dict[str, Any]) -> None:
    srv = DashboardServer(("127.0.0.1", 0), stub_app(box["file"]))
    thread = threading.Thread(target=server.serve, args=(srv,), daemon=True)
    thread.start()
    srv.shutdown()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_dashboard_for_run_wires_build_and_watched(tmp_path: Path) -> None:
    from agile_team import config as cfg
    from agile_team.roles import RoleBook

    (tmp_path / cfg.CONFIG_NAME).write_text("")
    config = cfg.load(tmp_path)
    app = Dashboard.for_run(config, RoleBook.for_repo(tmp_path, {}, tmp_path / "none"))
    assert next(iter(app.snapshot())) == "generated_at"
    assert app.watched()[0] == config.run_dir / "state.json"
    assert app.poll_seconds == server.POLL_SECONDS


def test_handler_log_is_silent(httpd: DashboardServer, capsys: pytest.CaptureFixture) -> None:
    fetch(httpd, "/api/snapshot").read()
    assert capsys.readouterr().err == ""
