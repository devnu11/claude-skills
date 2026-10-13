"""s4 end to end: the real ``agile-team dashboard`` process, read over HTTP."""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from agile_team import events as events_mod
from agile_team import gates
from agile_team import state as state_mod

from tests import dashboard_node

from .readiness import RUNNER, STARTUP_S, Launch, Output, dashboard

FIXTURE = Path(events_mod.__file__).parent / "dashboard" / "fixtures" / "snapshot.json"


@pytest.fixture
def dash(configured: Path, tmp_path: Path) -> Iterator[tuple[subprocess.Popen, str, Path]]:
    run = configured / ".team" / "run"
    run.mkdir(parents=True)
    (run / "events.jsonl").write_text(
        json.dumps({"id": "e1", "kind": "sprint-start", "at": time.time(), "data": {}}) + "\n"
    )
    with dashboard(Launch(configured, tmp_path / "scratch-home")) as live_dash:
        yield live_dash.proc, live_dash.url, run


def _conn(url: str, timeout: float = STARTUP_S) -> http.client.HTTPConnection:
    host_port = re.match(r"http://([^/]+)", url).group(1)
    return http.client.HTTPConnection(host_port, timeout=timeout)


def _get(url: str, path: str) -> tuple[int, bytes]:
    conn = _conn(url)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


def _read_until(resp: http.client.HTTPResponse, needle: bytes) -> bytes:
    """Read stream lines until ``needle`` shows or STARTUP_S passes (F6)."""
    deadline, seen = time.monotonic() + STARTUP_S, b""
    while needle not in seen:
        assert time.monotonic() < deadline, f"{needle!r} not on the stream; saw {seen!r}"
        seen += resp.fp.readline()
    return seen


def test_index_and_snapshot(dash) -> None:
    _, url, _ = dash
    status, body = _get(url, "/")
    assert status == 200 and b"<html" in body.lower()
    status, body = _get(url, "/api/snapshot")
    assert status == 200
    assert set(json.loads(body)) == set(json.loads(FIXTURE.read_text()))


def test_stream_pushes_new_event(dash) -> None:
    _, url, run = dash
    conn = _conn(url)
    conn.request("GET", "/api/stream")
    resp = conn.getresponse()
    assert resp.status == 200
    assert b"data:" in resp.fp.readline()
    with (run / "events.jsonl").open("a") as fh:
        fh.write(json.dumps({"id": "e2", "kind": "gate", "at": time.time(), "data": {}}) + "\n")
    seen = _read_until(resp, b"e2")
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


def test_only_outside_urls_are_pinned_libraries(dash) -> None:
    _, url, _ = dash
    urls = set(re.findall(r"https?://[^\s\"'`)<>]+", _index(url)))
    urls -= {"http://www.w3.org/2000/svg"}
    patterns = [
        r"https://cdn\.jsdelivr\.net/npm/mermaid@11\.4\.1/\S+",
        r"https://cdn\.jsdelivr\.net/npm/markdown-it@14\.1\.0/\S+",
    ]
    assert len(urls) == len(patterns)
    for pattern in patterns:
        assert len([u for u in urls if re.fullmatch(pattern, u)]) == 1


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
    conn = _conn(url)
    conn.request("GET", "/api/stream")
    resp = conn.getresponse()
    assert b"data:" in resp.fp.readline()
    old = _budget(url)
    toml.write_text(re.sub(r"budget_usd = [\d.]+", "budget_usd = 4321.0", toml.read_text()))
    seen = _read_until(resp, b"4321")
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

