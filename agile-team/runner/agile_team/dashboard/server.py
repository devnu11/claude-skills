"""Read-only dashboard server: ``/``, ``/api/snapshot`` and an SSE stream, stdlib only.

Never serves a directory.
"""

from __future__ import annotations

import json
import socket
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, BinaryIO, NamedTuple
from urllib.parse import urlsplit

from ..config import Config
from ..roles import RoleBook
from . import snapshot

POLL_SECONDS = 1.0
DEFAULT_PORT = 8765
KEEPALIVE = b": keepalive\n\n"
HOSTS = {"win32": "127.0.0.1"}
ALL_INTERFACES = {"0.0.0.0", ""}
INDEX = resources.files(__package__) / "index.html"


@dataclass(frozen=True)
class Dashboard:
    """What the server shows and how often the stream polls."""

    snapshot: Callable[[], dict[str, Any]]
    watched: Callable[[], list[Path]]
    poll_seconds: float = POLL_SECONDS

    @classmethod
    def for_run(cls, config: Config, book: RoleBook) -> Dashboard:
        """A dashboard over one repo's run files."""
        return cls(partial(snapshot.build, config, book), partial(snapshot.watched_files, config))


Fingerprint = tuple[tuple[str, int, int], ...]


def _stat(path: Path) -> tuple[str, int, int] | None:
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    return (str(path), info.st_mtime_ns, info.st_size)


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


class DashboardServer(ThreadingHTTPServer):
    """Threaded HTTP server carrying the ``Dashboard`` it shows."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], app: Dashboard) -> None:
        self.app = app
        super().__init__(address, Handler)


def _send(handler: Handler, body: Body) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", body.content_type)
    handler.send_header("Content-Length", str(len(body.data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body.data)


def _index(handler: Handler) -> None:
    _send(handler, Body("text/html; charset=utf-8", INDEX.read_bytes()))


def _snapshot(handler: Handler) -> None:
    data = json.dumps(handler.server.app.snapshot()).encode()  # type: ignore[attr-defined]
    _send(handler, Body("application/json", data))


def _not_found(handler: Handler) -> None:
    handler.send_error(404)


def sse_data(snap: dict[str, Any]) -> bytes:
    """One SSE data event; ``json.dumps`` never emits a raw newline."""
    return f"data: {json.dumps(snap)}\n\n".encode()


def _pump(out: BinaryIO, app: Dashboard) -> None:
    last: Fingerprint | None = None
    while True:
        now = fingerprint(app.watched())
        out.write(sse_data(app.snapshot()) if now != last else KEEPALIVE)
        out.flush()
        last = now
        time.sleep(app.poll_seconds)


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


def display_url(host: str, port: int) -> str:
    """The URL to show; an all-interfaces host becomes this machine's name."""
    name = socket.gethostname() if host in ALL_INTERFACES else host
    return f"http://{name}:{port}/"


def serve(server: DashboardServer) -> None:
    """Serve until interrupted; Ctrl-C propagates."""
    with server:
        server.serve_forever()
