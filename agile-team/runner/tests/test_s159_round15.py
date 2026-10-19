"""s159 round 15 (D3): limit status tone, role text, replay fix brief."""

from __future__ import annotations

from pathlib import Path

import pytest
from agile_team import boundary as b
from agile_team import health, system
from agile_team.health import Level
from agile_team.state import RunStatus

from .test_s78_health import beat, verdict

PKG = Path(b.__file__).parent


def test_a_run_stopped_by_a_limit_is_red_and_halted() -> None:
    result = verdict(beat(), status=RunStatus.LIMIT)
    assert result.level is Level.RED
    assert result.reason.startswith("halted:")
    assert RunStatus.LIMIT in health.HALTED


def test_the_page_tones_the_limit_status_as_a_warning() -> None:
    html = system.read_text(PKG / "dashboard" / "index.html")
    assert 'limit: "warning"' in html


@pytest.mark.parametrize("phrase", ["proves they fail", "fail for the right reason"])
def test_the_unit_tester_role_does_not_ask_for_a_red_proof(phrase: str) -> None:
    assert phrase not in system.read_text(PKG / "roles" / "unit-tester.md")


def replay_brief(story: str, commit: str = "abc123") -> str:
    failure = b.Failure(
        stage=b.Stage.REPLAY,
        case=b.FixCase.REBASE_CONFLICT,
        reason="CONFLICT in a.py",
        branch="replay-1",
        files=["a.py"],
        commit=commit,
        subject="add a",
        worktree="/wt",
        story=story,
    )
    bd = b.Boundary(b.Edge.END, 2, stage=b.Stage.REPLAY)
    bd.failure = failure
    return b.fix_brief(bd, b.FixContext(team="team-br", target="origin/main", sha="s"))


def test_a_story_replay_stop_names_story_commit_and_target() -> None:
    brief = replay_brief("s12")
    assert "(story s12) with conflicts in: a.py" in brief
    assert 'abc123 "add a"' in brief
    assert "origin/main" in brief


def test_a_plain_commit_replay_stop_has_no_story_text_or_gap() -> None:
    brief = replay_brief("")
    assert "(story" not in brief
    assert "  " not in brief.split("\n\n")[1]
    assert '"add a" with conflicts in: a.py' in brief


def plain_failure(*, replay: bool) -> b.Failure:
    return b.Failure(
        stage=b.Stage.REPLAY,
        case=b.FixCase.REBASE_CONFLICT,
        reason="x",
        plain_rebase=not replay,
    )


def test_a_plain_rebase_conflict_gets_the_ordinary_fix_lines() -> None:
    lines = b._fix_lines(plain_failure(replay=False))
    assert lines == b.FIX_LINES[b.FixCase.REBASE_CONFLICT]
    assert lines != b.REPLAY_FIX_LINES


def test_a_replay_stop_gets_the_replay_fix_lines() -> None:
    assert b._fix_lines(plain_failure(replay=True)) == b.REPLAY_FIX_LINES


def test_a_failure_without_the_plain_rebase_key_loads_as_a_replay_stop() -> None:
    data = {"stage": "replay", "case": "rebase_conflict", "reason": "x"}
    assert b.Failure(**data).plain_rebase is False


@pytest.mark.parametrize("story", ["s12", ""])
def test_a_replay_stop_is_not_aborted_and_names_the_continue_commands(story: str) -> None:
    brief = replay_brief(story)
    assert "aborted" not in brief.replace("not aborted", "")
    assert "cherry-pick --continue" in brief
    assert "CHERRY_PICK_HEAD" in brief
