"""Dashboard server: the page, the snapshot, the SSE stream, story files by id, and
token-gated reorder requests, thread posts, review requests and opinion acts from
localhost; stdlib only.

Never serves a directory.
"""

from __future__ import annotations

import hmac
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, BinaryIO, NamedTuple
from urllib.parse import parse_qs, urlsplit

from .. import opinions, reorders, system, threads
from ..backlog import Ask
from ..config import Config
from ..opinions import Opinions
from ..roles import RoleBook
from ..threads import Entry, Post
from . import snapshot, story_files
from .story_files import FileAsk
from .tool_groups import MiscAsk

POLL_SECONDS = 1.0
DEFAULT_PORT = 8765
KEEPALIVE = b": keepalive\n\n"
HOSTS = {"win32": "127.0.0.1"}
ALL_INTERFACES = {"0.0.0.0", ""}
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
WRITE_HOSTS = {"127.0.0.1", "::1"}
TOKEN_HEADER = "X-Agile-Team-Token"
MAX_BODY = 4096
MAX_POST_BODY = 32768
BODY_LIMITS: dict[str, int] = {
    "/api/reorder": MAX_BODY,
    "/api/thread": MAX_POST_BODY,
    "/api/review": MAX_BODY,
    "/api/opinion": MAX_BODY,
}
WHOLE_NUMBER = re.compile(r"[0-9]+")
INDEX = Path(__file__).parent / "index.html"


