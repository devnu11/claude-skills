"""s51: started stories rank first; a pull ahead of them needs a reason (design G1-G14)."""

from __future__ import annotations

import asyncio
import json

import pytest
from agile_team import po_tools, system
from agile_team.gates import PreviousStep, StoryState, StoryStatus
from agile_team.po_tools import CI_BUG_PULL, Tools
from agile_team.priority import (
    PULL_NEEDS_REASON,
    RANKED_ELSEWHERE,
    Placement,
    Priority,
    Pull,
    Tier,
    first_refusal,
    held,
    pull_refusal,
    pulls,
    set_pull,
    started,
)
from agile_team.router import Router
from agile_team.state import RunState

from .pipeline_helpers import add_story
from .test_snapshot import FIXTURE_TEXT


def story(sid: str, step: str = "design", **kw) -> StoryState:
    return StoryState(sid, sid, step, **kw)


def book(*items: StoryState) -> dict[str, StoryState]:
    return {s.id: s for s in items}


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


# ----- started / held / tier ----------------------------------------------------


@pytest.mark.parametrize(("commit", "want"), [(None, False), ("abc", True)])
def test_started_means_a_recorded_commit(commit, want) -> None:
    assert started(story("s1", "tests", commit=commit)) is want


def test_started_ignores_the_step() -> None:
    assert started(story("s1", "design", commit="abc"))
    assert not started(story("s2", "implement", previous=PreviousStep("dev", "done")))


@pytest.mark.parametrize(
    ("kw", "want"),
    [
        ({"hold": "quarantine"}, True),
        ({"status": StoryStatus.BLOCKED}, True),
        ({"status": StoryStatus.NEEDS_MANAGER}, True),
        ({}, False),
        ({"status": StoryStatus.ACTIVE}, False),
    ],
)
def test_held(kw, want) -> None:
    assert held(story("s1", **kw)) is want


def test_tier_values_are_the_three_groups() -> None:
    assert [str(t) for t in Tier] == ["in progress", "held", "not started"]


def test_tier_of_each_group_and_of_pulled_stories() -> None:
    p = Priority([], ["s4", "s5"])
    assert p.tier(story("s1", commit="a")) is Tier.IN_PROGRESS
    assert p.tier(story("s2", commit="a", hold="questions")) is Tier.HELD
    assert p.tier(story("s3")) is Tier.NOT_STARTED
    assert p.tier(story("s4")) is Tier.IN_PROGRESS
    assert p.tier(story("s5", hold="questions")) is Tier.HELD


# ----- the ranking (G3) ---------------------------------------------------------


def test_groups_come_first_then_the_order_then_natural_id() -> None:
    items = [
        story("s9"),
        story("s2", commit="a", hold="questions"),
        story("s20", commit="a"),
        story("s3", commit="a"),
        story("s1", status=StoryStatus.DONE, commit="a"),
        story("s4"),
    ]
    p = Priority(["s4", "s20"], [])
    assert [s.id for s in p.ranked(items)] == ["s20", "s3", "s2", "s4", "s9", "s1"]


def test_a_held_story_ranks_back_at_its_listed_place_when_released() -> None:
    a, b = story("s1", commit="a"), story("s2", commit="a")
    p = Priority(["s1", "s2"], [])
    a.hold = "quarantine"
    assert p.queue([a, b]) == ["s2", "s1"]
    a.hold = None
    assert p.queue([a, b]) == ["s1", "s2"]


# ----- pulls (G6, G7, G8, G9, G13) ---------------------------------------------------


def test_pulls_are_the_not_started_ids_before_the_last_started_one() -> None:
    items = book(story("s1", commit="a"), story("s2"), story("s3", commit="a"), story("s4"))
    assert pulls(["s2", "s1", "s4", "s3"], items) == ["s2", "s4"]
    assert pulls(["s1", "s3", "s2", "s4"], items) == []
    assert pulls(["s2", "s4"], items) == []
    assert pulls([], items) == []


def test_pulled_stories_do_not_count_as_started_for_pulls() -> None:
    items = book(story("s1"), story("s2"), story("s3"))
    assert pulls(["s1", "s2", "s3"], items) == []