# The quiet limits are the defaults: the step moves its own quiet clock on command (s107 F4),
# so no test waits for real seconds to reach amber or red.
HEALTH_TOML = (
    "\n[health]\nbeat_s = 0.5\nstale_s = {stale}\n"
    "amber_quiet_s = 300\namber_tool_s = 1\nred_quiet_s = 600\n"
)
STEP_SCRIPT = """
import sys, time
from pathlib import Path
from claude_agent_sdk import AssistantMessage, TextBlock
from agile_team import live, system
from agile_team.providers import Billing
run = Path(sys.argv[1])
(run / "runner.pid").write_text(str(__import__("os").getpid()))
pulse = live.Pulse(run, beat_s=0.5)
pulse.start()
meter = pulse.open(live.Who("developer-cli", "s1", "implement", "sonnet", Billing.FREE))
meter.take(AssistantMessage(content=[TextBlock("hi")], model="claude-sonnet-4-5",
    usage={"input_tokens": 3, "output_tokens": 9}, message_id="m1"))
print("ready", flush=True)
for line in sys.stdin:
    meter.reading.wake(system.now() - float(line))
    print(f"quiet {line.strip()}", flush=True)
time.sleep(120)
"""
READY = re.compile(r"^ready$")


def _fake_step(run: Path, status: state_mod.RunStatus) -> tuple[subprocess.Popen, Output]:
    """A real process that meters one turn, beats, and moves its quiet clock on command."""
    state_mod.save(run, state_mod.RunState(status=status))
    proc = subprocess.Popen(
        [sys.executable, "-c", STEP_SCRIPT, str(run)],
        cwd=RUNNER, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
    )  # fmt: skip
    output = Output(proc)
    output.wait_for(READY)
    return proc, output


def _go_quiet(step: tuple[subprocess.Popen, Output], seconds: int) -> None:
    """Tell the fake step it has been quiet for ``seconds``; wait for its ack."""
    step[0].stdin.write(f"{seconds}\n")
    step[0].stdin.flush()
    step[1].wait_for(re.compile(rf"^quiet {seconds}$"))


def _age_heartbeat(run: Path, seconds: float) -> None:
    """Rewrite heartbeat.json atomically with ``at`` and ``mono`` ``seconds`` earlier."""
    path = run / "heartbeat.json"
    beat = json.loads(path.read_text())
    beat["at"] -= seconds
    beat["mono"] -= seconds
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(beat))
    os.replace(tmp, path)


def _set_health(dash, stale: float) -> None:
    toml = _repo_of(dash) / ".agile-team.toml"
    toml.write_text(toml.read_text() + HEALTH_TOML.format(stale=stale))


def _stream_health(
    url: str, done: Callable[[list[tuple[str, str]]], bool]
) -> list[tuple[str, str]]:
    """The distinct (level, reason) seen on /api/stream until ``done(seen)`` (F6)."""
    conn = _conn(url)
    conn.request("GET", "/api/stream")
    resp = conn.getresponse()
    seen: list[tuple[str, str]] = []
    deadline = time.monotonic() + STARTUP_S
    while not done(seen):
        assert time.monotonic() < deadline, f"health never reached the wanted state; saw {seen}"
        line = resp.fp.readline()
        health = json.loads(line[5:]).get("health") if line.startswith(b"data:") else None
        pair = (health["level"], health["reason"]) if health else None
        if pair and pair not in seen:
            seen.append(pair)
    conn.close()
    return seen


def _levels(seen: list[tuple[str, str]]) -> list[str]:
    return [level for level, _ in seen]


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
    _set_health(dash, stale=120)
    fake = _fake_step(dash[2], state_mod.RunStatus.RUNNING)
    step.append(fake[0])
    conn = _conn(dash[1])
    conn.request("GET", "/api/stream")
    resp = conn.getresponse()
    seen: list[tuple[str, str]] = []
    for level, quiet in (("green", None), ("amber", 400), ("red", 700)):
        if quiet:
            _go_quiet(fake, quiet)
        _read_health_until(resp, seen, level)
    conn.close()
    levels = _levels(seen)
    assert levels[0] == "green" and "amber" in levels and levels[-1] == "red", seen
    assert "no turn for" in seen[-1][1]