@dataclass(frozen=True)
class Dashboard:
    """What the server shows and how often the stream polls."""

    snapshot: Callable[[], dict[str, Any]]
    watched: Callable[[], list[Path]]
    poll_seconds: float = POLL_SECONDS
    vital_sign: Callable[[], str] = lambda: ""
    read_file: Callable[[FileAsk], str | None] = lambda _ask: None
    misc_calls: Callable[[MiscAsk], list[dict] | None] = lambda _ask: None
    queue: Callable[[Ask], reorders.Request] | None = None
    post: Callable[[Post], Entry | None] | None = None
    token: str = ""
    opinions: Opinions | None = None

    @classmethod
    def for_run(cls, config: Config, book: RoleBook) -> Dashboard:
        """A dashboard over one repo's run files."""
        return cls(
            partial(snapshot.build, config, book),
            partial(snapshot.watched_files, config),
            vital_sign=partial(snapshot.vital_sign, config),
            read_file=partial(story_files.read, config),
            misc_calls=partial(snapshot.misc_calls, config),
            queue=reorders.Requests(config.run_dir).queue,
            post=partial(threads.post_known, config.run_dir),
            opinions=Opinions(config.run_dir),
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
    status: int = 200


class Handler(BaseHTTPRequestHandler):
    """GET and token-gated POST handler; every unknown path is a 404."""

    def do_GET(self) -> None:
        ROUTES.get(urlsplit(self.path).path, _not_found)(self)

    def do_POST(self) -> None:
        POSTS.get(urlsplit(self.path).path, _not_found)(self)

    def log_message(self, format: str, *args: Any) -> None:
        """Quiet: the dashboard runs in the background."""


def open_server(address: tuple[str, int], app: Dashboard) -> system.HttpServer:
    """A threaded HTTP server for ``app`` (daemon threads; the handler reads ``server.app``)."""
    server = system.listen_http(address, Handler)
    server.app = app  # type: ignore[attr-defined]
    return server


def _send(handler: Handler, body: Body) -> None:
    handler.send_response(body.status)
    handler.send_header("Content-Type", body.content_type)
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(body.data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body.data)


def _index(handler: Handler) -> None:
    _send(handler, Body("text/html; charset=utf-8", system.read_bytes(INDEX)))


def _snapshot(handler: Handler) -> None:
    data = json.dumps(handler.server.app.snapshot()).encode()  # type: ignore[attr-defined]
    _send(handler, Body("application/json", data))


def _file(handler: Handler) -> None:
    query = parse_qs(urlsplit(handler.path).query)
    ask = FileAsk(*(query.get(key, [""])[0] for key in ("kind", "id")))
    text = handler.server.app.read_file(ask)  # type: ignore[attr-defined]
    if text is None:
        _not_found(handler)
    else:
        _send(handler, Body("text/plain; charset=utf-8", text.encode()))


def _misc(handler: Handler) -> None:
    query = parse_qs(urlsplit(handler.path).query)
    ask = MiscAsk(*(query.get(key, [""])[0] for key in MiscAsk._fields))
    calls = handler.server.app.misc_calls(ask)  # type: ignore[attr-defined]
    if calls is None:
        _not_found(handler)
    else:
        _send(handler, Body("application/json", json.dumps(calls).encode()))


def may_write(handler: Handler) -> bool:
    """Is the peer on localhost and does it carry the token (B18 checks 1-2)?"""
    if handler.client_address[0] not in WRITE_HOSTS:
        return False
    given = handler.headers.get(TOKEN_HEADER, "").encode()
    want = handler.server.app.token.encode()  # type: ignore[attr-defined]
    return bool(want) and hmac.compare_digest(given, want)


def _body(handler: Handler) -> bytes | None:
    """The request body when its Content-Length is 1 to the route's limit, else None."""
    raw = handler.headers.get("Content-Length", "")
    limit = BODY_LIMITS[urlsplit(handler.path).path]
    if not WHOLE_NUMBER.fullmatch(raw) or not 1 <= int(raw) <= limit:
        return None
    return handler.rfile.read(int(raw))


def _reorder(handler: Handler) -> None:
    if not may_write(handler):
        return handler.send_error(403)
    ask = reorders.parse_ask(_body(handler) or b"")
    queue = handler.server.app.queue  # type: ignore[attr-defined]
    if ask is None or queue is None:
        return handler.send_error(400)
    data = json.dumps({"id": queue(ask).id, "status": "queued"}).encode()
    _send(handler, Body("application/json", data, 202))


def _thread(handler: Handler) -> None:
    if not may_write(handler):
        return handler.send_error(403)
    post = threads.parse_post(_body(handler) or b"")
    send = handler.server.app.post  # type: ignore[attr-defined]
    entry = send(post) if post and send else None
    if entry is None:
        return handler.send_error(400)
    data = json.dumps({"id": entry.id, "status": "posted"}).encode()
    _send(handler, Body("application/json", data, 202))


def _review(handler: Handler) -> None:
    if not may_write(handler):
        return handler.send_error(403)
    box = handler.server.app.opinions  # type: ignore[attr-defined]
    if box is None or not opinions.is_object(_body(handler) or b""):
        return handler.send_error(400)
    data = json.dumps({"id": box.ask_review().id, "status": "asked"}).encode()
    _send(handler, Body("application/json", data, 202))


def _opinion(handler: Handler) -> None:
    if not may_write(handler):
        return handler.send_error(403)
    ask = opinions.parse_act(_body(handler) or b"")
    box = handler.server.app.opinions  # type: ignore[attr-defined]
    if ask is None or box is None:
        return handler.send_error(400)
    reason = box.refusal(ask)
    if reason:
        data = json.dumps({"status": "refused", "reason": reason}).encode()
        return _send(handler, Body("application/json", data, 409))
    done = box.act(ask)
    status = opinions.ACT_STATUS[done.act]
    data = json.dumps(
        {"id": done.id, "status": status, "route": str(done.route), "ref": done.ref}
    ).encode()
    _send(handler, Body("application/json", data, 202))


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
    "/api/file": _file,
    "/api/misc": _misc,
}
POSTS: dict[str, Callable[[Handler], None]] = {
    "/api/reorder": _reorder,
    "/api/thread": _thread,
    "/api/review": _review,
    "/api/opinion": _opinion,
}


def with_token(url: str, token: str) -> str:
    """``url`` with the write token in its query."""
    return f"{url}?token={token}"


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
