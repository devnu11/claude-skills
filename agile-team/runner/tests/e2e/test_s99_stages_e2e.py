"""s99 end to end: real shell and clock write runner-stage events; ``tools`` lists both sets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agile_team import cli, gates, live, stages
from agile_team.commands import CommandShell
from agile_team.events import EventKind, EventLog
from agile_team.stage_log import StageLog


def _gate_events(tmp_path: Path) -> list[dict]:
    """Run the implement gate for s99 with real shell commands; return its stage events."""
    events = EventLog(tmp_path / "events.jsonl")
    log = StageLog(events, live.Pulse(tmp_path, 20.0))
    cmds = {"test": "sleep 0.05; exit 0", "coverage": "echo 'TOTAL 100 0 99%'; exit 0"}
    checks = gates.Checks(cmds, 95.0, CommandShell(tmp_path, 20.0).run)
    checks.stages = log.open
    with log.within(stages.Place("s99", "implement")):
        checks.tests_green_and_covered()
    return [
        e.data | {"story": e.story} for e in events.events() if e.kind == EventKind.RUNNER_STAGE
    ]


def test_implement_gate_writes_one_timed_stage_event(tmp_path: Path) -> None:
    """AC3/AC4: one event for the gate, with when, attachment, story, step and awake seconds."""
    rows = _gate_events(tmp_path)
    assert [r["stage"] for r in rows] == ["gate.tests+coverage"]
    row = rows[0]
    assert (row["when"], row["attach"], row["story"], row["step"]) == (
        "after",
        "step",
        "s99",
        "implement",
    )
    assert row["code"] == 0 and row["seconds"] > 0 and row["started_at"] > 0


def test_tools_lists_built_in_and_repo_rows(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """AC2: ``agile-team tools`` prints both lists, the repo's one [[tool]] row among them."""
    (tmp_path / ".agile-team.toml").write_text(
        '[[tool]]\nname = "deploy.preview"\ndescription = "Preview"\ncommand = "echo hi"\n'
    )
    assert cli.main(["--repo", str(tmp_path), "tools"]) == 0
    out = json.loads(capsys.readouterr().out)
    names = [s["name"] for s in out["built_in"]]
    assert names == [str(n) for n in stages.STAGES]
    assert "gate.tests+coverage" in names and "boundary.ci-wait" in names
    assert out["repo"] == [
        {"name": "deploy.preview", "description": "Preview", "command": "echo hi", "label": ""}
    ]


def test_tool_clashing_with_a_built_in_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """AC2: a [[tool]] named like a built-in stage fails the command."""
    (tmp_path / ".agile-team.toml").write_text(
        '[[tool]]\nname = "gate.tests+coverage"\ndescription = "x"\ncommand = "true"\n'
    )
    assert cli.main(["--repo", str(tmp_path), "tools"]) != 0
    assert "clashes with a built-in name" in capsys.readouterr().err