def _read_health_until(resp, seen: list[tuple[str, str]], level: str) -> None:
    """Add stream samples to ``seen`` until one has ``level``; fail after STARTUP_S."""
    deadline = time.monotonic() + STARTUP_S
    while level not in _levels(seen):
        assert time.monotonic() < deadline, f"never {level}; saw {seen}"
        line = resp.fp.readline()
        health = json.loads(line[5:]).get("health") if line.startswith(b"data:") else None
        pair = (health["level"], health["reason"]) if health else None
        if pair and pair not in seen:
            seen.append(pair)


def test_killed_runner_turns_red_not_running_then_heartbeat_old(dash, step) -> None:
    """s44 AC4: SIGKILL leaves state running; the stream goes red, then names the old heartbeat."""
    _set_health(dash, stale=2)
    proc, _ = _fake_step(dash[2], state_mod.RunStatus.RUNNING)
    step.append(proc)
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)
    seen = _stream_health(
        dash[1], lambda s: any("heartbeat" in reason and "old" in reason for _, reason in s)
    )
    assert seen[0][0] == "red" and "the runner is not running" in seen[0][1], seen
    assert {level for level, _ in seen} == {"red"}
    assert any("heartbeat" in reason and "old" in reason for _, reason in seen), seen


def test_graceful_stop_stays_idle_past_stale(dash, step) -> None:
    """s44 R15: a stopped run with no halt kind is idle, never red, even with a stale heartbeat."""
    _set_health(dash, stale=2)
    proc, _ = _fake_step(dash[2], state_mod.RunStatus.STOPPED)
    step.append(proc)
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)
    _age_heartbeat(dash[2], 62)
    seen = _stream_health(dash[1], bool)
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
    assert out["story"] == {"developer-cli": {"tokens": 20, "cost": 2.0, "seconds": 0}}
    assert out["sprint"] == {
        "developer-cli": {"tokens": 40, "cost": 4.0, "seconds": 0},
        "product-owner": {"tokens": 80, "cost": 8.0, "seconds": 0},
    }
    assert out["run"]["product-owner"] == {"tokens": 90, "cost": 9.0, "seconds": 0}
    assert out["run"]["developer-cli"] == {"tokens": 60, "cost": 6.0, "seconds": 0}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_stopped_pill_is_plain_and_fallback_pill_has_a_space(dash, step) -> None:
    """s74 AC1/AC2: graceful stop is a plain ``● stopped``; fallback pill is ``▶ role``."""
    _set_health(dash, stale=2)
    proc, _ = _fake_step(dash[2], state_mod.RunStatus.STOPPED)
    step.append(proc)
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)
    served = json.loads(_get(dash[1], "/api/snapshot")[1])
    driver = f"""
    const view = {json.dumps(served)};
    const now = view.now ?? Date.now() / 1000;
    const text = pillText(view, now);
    const row = statusPills(view, now).join("");
    const bare = JSON.parse(JSON.stringify(view));
    bare.heartbeat = null;
    bare.turns = [];
    bare.events = [
      {{id: "x", kind: "step-start", role: "developer", story: "s9", at: now - 5, data: {{}}}}];
    console.log(JSON.stringify({{text, row, fallback: pillText(bare, now)}}));
    """
    out = dashboard_node.run_page(driver)
    assert "stopped" in out["text"] and "⚠" not in out["row"]
    assert "h-amber" not in out["row"] and "h-red" not in out["row"]
    assert 'class="pill tone-"><span class="dot"></span>stopped' in out["row"]
    assert out["fallback"].startswith("▶ developer")


def test_cli_prints_local_link_then_other_machines(configured: Path, tmp_path: Path) -> None:
    """s44 AC7: ``dashboard`` prints the localhost link first, then the LAN link."""
    args = ("--host", "0.0.0.0", "--port", "0", "--no-open")
    with dashboard(Launch(configured, tmp_path / "home", args)) as live_dash:
        live_dash.output.wait_for(re.compile(r"^from other machines: "))
        lines = live_dash.output.lines()[:2]
    assert re.fullmatch(r"dashboard: http://localhost:\d+/\?token=\S+\n", lines[0]), lines
    assert re.fullmatch(r"from other machines: http://\S+:\d+/\n", lines[1]), lines