def test_set_pull_judges_only_a_list_that_names_a_started_story() -> None:
    items = book(story("s1", commit="a"), story("s2"))
    assert set_pull(["s2", "s1"], items) == Pull(("s2", "s1"), ("s2",))
    assert set_pull(["s2"], items) == Pull()


def test_move_pull_lands_before_or_after_started_stories() -> None:
    items = book(story("s1", commit="a"), story("s2", commit="a"), story("s3"))
    p = Priority([], [])
    assert p.move_pull(Placement("s3", 1), items) == Pull(("s3",), ("s3",))
    assert p.move_pull(Placement("s3", 3), items) == Pull(("s3",), ())
    assert p.move_pull(Placement("s1", 3), items) == Pull(("s1",), ())


def test_pull_refusal_text_and_cases() -> None:
    pull = Pull(("s3", "s4"), ("s3", "s4"))
    want = PULL_NEEDS_REASON.format(ids="s3, s4")
    assert want == (
        "pulling s3, s4 ahead of started stories needs a reason; "
        "give one, or place them after the started stories"
    )
    assert pull_refusal(pull, "") == want
    assert pull_refusal(pull, "  \n") == want
    assert pull_refusal(pull, "hotfix") is None
    assert pull_refusal(Pull(("s3",), ()), "") is None
    assert pull_refusal(Pull(), "") is None


def test_repulled_drops_judged_adds_ahead_and_prunes() -> None:
    items = book(
        story("s1", commit="a"),
        story("s2"),
        story("s3"),
        story("s4"),
        story("s5", status=StoryStatus.DONE),
        story("s6", commit="a"),
    )
    p = Priority([], ["s2", "s3", "s5", "s6", "ghost"])
    got = p.repulled(Pull(("s2",), ("s4", "s3", "s4")), items)
    assert got == ["s3", "s4"]
    assert p.repulled(Pull(), items) == ["s2", "s3"]


# ----- state --------------------------------------------------------------------------


def test_state_without_pulled_loads_empty_and_pulled_round_trips() -> None:
    data = json.loads(RunState().to_json())
    data.pop("pulled", None)
    assert RunState.from_json(json.dumps(data)).pulled == []
    assert RunState.from_json(RunState(pulled=["s2"]).to_json()).pulled == ["s2"]


# ----- the router -----------------------------------------------------------------------


def origin(rt) -> None:
    add_story(rt, "s45")
    add_story(rt, "s38", "tests", commit="a")
    add_story(rt, "s21", "implement", commit="b")
    add_story(rt, "s50")
    rt.state.order = ["s45", "s38", "s21", "s50"]


def test_router_runs_the_started_story_not_the_first_listed(make_runtime) -> None:
    rt = make_runtime()
    origin(rt)
    assert Router(rt).next_work().story.id == "s38"


def test_router_skips_a_held_started_story_for_the_next_started_one(make_runtime) -> None:
    rt = make_runtime()
    origin(rt)
    rt.state.stories["s38"].hold = "quarantine"
    assert Router(rt).next_work().story.id == "s21"


def test_held_started_stories_do_not_stop_a_not_started_one(make_runtime) -> None:
    rt = make_runtime()
    origin(rt)
    for sid in ("s38", "s21"):
        rt.state.stories[sid].hold = "quarantine"
    assert Router(rt).next_work().story.id == "s45"


def test_a_pulled_story_routes_before_the_started_ones(make_runtime) -> None:
    rt = make_runtime()
    origin(rt)
    rt.state.pulled = ["s45"]
    assert Router(rt).next_work().story.id == "s45"


# ----- PO tools: the worked example ---------------------------------------------------------


def origin_tools(make_runtime) -> Tools:
    t = Tools(make_runtime())
    origin(t.runtime)
    return t


def events_of(t: Tools) -> list:
    return [e for e in t.runtime.events.events() if e.kind == "priority"]


def test_move_story_pull_without_a_reason_is_refused_and_changes_nothing(make_runtime) -> None:
    t = origin_tools(make_runtime)
    before = len(t.runtime.events.events())
    out = call(t.move_story({"story": "s45", "position": 1, "reason": ""}))
    assert out["status"] == "refused"
    assert out["reason"] == PULL_NEEDS_REASON.format(ids="s45")
    assert t.runtime.state.order == ["s45", "s38", "s21", "s50"]
    assert t.runtime.state.pulled == [] and len(t.runtime.events.events()) == before


