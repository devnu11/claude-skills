"""Read-only dashboard server: ``/``, ``/api/snapshot`` and an SSE stream, stdlib only.

Never serves a directory.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, BinaryIO, NamedTuple
from urllib.parse import urlsplit

from .. import system
from ..config import Config
from ..roles import RoleBook
from . import snapshot

POLL_SECONDS = 1.0
DEFAULT_PORT = 8765
KEEPALIVE = b": keepalive\n\n"
HOSTS = {"win32": "127.0.0.1"}
ALL_INTERFACES = {"0.0.0.0", ""}
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
INDEX = Path(__file__).parent / "index.html"


@dataclass(frozen=True)
class Dashboard:
    """What the server shows and how often the stream polls."""

    snapshot: Callable[[], dict[str, Any]]
    watched: Callable[[], list[Path]]
    poll_seconds: float = POLL_SECONDS
    vital_sign: Callable[[], str] = lambda: ""

    @classmethod
    def for_run(cls, config: Config, book: RoleBook) -> Dashboard:
        """A dashboard over one repo's run files."""
        return cls(
            partial(snapshot.build, config, book),
            partial(snapshot.watched_files, config),
            vital_sign=partial(snapshot.vital_sign, config),
        )


Fingerprint = tuple[tuple[str, int, int], ...]
Seen = tuple[Fingerprint, str]


def _stat(path: Path) -> tuple[str, int, int] | None:
    try:
        info = system.stat(path)
    except FileNotFoundError:
        return None
    return (str(path), info.mtime_ns, info.size)


def fingerprint(paths: list[Path]) -> Fingerprint:
    """Changes when a watched file appears, disappears or is written."""
    stats = (_stat(path) for path in paths)
    return tuple(s for s in stats if s is not None)


class Body(NamedTuple):
    """A response body and its content type."""

    content_type: str
    data: bytes


class Handler(BaseHTTPRequestHandler):
    """GET-only handler; every unknown path is a 404."""

    def do_GET(self) -> None:
        ROUTES.get(urlsplit(self.path).path, _not_found)(self)

    def log_message(self, format: str, *args: Any) -> None:
        """Quiet: the dashboard runs in the background."""


def open_server(address: tuple[str, int], app: Dashboard) -> system.HttpServer:
    """A threaded HTTP server for ``app`` (daemon threads; the handler reads ``server.app``)."""
    server = system.listen_http(address, Handler)
    server.app = app  # type: ignore[attr-defined]
    return server


def _send(handler: Handler, body: Body) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", body.content_type)
    handler.send_header("Content-Length", str(len(body.data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body.data)


def _index(handler: Handler) -> None:
    _send(handler, Body("text/html; charset=utf-8", system.read_bytes(INDEX)))


def _snapshot(handler: Handler) -> None:
    data = json.dumps(handler.server.app.snapshot()).encode()  # type: ignore[attr-defined]
    _send(handler, Body("application/json", data))


def _not_found(handler: Handler) -> None:
    handler.send_error(404)


def sse_data(snap: dict[str, Any]) -> bytes:
    """One SSE data event; ``json.dumps`` never emits a raw newline."""
    return f"data: {json.dumps(snap)}\n\n".encode()


def _pump(out: BinaryIO, app: Dashboard) -> None:
    last: Seen | None = None
    while True:
        now = (fingerprint(app.watched()), app.vital_sign())
        out.write(sse_data(app.snapshot()) if now != last else KEEPALIVE)
        out.flush()
        last = now
        system.sleep(app.poll_seconds)


def _stream(handler: Handler) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    try:
        _pump(handler.wfile, handler.server.app)  # type: ignore[attr-defined]
    except (BrokenPipeError, ConnectionResetError):
        return


ROUTES: dict[str, Callable[[Handler], None]] = {
    "/": _index,
    "/api/snapshot": _snapshot,
    "/api/stream": _stream,
}


def default_host() -> str:
    """All interfaces, except localhost on Windows."""
    return HOSTS.get(sys.platform, "0.0.0.0")


class Urls(NamedTuple):
    """Where the dashboard can be opened: here, and from other machines if it listens there."""

    local: str
    lan: str | None


def lan_name() -> str:
    """This machine's name on the LAN: its hostname, with ``.local`` added when it has no dot."""
    name = system.hostname()
    return name if "." in name else f"{name}.local"


def dashboard_urls(host: str, port: int) -> Urls:
    """The links to print for a listening ``host`` and ``port`` (S7)."""
    if host in ALL_INTERFACES:
        return Urls(f"http://localhost:{port}/", f"http://{lan_name()}:{port}/")
    name = "localhost" if host in LOOPBACK else host
    return Urls(f"http://{name}:{port}/", None)


def serve(server: system.HttpServer) -> None:
    """Serve until interrupted; Ctrl-C propagates."""
    with server:
        server.serve_forever()
