"""s83 end to end: a real ``dashboard --token`` takes a reorder; the runner applies it."""

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
from agile_team import reorders
from agile_team import state as state_mod

from ..pipeline_helpers import Script, add_story, build
from .test_dashboard_e2e import BOOT, RUNNER

TOKEN = "e2e-token"


def _url(proc: subprocess.Popen) -> str:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if select.select([proc.stdout], [], [], 0.5)[0]:
            match = re.search(r"dashboard: (http://\S+)", proc.stdout.readline())
            if match:
                return match.group(1)
        assert proc.poll() is None, "dashboard exited early"
    raise AssertionError("no dashboard URL printed")


@pytest.fixture
def served(make_runtime, configured: Path, tmp_path: Path) -> Iterator[tuple]:
    """A seeded runtime and a real dashboard process on the same repo."""
    rt = build(make_runtime, Script(), steps=["design", "review"])
    add_story(rt, "s1")
    for sid in ("b1", "b2", "b3"):
        add_story(rt, sid, sprint=0)
    rt.state.order = ["s1", "b1", "b2", "b3"]
    state_mod.save(rt.config.run_dir, rt.state)
    stories = rt.config.stories_dir
    stories.mkdir(parents=True, exist_ok=True)
    (stories / "b1.md").write_text("# b1 story\n")
    (configured / "secret.md").write_text("do not serve\n")
    env = {**os.environ, "AGILE_TEAM_HOME": str(tmp_path / "home")}
    cmd = [sys.executable, "-c", BOOT, "--repo", str(configured), "dashboard"]
    cmd += ["--host", "127.0.0.1", "--port", "0", "--no-open", "--token", TOKEN]
    proc = subprocess.Popen(
        cmd, cwd=RUNNER, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    try:
        yield rt, _url(proc), proc
    finally:
        proc.kill()
        proc.wait(timeout=10)


def _call(url: str, method: str, path: str, body: bytes = b"", token: str | None = None) -> tuple:
    conn = http.client.HTTPConnection(re.match(r"http://([^/]+)", url).group(1), timeout=10)
    headers = {"X-Agile-Team-Token": token} if token is not None else {}
    conn.request(method, path, body=body or None, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def _snapshot(url: str) -> dict:
    return json.loads(_call(url, "GET", "/api/snapshot")[1])


def _ask(url: str, story: str, position: int) -> bytes:
    version = _snapshot(url)["run"]["order_version"]
    return json.dumps({"story": story, "position": position, "version": version}).encode()


def test_url_carries_the_token(served) -> None:
    """AC7: the printed local URL has the token; the snapshot does not."""
    _, url, _ = served
    assert url.endswith(f"/?token={TOKEN}")
    assert TOKEN not in _call(url, "GET", "/api/snapshot")[1].decode()


def test_snapshot_lists_groups_and_labels(served) -> None:
    """AC1: the queue in ranking order, split into sprint and backlog."""
    _, url, _ = served
    run = _snapshot(url)["run"]
    assert run["order"] == ["s1", "b1", "b2", "b3"]
    assert run["backlog"] == ["b1", "b2", "b3"]


def test_file_route_serves_by_id_and_refuses_the_rest(served) -> None:
    """AC3: only story files by id; anything else is 404."""
    _, url, _ = served
    status, body = _call(url, "GET", "/api/file?kind=story&id=b1")
    assert (status, body) == (200, b"# b1 story\n")
    for query in (
        "kind=story&id=../secret",
        "kind=story&id=/etc/passwd",
        "kind=story&id=nope",
        "kind=secrets&id=b1",
        "kind=design&id=b1",
        "id=b1",
    ):
        assert _call(url, "GET", f"/api/file?{query}")[0] == 404, query


def test_write_gate_wants_the_token(served) -> None:
    """AC7: no token or a wrong one is 403 and writes nothing."""
    rt, url, _ = served
    body = _ask(url, "b3", 1)
    for token in (None, "", "wrong"):
        assert _call(url, "POST", "/api/reorder", body, token)[0] == 403
    assert not list((rt.config.run_dir / "reorders").glob("r*.json"))
    assert _call(url, "POST", "/api/reorder", b"{}", TOKEN)[0] == 400
    assert _call(url, "POST", "/api/other", body, TOKEN)[0] == 404


def test_queued_request_is_applied_by_the_runner(served) -> None:
    """AC4-AC6: 202, a request file, then the desk reorders and logs a human event."""
    rt, url, _ = served
    status, data = _call(url, "POST", "/api/reorder", _ask(url, "b3", 1), TOKEN)
    assert status == 202 and json.loads(data) == {"id": "r1", "status": "queued"}
    assert (rt.config.run_dir / "reorders" / "r1.json").is_file()
    assert _snapshot(url)["reorders"][-1]["status"] == "pending"
    rt.state = state_mod.load(rt.config.run_dir)
    reorders.Desk(rt).apply()
    assert rt.state.reorders == {"r1": reorders.APPLIED}
    assert rt.state.order[:1] == ["s1"] and rt.state.order.index("b3") < rt.state.order.index("b1")
    event = [e for e in rt.events.events() if e.kind == "priority"][-1]
    assert event.data["source"] == "human (dashboard)" and event.role is None
    assert _snapshot(url)["reorders"][-1]["status"] == "applied"
    assert TOKEN not in (rt.config.run_dir / "events.jsonl").read_text()


def test_sprint_story_and_stale_requests_are_refused(served) -> None:
    """AC4/AC5: a sprint story and an old order version are refused, order unchanged."""
    rt, url, _ = served
    _call(url, "POST", "/api/reorder", _ask(url, "s1", 1), TOKEN)
    stale = json.dumps({"story": "b3", "position": 1, "version": "000000000000"}).encode()
    _call(url, "POST", "/api/reorder", stale, TOKEN)
    rt.state = state_mod.load(rt.config.run_dir)
    before = list(rt.state.order)
    reorders.Desk(rt).apply()
    assert rt.state.reorders["r2"].startswith("the order changed")
    assert "current sprint" in rt.state.reorders["r1"]
    assert rt.state.order == before