def test_move_story_pull_without_a_reason_key_is_refused(make_runtime) -> None:
    t = origin_tools(make_runtime)
    out = call(t.move_story({"story": "s45", "position": 1}))
    assert out["status"] == "refused"


def test_move_story_pull_with_a_reason_pulls_and_records(make_runtime) -> None:
    t = origin_tools(make_runtime)
    out = call(t.move_story({"story": "s45", "position": 1, "reason": "hotfix today"}))
    assert out == {"status": "ordered", "order": ["s45", "s38", "s21", "s50"]}
    assert t.runtime.state.pulled == ["s45"]
    [ev] = events_of(t)
    assert ev.data["pulled"] == ["s45"] and ev.data["reason"] == "hotfix today"
    assert ev.data["order"] == ["s45", "s38", "s21", "s50"]
    assert ev.data["moves"] == [
        {"story": "s45", "from": 3, "to": 1},
        {"story": "s38", "from": 1, "to": 2},
        {"story": "s21", "from": 2, "to": 3},
    ]


def test_move_story_of_a_started_story_behind_others_keeps_order_and_notes(make_runtime) -> None:
    t = origin_tools(make_runtime)
    out = call(t.move_story({"story": "s21", "position": 4, "reason": "x"}))
    note = RANKED_ELSEWHERE.format(story="s21", landed=2, position=4)
    assert out["note"] == note and note.startswith("s21 ranks #2, not #4")
    assert out["order"] == ["s38", "s21", "s45", "s50"]
    assert t.runtime.state.order == ["s45", "s38", "s21", "s50"]  # G16 rule 1
    assert t.runtime.state.pulled == []


def test_move_story_landing_where_asked_has_no_note(make_runtime) -> None:
    t = origin_tools(make_runtime)
    out = call(t.move_story({"story": "s21", "position": 1, "reason": ""}))
    assert "note" not in out and out["order"][0] == "s21"


def test_prioritise_pull_needs_a_reason_then_pulls(make_runtime) -> None:
    t = origin_tools(make_runtime)
    out = call(t.prioritise({"stories": ["s45", "s38"]}))
    assert out["status"] == "refused" and out["reason"] == PULL_NEEDS_REASON.format(ids="s45")
    assert t.runtime.state.pulled == []
    out = call(t.prioritise({"stories": ["s45", "s38"], "reason": "hotfix"}))
    assert out["order"] == ["s45", "s38", "s21", "s50"]
    assert t.runtime.state.pulled == ["s45"]
    assert events_of(t)[-1].data["pulled"] == ["s45"]


def test_prioritise_without_a_started_story_keeps_pulls_and_needs_no_reason(make_runtime) -> None:
    t = origin_tools(make_runtime)
    call(t.move_story({"story": "s45", "position": 1, "reason": "hotfix"}))
    out = call(t.prioritise({"stories": ["s50", "s45"]}))
    assert out["order"] == ["s45", "s38", "s21", "s50"]
    assert t.runtime.state.order == ["s50", "s45", "s38", "s21"]
    assert t.runtime.state.pulled == ["s45"]


def test_prioritise_listing_a_pulled_story_after_a_started_one_unpulls_it(make_runtime) -> None:
    t = origin_tools(make_runtime)
    call(t.move_story({"story": "s45", "position": 1, "reason": "hotfix"}))
    out = call(t.prioritise({"stories": ["s21", "s45"]}))
    assert out["status"] == "ordered" and out["order"] == ["s21", "s38", "s45", "s50"]
    assert t.runtime.state.pulled == []
    assert events_of(t)[-1].data["pulled"] == []


# ----- start_sprint ---------------------------------------------------------------------


def test_start_sprint_never_pulls_from_its_list(make_runtime) -> None:
    t = Tools(make_runtime())
    for sid in ("s1", "s2"):
        call(t.open_story({"id": sid, "title": sid}))
    t.runtime.state.stories["s2"].commit = "abc"
    out = call(t.start_sprint({"goal": "G", "stories": ["s1", "s2"]}))
    assert "status" not in out or out.get("status") != "refused"
    state = t.runtime.state
    assert t.runtime.priority().queue(state.stories.values()) == ["s2", "s1"]
    assert state.pulled == []
    [ev] = events_of(t)
    assert ev.data["pulled"] == [] and ev.data["order"] == ["s2", "s1"]


