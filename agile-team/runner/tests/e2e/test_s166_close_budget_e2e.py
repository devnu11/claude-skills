"""s166 end to end: a real ``gh`` stub on PATH behind ``GhPrs.close``; the budget check."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from agile_team import upstream as up
from agile_team.boundary import StepKind
from agile_team.gates import StoryState
from agile_team.router import Work

from ..late import Late

sched = Late("scheduler")
STUB = """#!/bin/sh
echo "$@" >> "$GH_LOG"
case "$2" in
  close) echo "$GH_CLOSE_MSG" >&2; exit "$GH_CLOSE_CODE";;
  view) echo "{\\"state\\": \\"$GH_STATE\\"}"; exit 0;;
esac
"""


def gh_on_path(tmp_path: Path, monkeypatch, close: tuple[int, str], state: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(STUB)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "gh.log"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GH_LOG", str(log))
    monkeypatch.setenv("GH_CLOSE_CODE", str(close[0]))
    monkeypatch.setenv("GH_CLOSE_MSG", close[1])
    monkeypatch.setenv("GH_STATE", state)
    return log


def test_ac1_a_merged_story_pr_closes_without_error(tmp_path, monkeypatch) -> None:
    log = gh_on_path(tmp_path, monkeypatch, (1, "already merged"), "MERGED")
    up.GhPrs(up.command_runner(tmp_path)).close(40, "landed")
    assert log.read_text().count("pr close") == 1 and "pr view" in log.read_text()


def test_ac1_any_other_failure_is_still_reported(tmp_path, monkeypatch) -> None:
    gh_on_path(tmp_path, monkeypatch, (1, "boom"), "OPEN")
    with pytest.raises(up.UpstreamError, match="boom"):
        up.GhPrs(up.command_runner(tmp_path)).close(40, "landed")


def test_ac1_an_open_pr_closes_with_the_note_and_no_view(tmp_path, monkeypatch) -> None:
    log = gh_on_path(tmp_path, monkeypatch, (0, ""), "OPEN")
    up.GhPrs(up.command_runner(tmp_path)).close(40, "landed")
    assert "--comment landed" in log.read_text() and "pr view" not in log.read_text()


def test_ac2_a_running_landing_does_not_halt_the_budget_check(make_runtime) -> None:
    rt = make_runtime()
    rt.state.sprint = 1
    s = sched.Scheduler(rt, None)
    a = StoryState(id="s1", title="T", step="implement", sprint=1)
    b = StoryState(id="s2", title="T", step="implement", sprint=1)
    s.running["s1"] = Work("runner", a, "", StepKind.LAND)
    assert s.check_budget(Work("developer-cli", b, "brief")) is None
