"""s159 through the library API with real files: the ledger-backed budget reserve, the hand-over
scope table, the halt table and the story-state round trip.
"""

from __future__ import annotations

from pathlib import Path

from agile_team import budget_reserve as br
from agile_team import handover
from agile_team import state as state_mod
from agile_team.gates import StoryState
from agile_team.halt import HALTS, HaltKind
from agile_team.ledger import Entry, Ledger
from agile_team.state import RunState, RunStatus
from agile_team.story_branches import KeptSession, Landed, StoryCi

DEV = br.Who("developer", "sonnet", 1.0)


def ledger_with(path: Path, costs: list[float], **kw) -> Ledger:
    ledger = Ledger(path)
    for cost in costs:
        ledger.record(Entry("developer", "sonnet", cost, "s1", **kw))
    return ledger


def test_ac12_1_under_five_fresh_steps_only_the_floor_applies(tmp_path: Path) -> None:
    ledger = ledger_with(tmp_path / "ledger.jsonl", [3.0, 3.0, 3.0, 3.0])
    assert br.reserve(ledger.entries(), DEV) == 1.0


def test_ac12_1_from_five_fresh_steps_the_reserve_is_mean_plus_three_sigma(
    tmp_path: Path,
) -> None:
    ledger = ledger_with(tmp_path / "ledger.jsonl", [1.0, 2.0, 3.0, 4.0, 5.0])
    assert round(br.reserve(ledger.entries(), DEV), 3) == round(3 + 3 * 2**0.5, 3)


def test_ac12_1_resumed_and_estimated_steps_are_excluded(tmp_path: Path) -> None:
    ledger = ledger_with(tmp_path / "ledger.jsonl", [9.0] * 6, resumed=True)
    assert br.reserve(ledger.entries(), DEV) == 1.0


def test_ac12_1_nothing_starts_when_spend_plus_reserves_could_reach_the_ceiling() -> None:
    assert br.start_refusal(br.Headroom(5.0, 10.0), [1.0, 1.0]) is None
    text = br.start_refusal(br.Headroom(8.5, 10.0), [1.0, 1.0])
    assert text and "reaches 10.00" in text


def test_ac6_6_every_trigger_has_a_scope_and_the_new_ones_are_per_story() -> None:
    handover.check_scopes()
    for name in ("STORY_CI_RED", "WORKTREE_DRIFT", "LAND_BOUNCED"):
        assert handover.SCOPES[handover.Trigger[name]] is handover.Scope.STORY
    assert handover.SCOPES[handover.Trigger.CI_FAILED] is handover.Scope.RUN


def test_ac11_4_the_usage_limit_is_its_own_status_and_exits_75() -> None:
    rule = HALTS[HaltKind.LIMIT]
    assert rule.status is RunStatus.LIMIT and rule.exit_code == 75
    assert RunState(status=RunStatus.LIMIT).halted()


def test_ac2_15_ac10_2_story_branch_fields_survive_a_save_and_load(tmp_path: Path) -> None:
    story = StoryState("s1", "One", "land", sprint=1, branch="team/story-s1-r1", base_sha="b" * 40)
    story.pushed, story.pr, story.replays = "c" * 40, 9, 1
    story.landed = Landed("d" * 40, pushed="d" * 40, pr=4)
    story.sessions = {"developer": KeptSession("sess", "m", "high", "claude")}
    story.story_ci = StoryCi("c" * 40, "green", "pr")
    state = RunState()
    state.stories["s1"] = story
    state_mod.save(tmp_path, state)
    back = state_mod.load(tmp_path).stories["s1"]
    assert (back.branch, back.base_sha, back.pushed, back.pr, back.replays) == (
        "team/story-s1-r1",
        "b" * 40,
        "c" * 40,
        9,
        1,
    )
    assert back.landed == Landed("d" * 40, pushed="d" * 40, pr=4)
    assert back.sessions["developer"].session == "sess"