def test_start_sprint_pulls_the_pending_ci_bug_story(make_runtime) -> None:
    t = Tools(make_runtime())
    for sid in ("s1", "s2"):
        call(t.open_story({"id": sid, "title": sid}))
    t.runtime.state.stories["s2"].commit = "abc"
    t.runtime.state.upstream.ci_bug = "s1"
    call(t.start_sprint({"goal": "G", "stories": ["s1", "s2"]}))
    state = t.runtime.state
    assert t.runtime.priority().queue(state.stories.values()) == ["s1", "s2"]
    assert state.pulled == ["s1"]
    [ev] = events_of(t)
    assert ev.data["pulled"] == ["s1"]
    assert ev.data["reason"] == "G; " + CI_BUG_PULL.format(story="s1")
    assert ev.data["reason"].endswith("s1 fixes it")
    assert state.upstream.ci_bug == ""


def test_story_status_reports_pulled(make_runtime) -> None:
    t = origin_tools(make_runtime)
    call(t.move_story({"story": "s45", "position": 1, "reason": "hotfix"}))
    status = call(t.story_status({}))
    assert status["pulled"] == ["s45"]
    assert list(status["stories"])[:2] == ["s45", "s38"]


def test_schema_descriptions_state_the_new_rule() -> None:
    assert po_tools.SCHEMAS["prioritise"][0].startswith(
        "Set the order the team works in: the listed story ids first, in that order;"
    )
    assert "Started stories (with commits) always rank first" in po_tools.SCHEMAS["prioritise"][0]
    assert "give a reason; without a reason that is refused" in po_tools.SCHEMAS["prioritise"][0]
    assert "pulls it ahead and needs a reason" in po_tools.SCHEMAS["move_story"][0]
    assert "the order keeps its place" in po_tools.SCHEMAS["move_story"][0]
    sprint = po_tools.SCHEMAS["start_sprint"][0]
    assert "priority within each group; started stories still come first." in sprint


# ----- snapshot fixture and page -----------------------------------------------------------


def test_fixture_has_tiers_and_a_pulled_event() -> None:
    fixture = json.loads(FIXTURE_TEXT)
    tiers = {s["tier"] for s in fixture["stories"]}
    assert {"in progress", "held", "not started"} <= tiers
    assert all("in_progress" not in s for s in fixture["stories"])
    assert all(s["tier"] is None for s in fixture["stories"] if s["status"] == "done")
    ev = [e for e in fixture["events"] if e["kind"] == "priority"][-1]
    assert len(ev["data"]["pulled"]) == 1


def test_page_source_shows_pulled_ahead_in_the_timeline() -> None:
    from agile_team.dashboard import snapshot

    html = system.read_text(snapshot.Path(snapshot.__file__).parent / "index.html")
    assert "pulled ahead:" in html


def test_product_owner_role_states_the_groups() -> None:
    from agile_team import roles

    text = system.read_text(roles.BUILTIN_DIR / "product-owner.md")
    assert "Started stories (with commits) always go first" in text


# ----- round 1: changes build on the plan, not the queue (G15-G17) --------------------------


def test_plan_is_listed_then_natural_with_no_groups_and_no_done() -> None:
    items = [
        story("s3", commit="a"),
        story("s2"),
        story("s10"),
        story("s1", status=StoryStatus.DONE),
        story("s9"),
    ]
    p = Priority(["s9", "s3", "s1"], [])
    assert p.plan(items) == ["s9", "s3", "s2", "s10"]


def test_with_first_keeps_a_held_started_story_before_a_later_in_progress_one() -> None:
    held_one = story("s38", commit="a", hold="quarantine")
    items = [story("s45"), held_one, story("s21", commit="b"), story("s50")]
    p = Priority(["s45", "s38", "s21", "s50"], [])
    assert p.with_first(["s50"], items) == ["s50", "s45", "s38", "s21"]


