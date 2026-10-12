"""s4 end to end: the real ``agile-team dashboard`` process, read over HTTP."""

from __future__ import annotations

import http.client
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from agile_team import events as events_mod
from agile_team import gates
from agile_team import state as state_mod

from tests import dashboard_node

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


def _index(url: str) -> str:
    status, body = _get(url, "/")
    assert status == 200
    return body.decode()


def test_index_is_packaged_file_with_five_tabs(dash) -> None:
    _, url, _ = dash
    shipped = (Path(events_mod.__file__).parent / "dashboard" / "index.html").read_text()
    page = _index(url)
    assert page == shipped
    for tab in ("flow", "board", "tokens", "questions", "requirements"):
        assert f'id="tab-{tab}"' in page
        assert re.search(rf'\[\s*"{tab}"\s*,', page)


def test_api_urls_are_relative_and_resolve(dash) -> None:
    _, url, _ = dash
    page = _index(url)
    for path in ("api/snapshot", "api/stream"):
        assert f'"{path}"' in page
        assert f'"/{path}"' not in page
    assert _get(url, "/api/snapshot")[0] == 200
    conn = _conn(url)
    conn.request("GET", "/api/stream")
    resp = conn.getresponse()
    assert resp.status == 200 and "text/event-stream" in resp.getheader("Content-Type")
    conn.close()


def test_only_outside_url_is_pinned_mermaid(dash) -> None:
    _, url, _ = dash
    urls = set(re.findall(r"https?://[^\s\"'`)<>]+", _index(url)))
    urls -= {"http://www.w3.org/2000/svg"}
    assert len(urls) == 1
    (only,) = urls
    assert re.fullmatch(r"https://cdn\.jsdelivr\.net/npm/mermaid@\d+\.\d+\.\d+/\S+", only)


def test_event_edge_covers_flow_kinds(dash) -> None:
    _, url, _ = dash
    block = re.search(r"const EVENT_EDGE = \{(.*?)\n\};", _index(url), re.S).group(1)
    keys = set(re.findall(r'^\s*"?([\w-]+)"?:', block, re.M))
    assert {"step-start", "step-end", "message", "answer"} <= keys


def _budget(url: str) -> float:
    return json.loads(_get(url, "/api/snapshot")[1])["run"]["budget_usd"]


def test_budget_follows_config_file_and_pushes(dash) -> None:
    """s21 AC2: editing .agile-team.toml changes the snapshot and triggers an SSE push."""
    _, url, _ = dash
    toml = Path(_repo_of(dash)) / ".agile-team.toml"
    conn = _conn(url, timeout=8)
    conn.request("GET", "/api/stream")
    resp = conn.getresponse()
    assert b"data:" in resp.fp.readline()
    old = _budget(url)
    toml.write_text(re.sub(r"budget_usd = [\d.]+", "budget_usd = 4321.0", toml.read_text()))
    deadline, seen = time.time() + 6, b""
    while time.time() < deadline and b"4321" not in seen:
        seen += resp.fp.readline()
    conn.close()
    assert b"4321" in seen
    assert _budget(url) == 4321.0 != old


def _repo_of(dash) -> Path:
    return dash[2].parent.parent


def test_index_toggle_only_on_tokens_chart_and_board_fits(dash) -> None:
    """s21 AC1/AC3: one unit toggle, and the board columns shrink instead of scrolling."""
    html = _index(dash[1])
    assert html.count('id="unit"') == 1 and html.count("data-unit") >= 1
    assert "ui.unit" in html
    board = re.search(r"\.col \{([^}]*)\}", html).group(1)
    assert "flex: 1 1 0" in board and "min-width: 0" in board
    assert "overflow-x" not in re.search(r"\.board \{([^}]*)\}", html).group(1)


# ----- s44: live meter and runner health ---------------------------------------

HEALTH_TOML = (
    "\n[health]\nbeat_s = 0.5\nstale_s = {stale}\n"
    "amber_quiet_s = 2\namber_tool_s = 1\nred_quiet_s = 4\n"
)
STEP_SCRIPT = """
import sys, time
from pathlib import Path
from claude_agent_sdk import AssistantMessage, TextBlock
from agile_team import live
from agile_team.providers import Billing
run = Path(sys.argv[1])
(run / "runner.pid").write_text(str(__import__("os").getpid()))
pulse = live.Pulse(run, beat_s=0.5)
pulse.start()
meter = pulse.open(live.Who("developer-cli", "s1", "implement", "sonnet", Billing.FREE))
meter.take(AssistantMessage(content=[TextBlock("hi")], model="claude-sonnet-4-5",
    usage={"input_tokens": 3, "output_tokens": 9}, message_id="m1"))
print("ready", flush=True)
time.sleep(120)
"""


def _fake_step(run: Path, status: state_mod.RunStatus) -> subprocess.Popen:
    """A real process that meters one turn, beats, and then goes silent."""
    state_mod.save(run, state_mod.RunState(status=status))
    proc = subprocess.Popen(
        [sys.executable, "-c", STEP_SCRIPT, str(run)],
        cwd=RUNNER, stdout=subprocess.PIPE, text=True,
    )  # fmt: skip
    assert proc.stdout.readline().strip() == "ready"
    return proc


def _set_health(dash, stale: float) -> None:
    toml = _repo_of(dash) / ".agile-team.toml"
    toml.write_text(toml.read_text() + HEALTH_TOML.format(stale=stale))


