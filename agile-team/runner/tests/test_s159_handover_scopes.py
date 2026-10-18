"""s159 H1/H2: hand-over scopes and merged passes; new triggers; the new texts."""

from __future__ import annotations

import pytest
from agile_team import handover
from agile_team.handover import Pass, Trigger

RUN = [
    "ERROR",
    "BOUNDARY_ERROR",
    "BOUNDARY_ESCALATED",
    "SYNC_CONFLICT",
    "REBASE_CONFLICT",
    "PUSH_REJECTED",
    "CI_FAILED",
    "MAIN_BROKEN",
    "CI_GREEN",
    "SPRINT_END",
    "NEXT_SPRINT",
    "STALLED",
    "SPRINT_BACKLOG_STUCK",
]
STORY = [
    "STORY_CI_RED",
    "WORKTREE_DRIFT",
    "LAND_BOUNCED",
    "CI_INFRA",
    "CI_PENDING",
    "PUSH_PERMISSION",
    "KNOWN_FAILURES",
    "HUMAN_MESSAGE",
]


def test_new_trigger_values() -> None:
    """s159 spec, red: new trigger values (s159 red)."""
    assert Trigger.STORY_CI_RED.value == "story_ci_red"
    assert Trigger.WORKTREE_DRIFT.value == "worktree_drift"
    assert Trigger.LAND_BOUNCED.value == "land_bounced"


@pytest.mark.parametrize("name", RUN)
def test_run_scoped(name: str) -> None:
    """s159 spec, red: run scoped (s159 red)."""
    assert handover.SCOPES[Trigger[name]] is handover.Scope.RUN


@pytest.mark.parametrize("name", STORY)
def test_story_scoped(name: str) -> None:
    """s159 spec, red: story scoped (s159 red)."""
    assert handover.SCOPES[Trigger[name]] is handover.Scope.STORY


def test_every_trigger_has_a_scope() -> None:
    """s159 spec, red: every trigger has a scope (s159 red)."""
    assert set(handover.SCOPES) == set(Trigger)
    handover.check_scopes()


def test_check_scopes_names_a_missing_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    """s159 spec, red: check scopes names a missing trigger (s159 red)."""
    table = dict(handover.SCOPES)
    del table[Trigger.STALLED]
    monkeypatch.setattr(handover, "SCOPES", table)
    with pytest.raises(handover.ScopeTableError, match=r"stalled|STALLED"):
        handover.check_scopes()


def test_merge_joins_kinds_lines_and_stories_in_order() -> None:
    """s159 spec, red: merge joins kinds lines and stories in order (s159 red)."""
    a = Pass([Trigger.STORY_CI_RED], ["one"], ["s1"])
    b = Pass([Trigger.LAND_BOUNCED, Trigger.STORY_CI_RED], ["two"], ["s2", "s1"])
    got = handover.merge([a, b])
    assert got.lines == ["one", "two"]
    assert got.kinds[0] is Trigger.STORY_CI_RED and Trigger.LAND_BOUNCED in got.kinds
    assert got.stories[:2] == ["s1", "s2"]


def test_merge_of_one_is_that_pass() -> None:
    """s159 spec, red: merge of one is that pass (s159 red)."""
    a = Pass([Trigger.WORKTREE_DRIFT], ["x"], ["s1"])
    got = handover.merge([a])
    assert (got.kinds, got.lines, got.stories) == (a.kinds, a.lines, a.stories)


def test_ci_green_text_gives_the_ff_command_not_rebase_and_merge() -> None:
    """s159 spec, red: ci green text gives the ff command not rebase and merge (s159 red)."""
    row = handover.HANDOVERS[Trigger.CI_GREEN]
    text = repr(row)
    assert "Rebase and merge" not in text
