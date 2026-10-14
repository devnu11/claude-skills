"""s123 end to end: a devops fix's handover is no boundary hold; a bad stored hold is dropped."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agile_team import boundary as bd
from agile_team import cli, system
from agile_team import state as state_mod
from agile_team.boundary import BoundaryHold, Edge, Stage
from agile_team.boundary_runner import BoundaryRunner
from agile_team.events import EventKind

from ..conftest import FakeQuery
from ..test_cli import start_args

BAD = "stopped, questions"
BLOCKED = {"role": "devops", "status": "blocked", "open_questions": ["which linter?"]}


def poison(run_dir: Path) -> None:
    """Write the state the sprint-42 bug left behind: trigger text as the boundary hold."""
    data = json.loads((run_dir / "state.json").read_text())
    data["boundary"] = {"edge": "end", "sprint": 1, "hold": BAD}
    (run_dir / "state.json").write_text(json.dumps(data))


def cli_json(repo: Path, capsys, *args: str) -> dict:
    assert cli.main(["--repo", str(repo), *args]) == 0
    return json.loads(capsys.readouterr().out)


def test_ac1_ac3_fix_with_handover_leaves_a_valid_hold_that_loads(
    make_runtime, configured: Path, capsys
) -> None:
    rt = make_runtime()
    rt.state.sprint = 1
    rt.state.boundary = bd.Boundary(Edge.START, 1, stage=Stage.CHECK)
    BoundaryRunner(rt).after_fix(BLOCKED)
    assert rt.state.boundary.hold is BoundaryHold.FIX_HANDOVER
    loaded = state_mod.load(rt.config.run_dir)
    assert loaded.boundary.hold is BoundaryHold.FIX_HANDOVER and not loaded.load_faults
    report = cli_json(configured, capsys, "status")
    assert report["boundary"]["hold"] == "fix_handover"


def test_ac2_bad_hold_loads_status_and_watch_work_and_start_reports_one_fault(
    make_runtime, configured: Path, key_home: Path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(system, "which", lambda name: f"/bin/{name}")
    run_dir = make_runtime().config.run_dir
    state_mod.save(run_dir, state_mod.RunState(status=state_mod.RunStatus.IDLE))
    poison(run_dir)
    assert cli_json(configured, capsys, "status")["boundary"]["hold"] is None
    assert cli.main(["--repo", str(configured), "watch", "--timeout", "0"]) == 0
    capsys.readouterr()
    events = run_dir / "events.jsonl"
    assert not events.exists() or BAD not in events.read_text()
    cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery())
    faults = [
        json.loads(line)
        for line in events.read_text().splitlines()
        if json.loads(line)["kind"] == EventKind.FAULT
    ]
    named = [f for f in faults if f["data"].get("value") == BAD]
    assert len(named) == 1 and named[0]["data"]["field"] == "boundary.hold"
    assert state_mod.load(run_dir).load_faults == []


def test_boundary_in_code_stays_strict() -> None:
    with pytest.raises(ValueError):
        bd.Boundary(Edge.END, 1, hold="bogus")
