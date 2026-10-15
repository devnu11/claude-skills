"""s58 end to end: a sandboxed curl reaches a local service only with allowLocalBinding."""

from __future__ import annotations

import copy
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

import pytest
from agile_team import config as cfg
from agile_team import sandbox
from agile_team.config import Environment

from .readiness import serving
from .scripted_cli import CliRun, run_scripted

CURL_MAX_S = 60

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="allowLocalBinding applies to Claude Code's macOS (Seatbelt) sandbox; "
    "the Linux bubblewrap sandbox is not verified (s58)",
)


class Service(BaseHTTPRequestHandler):
    """The local service the Proxy is asked to accept: 200 ``ok``."""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def service():
    server = serving(Service)
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def run_cli(
    settings: dict, prepared: sandbox.Prepared, port: int, tmp: Path
) -> tuple[int, list[str]]:
    """Run the bundled CLI against a scripted model; return its exit code and the tool results."""
    url = f"http://127.0.0.1:{port}/"
    curl = (
        f"curl -s -o /dev/null -w '%{{http_code}}' --max-time {CURL_MAX_S} {url}; echo \" exit=$?\""
    )
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    return run_scripted(CliRun(settings, prepared.workdir, home, home / ".claude"), curl)


@pytest.fixture
def proxy(configured: Path, service: int):
    d = Environment("dash", "web", url=f"http://127.0.0.1:{service}/")
    c = cfg.load(configured)
    c.environments = [d]
    prepared = sandbox.layout(c, d)
    return sandbox.os_sandbox_settings(c, prepared), prepared


def test_sandboxed_curl_reaches_service_with_local_binding(
    proxy, service: int, tmp_path: Path
) -> None:
    settings, prepared = proxy
    code, results = run_cli(settings, prepared, service, tmp_path)
    assert code == 0, results
    assert len(results) == 1, results
    assert "200 exit=0" in results[0], results


def test_sandboxed_curl_fails_without_local_binding(proxy, service: int, tmp_path: Path) -> None:
    settings, prepared = proxy
    bare = copy.deepcopy(settings)
    del bare["sandbox"]["network"]
    _, results = run_cli(bare, prepared, service, tmp_path)
    assert len(results) == 1, results
    assert "exit=7" in results[0], results