def test_board_move_is_the_queue_move() -> None:
    items = book(story("s1"), story("s2"), story("s3"))
    p = Priority(["s1", "s2", "s3"], [])
    assert p.board_move(Placement("s3", 1), items) == ["s3", "s1", "s2"]
    assert p.board_move(Placement("s3", 3), items) == ["s1", "s2", "s3"]


def held_board() -> tuple[Priority, dict[str, StoryState]]:
    """Queue s21, s38 (held), s45, s50; plan s45, s38, s21, s50."""
    items = book(
        story("s45"),
        story("s38", commit="a", hold="quarantine"),
        story("s21", commit="b"),
        story("s50"),
    )
    return Priority(["s45", "s38", "s21", "s50"], []), items


def test_with_move_rule_1_goes_after_the_nearest_same_group_story_before() -> None:
    p, items = held_board()
    # board without s45: s21, s38, s50; s45 at 4 -> after s50 (same group)
    assert p.with_move(Placement("s45", 4), items) == ["s38", "s21", "s50", "s45"]


def test_with_move_rule_2_goes_before_the_nearest_same_group_story_after() -> None:
    p, items = held_board()
    # D1 repro: s50 at 3 has no same-group story before it; s45 is next
    assert p.with_move(Placement("s50", 3), items) == ["s50", "s45", "s38", "s21"]


def test_with_move_rule_3_alone_in_group_goes_before_the_next_on_the_board() -> None:
    p, items = held_board()
    # s38 is the only held story; at 1 it is before s21 on the board
    assert p.with_move(Placement("s38", 1), items) == ["s45", "s38", "s21", "s50"]
    # alone in its group and last on the board: at the end of the plan
    assert p.with_move(Placement("s38", 4), items) == ["s45", "s21", "s50", "s38"]


def test_with_move_of_a_pulled_story_lands_after_the_in_progress_one() -> None:
    p, items = held_board()
    p = Priority(p.order, ["s50"])
    # queue s21, s50(pulled), s38, ... : s50 to 2 is after s21 (same group)
    assert p.with_move(Placement("s50", 2), items) == ["s45", "s38", "s21", "s50"]


def test_move_pull_judges_board_move() -> None:
    p, items = held_board()
    assert p.move_pull(Placement("s45", 1), items) == Pull(("s45",), ("s45",))
    assert p.move_pull(Placement("s45", 4), items) == Pull(("s45",), ())


def test_first_refusal_returns_the_first_refusal_and_stops() -> None:
    calls: list[str] = []

    def check(name: str, result: str | None):
        def run() -> str | None:
            calls.append(name)
            return result

        return run

    assert first_refusal([]) is None
    assert first_refusal([check("a", None), check("b", None)]) is None
    calls.clear()
    assert first_refusal([check("a", None), check("b", "no"), check("c", "later")]) == "no"
    assert calls == ["a", "b"]


def test_prioritise_while_a_started_story_is_held_keeps_its_place(make_runtime) -> None:
    t = origin_tools(make_runtime)
    t.runtime.state.stories["s38"].hold = "quarantine"
    out = call(t.prioritise({"stories": ["s50"], "reason": ""}))
    assert out["status"] == "ordered"
    assert t.runtime.state.order == ["s50", "s45", "s38", "s21"]
    t.runtime.state.stories["s38"].hold = None
    assert t.runtime.priority().queue(t.runtime.state.stories.values())[0] == "s38"


def test_move_story_while_a_started_story_is_held_keeps_its_place(make_runtime) -> None:
    t = origin_tools(make_runtime)
    t.runtime.state.stories["s38"].hold = "quarantine"
    out = call(t.move_story({"story": "s50", "position": 3, "reason": ""}))
    assert out["status"] == "ordered"
    assert t.runtime.state.order == ["s50", "s45", "s38", "s21"]
    t.runtime.state.stories["s38"].hold = None
    assert t.runtime.priority().queue(t.runtime.state.stories.values())[0] == "s38"


def test_a_refused_pull_is_returned_once_and_unknown_ids_are_not_pulled_on(make_runtime) -> None:
    t = origin_tools(make_runtime)
    out = call(t.prioritise({"stories": ["s45", "s38"], "reason": ""}))
    assert out["status"] == "refused"
    assert out["reason"] == PULL_NEEDS_REASON.format(ids="s45")
