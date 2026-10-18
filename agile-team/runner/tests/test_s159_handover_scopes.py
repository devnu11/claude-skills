"""s159 H1/H2/C5: every trigger has a scope; passes merge for one PO turn."""

import pytest
from agile_team import handover as ho


def test_every_trigger_has_a_scope_r1() -> None:
    assert set(ho.SCOPES) == set(ho.Trigger)
    ho.check_scopes()


def test_a_missing_trigger_fails_naming_it_r1(monkeypatch: pytest.MonkeyPatch) -> None:
    table = dict(ho.SCOPES)
    del table[ho.Trigger.STALLED]
    monkeypatch.setattr(ho, "SCOPES", table)
    with pytest.raises(ho.ScopeTableError, match="stalled"):
        ho.check_scopes()


RUN_WIDE = [
    "ERROR", "BOUNDARY_ERROR", "BOUNDARY_ESCALATED", "SYNC_CONFLICT", "REBASE_CONFLICT",
    "PUSH_REJECTED", "CI_FAILED", "MAIN_BROKEN", "CI_GREEN", "SPRINT_END", "NEXT_SPRINT",
    "STALLED", "SPRINT_BACKLOG_STUCK",
]  # fmt: skip


@pytest.mark.parametrize("name", RUN_WIDE)
def test_run_wide_triggers_r1(name: str) -> None:
    assert ho.SCOPES[ho.Trigger[name]] is ho.Scope.RUN


def test_everything_else_is_per_story_r1() -> None:
    per_story = {t for t, s in ho.SCOPES.items() if s is ho.Scope.STORY}
    assert per_story == set(ho.Trigger) - {ho.Trigger[n] for n in RUN_WIDE}
    for name in ["STORY_CI_RED", "WORKTREE_DRIFT", "LAND_BOUNCED", "CI_INFRA", "CI_PENDING",
                 "PUSH_PERMISSION", "KNOWN_FAILURES", "HUMAN_MESSAGE"]:  # fmt: skip
        assert ho.Trigger[name] in per_story


def test_new_triggers_r1() -> None:
    assert ho.Trigger.STORY_CI_RED == "story_ci_red"
    assert ho.Trigger.WORKTREE_DRIFT == "worktree_drift"
    assert ho.Trigger.LAND_BOUNCED == "land_bounced"


def test_merge_joins_kinds_lines_and_stories_in_arrival_order_r1() -> None:
    a = ho.Pass([ho.Trigger.STORY_CI_RED], ["one"], ["s1"])
    b = ho.Pass([ho.Trigger.LAND_BOUNCED, ho.Trigger.STORY_CI_RED], ["two"], ["s2"])
    merged = ho.merge([a, b])
    assert merged.lines == ["one", "two"]
    assert merged.stories == ["s1", "s2"]
    assert merged.kinds[0] is ho.Trigger.STORY_CI_RED
    assert ho.Trigger.LAND_BOUNCED in merged.kinds


def test_merge_of_one_pass_is_that_pass_r1() -> None:
    a = ho.Pass([ho.Trigger.WORKTREE_DRIFT], ["x"], ["s1"])
    assert ho.merge([a]) == a
