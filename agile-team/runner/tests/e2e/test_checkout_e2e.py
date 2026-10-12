"""s61 end to end: ``start`` and ``accept-checkout`` against a changed checkout."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from agile_team import cli
from agile_team import state as state_mod
from agile_team.relay import Relay
from agile_team.state import RunStatus

from ..conftest import FakeQuery, git
from ..test_cli import any_tool, start_args
from ..test_s61 import CASES, accept_args, refs, sha7, stored, with_two_commits


@pytest.mark.parametrize("case", sorted(CASES))
def test_each_change_halts_start_before_any_step(
    case: str, configured: Path, key_home: Path, capsys, monkeypatch
) -> None:
    any_tool(monkeypatch)
    with_two_commits(configured)
    run_dir = stored(configured, status=RunStatus.IDLE)
    CASES[case](configured)
    before, query = refs(configured), FakeQuery()
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), query) == 78
    err = capsys.readouterr().err
    assert "checkout changed: expected main at " in err
    assert query.calls == [] and refs(configured) == before
    saved = state_mod.load(run_dir)
    assert saved.status is RunStatus.CHECKOUT_CHANGED
    assert len(Relay(run_dir).open_questions()) == 1
    if case == "rebase":
        assert "with a rebase in progress" in (saved.status_reason or "")


def test_a_merge_conflict_on_the_recorded_branch_halts(
    configured: Path, key_home: Path, monkeypatch
) -> None:
    any_tool(monkeypatch)
    with_two_commits(configured)
    run_dir = stored(configured, status=RunStatus.IDLE)
    git(configured, "checkout", "-q", "-b", "side", "HEAD~1")
    (configured / "src" / "app.py").write_text("x = 9\n")
    git(configured, "commit", "-q", "-am", "side")
    git(configured, "checkout", "-q", "main")
    subprocess.run(["git", "merge", "side"], cwd=configured, capture_output=True, check=False)
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery()) == 78
    assert "with a merge in progress" in (state_mod.load(run_dir).status_reason or "")


def test_accept_then_resume_runs_and_status_shows_the_record(
    configured: Path, key_home: Path, capsys, monkeypatch
) -> None:
    any_tool(monkeypatch)
    run_dir = stored(configured, status=RunStatus.IDLE)
    with_two_commits(configured)
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery()) == 78
    assert cli.main(accept_args(configured, key_home)) == 0
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery()) == 0
    capsys.readouterr()
    assert cli.main(["--repo", str(configured), "status"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["checkout"]["head"] == git(configured, "rev-parse", "HEAD").strip()
    assert sha7(configured) in report["checkout"]["head"]
    assert state_mod.load(run_dir).status is not RunStatus.CHECKOUT_CHANGED
