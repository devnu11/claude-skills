"""s78 end to end: `agile-team watch` and the dashboard judge late beats, sleep and death."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from agile_team import events as events_mod
from agile_team import state as state_mod

from .. import clock
from .readiness import Output, wait_until
from .test_dashboard_e2e import _get, dash  # noqa: F401
from .test_liaison_e2e import run_cli

RUNNER = Path(events_mod.__file__).parent.parent

PULSE_SCRIPT = """
import sys, time
from pathlib import Path
from agile_team import live
run = Path(sys.argv[1])
pulse = live.Pulse(run, beat_s=0.2)
pulse.start()
with pulse.doing("gate: implement on s71"):
    print("ready", flush=True)
    time.sleep(60)
"""


@pytest.fixture
def run_dir(configured: Path) -> Path:
    """The scratch run dir with a running state."""
    run = configured / ".team" / "run"
    run.mkdir(parents=True)
    state_mod.save(run, state_mod.RunState(status=state_mod.RunStatus.RUNNING))
    return run


@pytest.fixture
def alive() -> Iterator[int]:
    """The pid of a live process."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    yield proc.pid
    proc.kill()
    proc.wait(timeout=10)


def _beat(run: Path, pid: int, age: float, slept: float = 0.0, **extra) -> None:
    """A version-2 heartbeat ``age`` seconds old; the machine slept ``slept`` of them."""
    (run / "runner.pid").write_text(str(pid))
    now = clock.real_now()
    mono = clock.real_monotonic() - (age - slept)
    beat = {"version": 2, "pid": pid, "beat": "beating", "at": now - age, "mono": mono}
    beat |= {"started_at": now - 1000, "chore": None, "step": None} | extra
    (run / "heartbeat.json").write_text(json.dumps(beat))


def _tool(age: float) -> dict:
    now = clock.real_now()
    return {
        "role": "reviewer", "story": "s71", "step": "review", "started_at": now - 900,
        "turn": 5, "model": "m", "configured_model": "m", "last_turn_at": now - age,
        "quiet_since": now - age, "tool": {"name": "Bash", "started_at": now - age},
        "tokens": {}, "cost_usd": 0.0,
    }  # fmt: skip


def _health(repo: Path) -> dict:
    out = run_cli(repo, "watch", "--timeout", "1")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)["health"]


def test_late_beat_with_open_tool_is_amber_not_red(configured: Path, run_dir: Path, alive: int):
    """AC1/AC3: a 4 min late beat while a tool runs is amber and says so."""
    _beat(run_dir, alive, 240, step=_tool(240))
    health = _health(configured)
    assert health["level"] == "amber", health
    assert "heartbeat 4 min old while Bash runs" in health["reason"]


def test_late_beat_during_a_gate_is_amber_naming_the_gate(configured, run_dir, alive):
    """AC2: a gate chore with a 100 s late beat is amber, reason names the gate."""
    chore = {"what": "gate: implement on s71", "since": clock.real_now() - 100}
    _beat(run_dir, alive, 100, chore=chore)
    health = _health(configured)
    assert health["level"] == "amber", health
    assert "while runner: gate: implement on s71" in health["reason"]


def _chore_beat(run_dir: Path) -> bool:
    """Whether heartbeat.json names the gate chore (False when missing or torn)."""
    try:
        beat = json.loads((run_dir / "heartbeat.json").read_text())
    except (OSError, ValueError):
        return False
    return (beat.get("chore") or {}).get("what") == "gate: implement on s71"


def test_real_pulse_in_a_gate_reads_green(configured: Path, run_dir: Path):
    """AC2: a real process beating inside a gate chore reads green, runner: gate."""
    proc = subprocess.Popen(
        [sys.executable, "-c", PULSE_SCRIPT, str(run_dir)],
        cwd=RUNNER, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )  # fmt: skip
    try:
        Output(proc).wait_for(re.compile(r"^ready$"))
        (run_dir / "runner.pid").write_text(str(proc.pid))
        wait_until(lambda: _chore_beat(run_dir), "the gate chore in heartbeat.json")
        health = _health(configured)
    finally:
        proc.kill()
        proc.wait(timeout=10)
    assert health["level"] == "green", health
    assert "runner: gate: implement on s71" in health["reason"]


def test_sleep_stays_red(configured: Path, run_dir: Path, alive: int):
    """AC3: a beat 660 s old, 650 s of it asleep, is red as a sleep, with a tool open."""
    _beat(run_dir, alive, 660, slept=650, step=_tool(30))
    health = _health(configured)
    assert health["level"] == "red", health
    assert "the machine slept for" in health["reason"] and "heartbeat" not in health["reason"]


def test_dead_runner_stays_red(configured: Path, run_dir: Path):
    """AC3: the beat is excused-looking but the pid is gone: red, not running."""
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait(timeout=10)
    _beat(run_dir, dead.pid, 100, chore={"what": "gate: x on s1", "since": clock.real_now() - 100})
    health = _health(configured)
    assert health["level"] == "red" and "the runner is not running" in health["reason"]


def test_idle_stale_beat_is_red(configured: Path, run_dir: Path, alive: int):
    """AC3: late beat with no tool or chore is still red."""
    _beat(run_dir, alive, 120)
    health = _health(configured)
    assert health["level"] == "red" and "heartbeat 2 min old" in health["reason"]


def test_dashboard_snapshot_agrees_with_watch(dash, configured: Path, alive: int):  # noqa: F811
    """AC4: the dashboard snapshot and watch give one verdict for one run."""
    run = dash[2]
    state_mod.save(run, state_mod.RunState(status=state_mod.RunStatus.RUNNING))
    _beat(run, alive, 240, step=_tool(240))
    watched = _health(configured)
    status, body = _get(dash[1], "/api/snapshot")
    shown = json.loads(body)["health"]
    assert status == 200 and watched["level"] == "amber"
    assert shown["level"] == watched["level"]
    assert "heartbeat 4 min old while Bash runs" in shown["reason"]