def _stream_health(url: str, seconds: float) -> list[tuple[str, str]]:
    """The distinct (level, reason-words) seen on /api/stream within ``seconds``."""
    conn = _conn(url, timeout=2)
    conn.request("GET", "/api/stream")
    resp = conn.getresponse()
    seen: list[tuple[str, str]] = []
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            line = resp.fp.readline()
        except TimeoutError:
            continue
        if line.startswith(b"data:"):
            health = json.loads(line[5:]).get("health")
            pair = (health["level"], health["reason"]) if health else None
            if pair and pair not in seen:
                seen.append(pair)
    conn.close()
    return seen


@pytest.fixture
def step(dash):
    """Start/stop bookkeeping for a fake step process."""
    procs: list[subprocess.Popen] = []
    yield procs
    for proc in procs:
        proc.kill()
        proc.wait(timeout=10)


def test_health_goes_green_amber_red_as_the_step_goes_quiet(dash, step) -> None:
    """s44 AC4: a silent live step turns the stream amber, then red (no turn for ...)."""
    _set_health(dash, stale=30)
    step.append(_fake_step(dash[2], state_mod.RunStatus.RUNNING))
    seen = _stream_health(dash[1], 9)
    levels = [level for level, _ in seen]
    assert levels[0] == "green" and "amber" in levels and levels[-1] == "red", seen
    assert "no turn for" in seen[-1][1]


def test_killed_runner_turns_red_not_running_then_heartbeat_old(dash, step) -> None:
    """s44 AC4: SIGKILL leaves state running; the stream goes red, then names the old heartbeat."""
    _set_health(dash, stale=2)
    proc = _fake_step(dash[2], state_mod.RunStatus.RUNNING)
    step.append(proc)
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)
    seen = _stream_health(dash[1], 6)
    assert seen[0][0] == "red" and "the runner is not running" in seen[0][1], seen
    assert {level for level, _ in seen} == {"red"}
    assert any("heartbeat" in reason and "old" in reason for _, reason in seen), seen


def test_graceful_stop_stays_idle_past_stale(dash, step) -> None:
    """s44 R15: a stopped run with no halt kind is idle, never red, even with a stale heartbeat."""
    _set_health(dash, stale=2)
    proc = _fake_step(dash[2], state_mod.RunStatus.STOPPED)
    step.append(proc)
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)
    seen = _stream_health(dash[1], 5)
    assert seen and {level for level, _ in seen} == {"idle"}, seen
    assert not any("heartbeat" in reason for _, reason in seen)
    assert "stopped" in seen[0][1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_scope_toggle_totals_match_the_ledger(dash) -> None:
    """s44 AC9: the page's scopeTotals over the served snapshot match the ledger per scope."""
    run = dash[2]
    state = state_mod.RunState(sprint=2)
    state.stories = {
        "s1": gates.StoryState("s1", "one", "implement", sprint=1),
        "s2": gates.StoryState("s2", "two", "implement", sprint=2),
    }
    state_mod.save(run, state)
    base = time.time()  # recent, so no PO running-total correction applies
    starts = [
        {"id": f"e{n}", "kind": "sprint-start", "at": base + 100.0 * n, "data": {"sprint": n}}
        for n in (1, 2)
    ]
    (run / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in starts))
    rows = [
        ("product-owner", None, 150.0, 1.0, 10),
        ("developer-cli", "s1", 160.0, 2.0, 20),
        ("developer-cli", "s2", 250.0, 4.0, 40),
        ("product-owner", None, 260.0, 8.0, 80),
    ]
    (run / "ledger.jsonl").write_text(
        "".join(
            json.dumps({"role": r, "model": "sonnet", "story": s, "at": at, "cost_usd": c,
                        "tokens": {"input": 0, "output": t, "cache_read": 0, "cache_creation": 0}})
            + "\n"
            for r, s, at, c, t in ((r, s, base + at, c, t) for r, s, at, c, t in rows)
        )
    )  # fmt: skip
    served = json.loads(_get(dash[1], "/api/snapshot")[1])
    driver = f"""
    const view = {json.dumps(served)};
    const out = {{}};
    for (const [scope, focus] of [["story", "s1"], ["sprint", "s2"], ["run", ""]]) {{
      ui.scope = scope; ui.focus = focus; out[scope] = scopeTotals(view);
    }}
    console.log(JSON.stringify(out));
    """
    out = dashboard_node.run_page(driver)
    assert out["story"] == {"developer-cli": {"tokens": 20, "cost": 2.0}}
    assert out["sprint"] == {
        "developer-cli": {"tokens": 40, "cost": 4.0},
        "product-owner": {"tokens": 80, "cost": 8.0},
    }
    assert out["run"]["product-owner"] == {"tokens": 90, "cost": 9.0}
    assert out["run"]["developer-cli"] == {"tokens": 60, "cost": 6.0}


def test_cli_prints_local_link_then_other_machines(configured: Path, tmp_path: Path) -> None:
    """s44 AC7: ``dashboard`` prints the localhost link first, then the LAN link."""
    env = {**os.environ, "AGILE_TEAM_HOME": str(tmp_path / "home")}
    cmd = [sys.executable, "-c", BOOT, "--repo", str(configured), "dashboard", "--host", "0.0.0.0"]
    cmd += ["--port", "0", "--no-open"]  # fmt: skip
    proc = subprocess.Popen(
        cmd, cwd=RUNNER, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    try:
        lines = [proc.stdout.readline(), proc.stdout.readline()]
    finally:
        proc.kill()
        proc.wait(timeout=10)
    assert re.fullmatch(r"dashboard: http://localhost:\d+/\n", lines[0]), lines
    assert re.fullmatch(r"from other machines: http://\S+:\d+/\n", lines[1]), lines
