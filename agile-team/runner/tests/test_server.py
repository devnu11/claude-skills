"""Read-only dashboard server: routes, SSE stream, helpers (s4, D11-D13), on the fake (s76)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agile_team import config as cfg
from agile_team import system
from agile_team.dashboard import server
from agile_team.dashboard.server import Dashboard
from agile_team.roles import RoleBook

from .fake_system import FAKE_REPO, START_CLOCK, FakeSystem

SNAP = {"generated_at": 1.0, "run": {"status": "idle"}}
ALL_INTERFACES = "0.0.0.0"
WATCHED = FAKE_REPO / "watched.json"


class Wire:
    """A request handler without a socket: it records the status, headers and body."""

    def __init__(self, path: str = "/", app: Dashboard | None = None) -> None:
        self.path = path
        self.status: int | None = None
        self.headers: list[tuple[str, str]] = []
        self.wfile = io.BytesIO()
        self.server = SimpleNamespace(app=app)

    def send_response(self, code: int) -> None:
        self.status = code

    def send_header(self, name: str, value: str) -> None:
        self.headers.append((name, value))

    def end_headers(self) -> None:
        pass

    def send_error(self, code: int) -> None:
        self.status = code

    def header(self, name: str) -> str | None:
        return dict(self.headers).get(name)

    @property
    def body(self) -> bytes:
        return self.wfile.getvalue()


@pytest.fixture
def box(fake: FakeSystem) -> dict[str, Any]:
    fake.put(WATCHED, "one")
    return {"snap": dict(SNAP), "file": WATCHED}


@pytest.fixture
def app(box: dict[str, Any]) -> Dashboard:
    return Dashboard(lambda: box["snap"], lambda: [box["file"]], poll_seconds=0.01)


def get(path: str, app: Dashboard | None = None) -> Wire:
    wire = Wire(path, app)
    server.Handler.do_GET(wire)  # type: ignore[arg-type]
    return wire


# ----- 11-12. routes -----------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/?mock"])
def test_index(path: str) -> None:
    wire = get(path)
    assert wire.status == 200
    assert wire.header("Content-Type").startswith("text/html")
    assert wire.header("Cache-Control") == "no-store"
    assert wire.body == system.read_bytes(server.INDEX)
    assert wire.header("Content-Length") == str(len(wire.body))


def test_index_comes_from_the_package_directory() -> None:
    assert Path(server.__file__).parent / "index.html" == server.INDEX


def test_snapshot_route(app: Dashboard, box: dict[str, Any]) -> None:
    wire = get("/api/snapshot?x=1", app)
    assert wire.status == 200
    assert wire.header("Content-Type") == "application/json"
    assert wire.header("Cache-Control") == "no-store"
    assert json.loads(wire.body) == box["snap"]


# ----- 13. 404 / no directory serving -------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/index.html",
        "/api",
        "/api/snapshot/",
        "/api/stream/x",
        "/fixtures/other.json",
        "/dashboard/",
        "/.team/run/state.json",
        "/../.team/run/keyfile",
        "/%2e%2e/keyfile",
    ],
)
def test_other_paths_are_404(path: str) -> None:
    wire = get(path)
    assert wire.status == 404
    assert wire.body == b""


def test_routes_are_exactly_these() -> None:
    assert set(server.ROUTES) == {
        "/",
        "/api/snapshot",
        "/api/stream",
        "/api/file",
        "/api/misc",
        "/fixtures/snapshot.json",
    }


def test_the_fixture_is_served_as_json_without_a_token() -> None:
    wire = get("/fixtures/snapshot.json")
    assert wire.status == 200
    assert wire.header("Content-Type") == "application/json"
    assert wire.body == system.read_bytes(server.FIXTURE)


def test_the_fixture_comes_from_the_package_directory() -> None:
    assert Path(server.__file__).parent / "fixtures" / "snapshot.json" == server.FIXTURE


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_other_methods_are_not_handled(method: str) -> None:
    assert not hasattr(server.Handler, f"do_{method}")  # http.server answers 501


def test_handler_log_is_silent(capsys: pytest.CaptureFixture) -> None:
    server.Handler.log_message(Wire(), "%s", "x")  # type: ignore[arg-type]
    assert capsys.readouterr().err == ""


# ----- 14. SSE ------------------------------------------------------------------


def test_stream_sends_the_event_stream_headers_then_data(app: Dashboard) -> None:
    wire = Wire("/api/stream", app)
    wire.wfile = FailingWriter(BrokenPipeError)  # type: ignore[assignment]
    assert server._stream(wire) is None  # type: ignore[arg-type]
    assert wire.status == 200
    assert wire.header("Content-Type") == "text/event-stream"
    assert wire.header("Cache-Control") == "no-store"
    assert wire.wfile.writes == [server.sse_data(SNAP)]  # type: ignore[attr-defined]


def test_stream_pushes_on_change_and_keeps_alive(box: dict[str, Any], fake: FakeSystem) -> None:
    class Stop(Exception):
        pass

    class Writer:
        def __init__(self) -> None:
            self.writes: list[bytes] = []

        def write(self, data: bytes) -> int:
            self.writes.append(data)
            if len(self.writes) == 2:  # after the first keepalive: the run files change
                box["snap"] = {**SNAP, "generated_at": 2.0}
                system.write_text(box["file"], "changed content")
            if len(self.writes) == 4:
                raise Stop
            return len(data)

        def flush(self) -> None:
            pass

    out = Writer()
    with pytest.raises(Stop):
        server._pump(out, stub_app(box["file"], box))  # type: ignore[arg-type]
    assert out.writes[0] == server.sse_data(SNAP)
    assert out.writes[1] == server.KEEPALIVE
    assert json.loads(out.writes[2][len(b"data: ") :])["generated_at"] == 2.0
    assert out.writes[3] == server.KEEPALIVE


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


def stub_app(file: Path, box: dict[str, Any] | None = None) -> Dashboard:
    return Dashboard(lambda: box["snap"] if box else SNAP, lambda: [file], poll_seconds=0.5)


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


def test_pump_sends_data_once_then_keepalives_and_sleeps_the_poll(
    box: dict[str, Any], fake: FakeSystem
) -> None:
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
    assert fake.slept == [0.5, 0.5]


def test_sse_data_is_one_line() -> None:
    data = server.sse_data({"text": "a\nb"})
    assert data.startswith(b"data: ") and data.endswith(b"\n\n")
    assert data.count(b"\n") == 2


# ----- 16. fingerprint ----------------------------------------------------------


def test_fingerprint(fake: FakeSystem) -> None:
    f = FAKE_REPO / "a"
    missing = FAKE_REPO / "missing"
    assert server.fingerprint([missing]) == ()
    fake.put(f, "x", mtime=START_CLOCK)
    base = server.fingerprint([f, missing])
    assert len(base) == 1 and base[0][0] == str(f)
    fake.put(f, "xy", mtime=START_CLOCK)
    sized = server.fingerprint([f])
    assert sized != base
    fake.put(f, "xy", mtime=START_CLOCK + 1)
    assert server.fingerprint([f]) != sized
    assert len(server.fingerprint([f, missing])) == 1
    fake.put(missing, "now here")
    assert len(server.fingerprint([f, missing])) == 2


def test_fingerprint_carries_path_mtime_and_size(fake: FakeSystem) -> None:
    fake.put(WATCHED, "abc", mtime=START_CLOCK)
    assert server.fingerprint([WATCHED]) == ((str(WATCHED), int(START_CLOCK * 1e9), 3),)


# ----- 17. D13 ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "host"),
    [("win32", "127.0.0.1"), ("linux", ALL_INTERFACES), ("darwin", ALL_INTERFACES)],
)
def test_default_host(monkeypatch: pytest.MonkeyPatch, platform: str, host: str) -> None:
    monkeypatch.setattr("sys.platform", platform)
    assert server.default_host() == host


def test_dashboard_urls_replace_display_url() -> None:
    assert server.dashboard_urls(ALL_INTERFACES, 8765) == (
        "http://localhost:8765/", "http://fakehost.local:8765/",
    )  # fmt: skip
    assert server.dashboard_urls("127.0.0.1", 9) == ("http://localhost:9/", None)


def test_lan_name_keeps_a_dotted_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "hostname", lambda: "labbox.lan")
    assert server.lan_name() == "labbox.lan"


def test_constants() -> None:
    assert server.POLL_SECONDS == 1.0 and server.DEFAULT_PORT == 8765
    assert server.KEEPALIVE == b": keepalive\n\n"


# ----- 18. serve ----------------------------------------------------------------


def test_open_server_listens_on_the_address_and_carries_the_app(
    app: Dashboard, fake: FakeSystem
) -> None:
    srv = server.open_server(("127.0.0.1", 0), app)
    assert fake.listened == [("127.0.0.1", 0)]
    assert srv.app is app
    assert srv.RequestHandlerClass is server.Handler


def test_serve_returns_after_shutdown_and_closes(app: Dashboard) -> None:
    srv = server.open_server(("127.0.0.1", 0), app)
    assert server.serve(srv) is None
    assert srv.closed  # type: ignore[attr-defined]


def test_open_server_on_a_busy_address_raises(app: Dashboard, fake: FakeSystem) -> None:
    fake.listening.add(("127.0.0.1", 8765))
    with pytest.raises(OSError):
        server.open_server(("127.0.0.1", 8765), app)


def test_dashboard_for_run_wires_build_and_watched(repo: Path) -> None:
    system.write_text(repo / cfg.CONFIG_NAME, "")
    config = cfg.load(repo)
    app = Dashboard.for_run(config, RoleBook.for_repo(repo, {}, repo / "none"))
    assert next(iter(app.snapshot())) == "generated_at"
    assert app.watched()[0] == config.run_dir / "state.json"
    assert app.poll_seconds == server.POLL_SECONDS


def test_config_file_is_watched_and_budget_is_live(repo: Path) -> None:
    """s21 F5/F6: rewriting .agile-team.toml changes the fingerprint and the snapshot."""
    path = repo / cfg.CONFIG_NAME
    system.write_text(path, "[team]\nbudget_usd = 20.0\n")
    config = cfg.load(repo)
    app = Dashboard.for_run(config, RoleBook.for_repo(repo, {}, repo / "none"))
    before = server.fingerprint(app.watched())
    assert app.snapshot()["run"]["budget_usd"] == 20.0
    system.sleep(5)
    system.write_text(path, "[team]\nbudget_usd = 7.5\nmanager_every_pct = 30\n")
    assert server.fingerprint(app.watched()) != before
    assert app.snapshot()["run"]["budget_usd"] == 7.5
