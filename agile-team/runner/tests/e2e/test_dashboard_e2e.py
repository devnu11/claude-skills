"""s4 end to end: the real ``agile-team dashboard`` process, read over HTTP."""

from __future__ import annotations

import http.client
import json
import os
import re
import select
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from agile_team import events as events_mod

FIXTURE = Path(events_mod.__file__).parent / "dashboard" / "fixtures" / "snapshot.json"
BOOT = "import sys; from agile_team.cli import main; sys.exit(main())"
RUNNER = Path(events_mod.__file__).parent.parent


def _read_url(proc: subprocess.Popen, timeout: float = 20) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready, _, _ = select.select([proc.stdout], [], [], 0.5)
        if ready:
            match = re.search(r"dashboard: (http://\S+)", proc.stdout.readline())
            if match:
                return match.group(1)
        assert proc.poll() is None, "dashboard exited early"
    raise AssertionError("no dashboard URL printed")


@pytest.fixture
def dash(configured: Path, tmp_path: Path) -> Iterator[tuple[subprocess.Popen, str, Path]]:
    run = configured / ".team" / "run"
    run.mkdir(parents=True)
    (run / "events.jsonl").write_text(
        json.dumps({"id": "e1", "kind": "sprint-start", "at": time.time(), "data": {}}) + "\n"
    )
    env = {**os.environ, "AGILE_TEAM_HOME": str(tmp_path / "scratch-home")}
    cmd = [sys.executable, "-c", BOOT, "--repo", str(configured), "dashboard"]
    cmd += ["--host", "127.0.0.1", "--port", "0", "--no-open"]
    proc = subprocess.Popen(
        cmd, cwd=RUNNER, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    try:
        yield proc, _read_url(proc), run
    finally:
        proc.kill()
        proc.wait(timeout=10)


def _conn(url: str, timeout: float = 10) -> http.client.HTTPConnection:
    host_port = re.match(r"http://([^/]+)", url).group(1)
    return http.client.HTTPConnection(host_port, timeout=timeout)


def _get(url: str, path: str) -> tuple[int, bytes]:
    conn = _conn(url)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


def test_index_and_snapshot(dash) -> None:
    _, url, _ = dash
    status, body = _get(url, "/")
    assert status == 200 and b"<html" in body.lower()
    status, body = _get(url, "/api/snapshot")
    assert status == 200
    assert set(json.loads(body)) == set(json.loads(FIXTURE.read_text()))


def test_stream_pushes_new_event(dash) -> None:
    _, url, run = dash
    conn = _conn(url, timeout=8)
    conn.request("GET", "/api/stream")
    resp = conn.getresponse()
    assert resp.status == 200
    assert b"data:" in resp.fp.readline()
    with (run / "events.jsonl").open("a") as fh:
        fh.write(json.dumps({"id": "e2", "kind": "gate", "at": time.time(), "data": {}}) + "\n")
    deadline, seen = time.time() + 6, b""
    while time.time() < deadline and b"e2" not in seen:
        seen += resp.fp.readline()
    conn.close()
    assert b"e2" in seen


@pytest.mark.parametrize(
    "path",
    [
        "/../.team/run/events.jsonl",
        "/%2e%2e/.team/run/events.jsonl",
        "/%2e%2e%2f.team/run/events.jsonl",
        "/static/../../.team/run/events.jsonl",
        "/..%2f..%2f.agile-team.toml",
    ],
)
def test_traversal_is_404(dash, path: str) -> None:
    _, url, _ = dash
    status, body = _get(url, path)
    assert status == 404 and b"sprint-start" not in body


def test_stops_cleanly_on_sigint(dash) -> None:
    proc, _, _ = dash
    proc.send_signal(2)
    assert proc.wait(timeout=10) in (0, -2, 130)
