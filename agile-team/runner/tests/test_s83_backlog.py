"""s83: the Backlog's runner side: groups, requests, the desk, the PO's rule (design B1-B17)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agile_team import po_tools, system
from agile_team import state as state_mod
from agile_team.backlog import (
    BAD_PLACE,
    CANCELLED,
    HUMAN_ORDER,
    SPRINT_STORY,
    STALE,
    STORY_ID,
    Ask,
    HumanCheck,
    View,
    guarded,
    human_refusal,
    label,
    order_version,
    place_refusal,
    sprint_refusal,
    stale_refusal,
)
from agile_team.gates import StoryState, StoryStatus
from agile_team.handover import Pass, Trigger
from agile_team.po_tools import PoRun, Start, Tools
from agile_team.priority import (
    SOURCE_ROLES,
    Change,
    Pull,
    Reorder,
    Source,
)
from agile_team.reorders import (
    APPLIED,
    HUMAN_REASON,
    TOLD,
    TOLD_HEAD,
    Desk,
    Request,
    Requests,
    parse_ask,
    told_section,
)
from agile_team.router import Router
from agile_team.state import RunState

from .pipeline_helpers import add_story


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def story(sid: str, **kw) -> StoryState:
    return StoryState(sid, sid, "design", **kw)


def world(rt, *, human: list[str] | None = None) -> None:
    """Sprint 1 holds s1, s2; the backlog holds s5, s6, s7; none started."""
    for sid in ("s1", "s2"):
        add_story(rt, sid)
    for sid in ("s5", "s6", "s7"):
        add_story(rt, sid, sprint=None)
    rt.state.order = ["s1", "s2", "s5", "s6", "s7"]
    rt.state.human_order = human or []


def view_of(rt) -> View:
    return View.of(rt.state)


def ask(rt, story_id: str, position, version: str | None = None) -> Ask:
    return Ask(story_id, position, version or view_of(rt).version)


def settle(rt, *asks: Ask) -> list[Request]:
    queued = [Requests(rt.config.run_dir).queue(a) for a in asks]
    Desk(rt).apply()
    return queued


def priority_events(rt) -> list:
    return [e for e in rt.events.events() if e.kind == "priority"]


# ----- B1, B3, B10: groups, label, version -------------------------------------------


def test_view_splits_the_queue_into_sprint_and_backlog(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    add_story(rt, "s9", "design", status=StoryStatus.DONE)
    view = view_of(rt)
    assert view.queue == ["s1", "s2", "s5", "s6", "s7"]
    assert view.backlog == ["s5", "s6", "s7"]
    assert view.version == order_version(view.queue, view.backlog)


def test_view_of_a_state_with_no_stories_is_empty() -> None:
    view = View.of(RunState())
    assert (view.queue, view.backlog) == ([], [])


def test_order_version_is_twelve_hex_digits_and_stable() -> None:
    v = order_version(["a", "b"], ["b"])
    assert len(v) == 12 and int(v, 16) >= 0
    assert v == order_version(["a", "b"], ["b"])


def test_order_version_changes_with_order_and_with_sprint_membership() -> None:
    base = order_version(["a", "b", "c"], ["b", "c"])
    assert order_version(["a", "c", "b"], ["c", "b"]) != base
    assert order_version(["a", "b", "c"], ["c"]) != base  # b joined the sprint


def test_view_version_changes_when_a_story_joins_the_sprint(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    before = view_of(rt).version
    rt.state.stories["s5"].sprint = 1
    assert view_of(rt).version != before


@pytest.mark.parametrize(
    ("hold", "want"),
    [
        ("cancelled by the human (t15); not built", "cancelled"),
        ("  Cancelled: x", "cancelled"),
        ("waiting on s9", "held"),
        (None, ""),
    ],
)
def test_label(hold, want) -> None:
    assert label(story("s1", hold=hold)) == want


def test_cancelled_text_is_the_word() -> None:
    assert CANCELLED == "cancelled"


def test_a_started_story_with_no_hold_has_no_label() -> None:
    assert label(story("s1", commit="abc")) == ""


def test_story_id_shape() -> None:
    assert STORY_ID.match("s83") and STORY_ID.match("A_b-1")
    for bad in ("", "1a", "../x", "s1/..", "/etc", "a" * 65, "s 1"):
        assert not STORY_ID.match(bad)


# ----- B12: refusal pieces ------------------------------------------------------------


def test_stale_refusal(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    view = view_of(rt)
    assert stale_refusal(Ask("s5", 1, view.version), view) is None
    assert stale_refusal(Ask("s5", 1, "old"), view) == STALE
    assert STALE == "the order changed since the dashboard showed it; reload"


def test_sprint_refusal(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    view = view_of(rt)
    assert sprint_refusal("s5", view) is None
    assert sprint_refusal("s1", view) == SPRINT_STORY.format(story="s1")


@pytest.mark.parametrize("bad", [0, 4, True, "2", None, 1.0, -1])
def test_place_refusal_rejects(make_runtime, bad) -> None:
    rt = make_runtime()
    world(rt)
    assert place_refusal(bad, view_of(rt)) == BAD_PLACE.format(count=3)


@pytest.mark.parametrize("good", [1, 2, 3])
def test_place_refusal_accepts(make_runtime, good) -> None:
    rt = make_runtime()
    world(rt)
    assert place_refusal(good, view_of(rt)) is None


def test_placement_maps_backlog_place_to_queue_position(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    placement = view_of(rt).placement(ask(rt, "s7", 2))
    assert (placement.story, placement.position) == ("s7", 4)


# ----- B17: the human's order ---------------------------------------------------------


def test_guarded_keeps_only_backlog_stories(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    assert guarded(["s5", "s1", "s6", "gone"], view_of(rt)) == ["s5", "s6"]
    assert guarded([], view_of(rt)) == []


def test_human_refusal_needs_a_reason_when_the_guarded_order_changes() -> None:
    check = HumanCheck(["s5", "s6"], ["s1", "s5", "s6"], ["s6", "s1", "s5"])
    assert human_refusal(check, "") == HUMAN_ORDER.format(stories="s5, s6")
    assert human_refusal(check, "   ") == HUMAN_ORDER.format(stories="s5, s6")
    assert human_refusal(check, "because") is None


def test_human_refusal_ignores_changes_outside_the_guarded_order() -> None:
    check = HumanCheck(["s5", "s6"], ["s1", "s5", "s6"], ["s5", "s1", "s6"])
    assert human_refusal(check, "") is None


def test_human_refusal_with_nothing_guarded() -> None:
    assert human_refusal(HumanCheck([], ["a", "b"], ["b", "a"]), "") is None


def test_human_order_text_names_the_stories() -> None:
    assert "{stories}" in HUMAN_ORDER and "give a reason" in HUMAN_ORDER


# ----- B14: priority source ------------------------------------------------------------


def test_source_values_and_roles() -> None:
    assert Source.PO == "product-owner" and Source.HUMAN == "human (dashboard)"
    assert SOURCE_ROLES == {Source.PO: "product-owner", Source.HUMAN: None}


def test_reorder_defaults_to_the_po_and_builds_event_data() -> None:
    change = Reorder(Change.MOVE, ["b", "a"], "b", "why", Pull((), ("b",)))
    assert change.source is Source.PO
    data = change.event_data(["a", "b"], ["b", "a"])
    assert data["source"] == "product-owner"
    assert data["change"] == "move" and data["order"] == ["b", "a"]
    assert data["reason"] == "why" and data["pulled"] == ["b"]
    assert data["moves"] and set(data) == {"change", "order", "moves", "reason", "pulled", "source"}


def test_po_tool_events_carry_the_po_source_and_role(make_runtime) -> None:
    t = Tools(make_runtime())
    world(t.runtime)
    call(t.prioritise({"stories": ["s7"]}))
    call(t.move_story({"story": "s6", "position": 1}))
    first, second = priority_events(t.runtime)
    for ev in (first, second):
        assert ev.role == "product-owner" and ev.data["source"] == "product-owner"


def test_runtime_reorder_applies_logs_and_returns_the_queue(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    order = ["s7", "s1", "s2", "s5", "s6"]
    after = rt.reorder(Reorder(Change.SET, order, None, "r", Pull(), Source.HUMAN))
    assert after == order and rt.state.order == order
    [ev] = priority_events(rt)
    assert ev.role is None and ev.data["source"] == "human (dashboard)"
    assert state_mod.load(rt.config.run_dir).order == order


# ----- reorders: parse_ask, Request, Requests, told_section ---------------------------------


def body(**kw) -> bytes:
    return json.dumps({"story": "s5", "position": 1, "version": "abc", **kw}).encode()


def test_parse_ask_accepts_a_good_body_and_ignores_extra_keys() -> None:
    assert parse_ask(body(extra=1)) == Ask("s5", 1, "abc")


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not json",
        b"[]",
        b'"s5"',
        b"null",
        json.dumps({"position": 1, "version": "a"}).encode(),
        json.dumps({"story": "s5", "version": "a"}).encode(),
        json.dumps({"story": "s5", "position": 1}).encode(),
        body(position=True),
        body(position="1"),
        body(position=1.5),
        body(story="../x"),
        body(story="s 1"),
        body(story=5),
        body(version="v" * 65),
        body(version=3),
        b"\xff\xfe",
    ],
)
def test_parse_ask_refuses(raw) -> None:
    assert parse_ask(raw) is None


def test_parse_ask_allows_a_version_of_64_chars() -> None:
    assert parse_ask(body(version="v" * 64)) is not None


def test_request_round_trips_through_json() -> None:
    req = Request("r3", Ask("s5", 2, "abc"), 12.5)
    assert Request.from_json("r3", req.to_json()) == req


@pytest.mark.parametrize("text", ["", "x", "[]", '{"ask": 1}', "null"])
def test_request_from_bad_json_is_none(text) -> None:
    assert Request.from_json("r1", text) is None


def test_queue_writes_numbered_files_with_no_draft(make_runtime) -> None:
    rt = make_runtime()
    reqs = Requests(rt.config.run_dir)
    one = reqs.queue(Ask("s5", 1, "v"))
    two = reqs.queue(Ask("s6", 2, "v"))
    assert (one.id, two.id) == ("r1", "r2")
    folder = rt.config.run_dir / "reorders"
    names = sorted(p.name for p in system.list_dir(folder))
    assert names == ["r1.json", "r2.json"]
    assert [r.id for r in reqs.all()] == ["r1", "r2"]
    assert reqs.all()[1].ask == Ask("s6", 2, "v")


def test_queue_moves_on_when_the_number_is_taken(make_runtime, monkeypatch) -> None:
    rt = make_runtime()
    reqs = Requests(rt.config.run_dir)
    reqs.queue(Ask("s5", 1, "v"))
    real = system.hard_link
    clashes = iter([FileExistsError()])

    def link(target, draft):
        err = next(clashes, None)
        if err:
            raise err
        return real(target, draft)

    monkeypatch.setattr(system, "hard_link", link)
    assert reqs.queue(Ask("s6", 1, "v")).id == "r3"


def test_all_skips_other_names_and_unreadable_files(make_runtime) -> None:
    rt = make_runtime()
    reqs = Requests(rt.config.run_dir)
    reqs.queue(Ask("s5", 1, "v"))
    folder = rt.config.run_dir / "reorders"
    system.write_text(folder / "r2.json", "garbage")
    system.write_text(folder / "notes.txt", "x")
    system.write_text(folder / "r10.json", Request("r10", Ask("s6", 1, "v")).to_json())
    assert [r.id for r in reqs.all()] == ["r1", "r10"]


def test_all_with_no_folder_is_empty(make_runtime) -> None:
    assert Requests(make_runtime().config.run_dir).all() == []


def test_pending_leaves_out_the_settled(make_runtime) -> None:
    rt = make_runtime()
    reqs = Requests(rt.config.run_dir)
    for _ in range(3):
        reqs.queue(Ask("s5", 1, "v"))
    assert [r.id for r in reqs.pending({"r2": APPLIED})] == ["r1", "r3"]


def test_told_section() -> None:
    assert told_section([]) == ""
    assert told_section(["a", "b"]) == f"{TOLD_HEAD}\n- a\n- b\n\n"
    assert TOLD_HEAD == "From the dashboard:"


def test_texts() -> None:
    assert APPLIED == "applied"
    assert HUMAN_REASON.format(id="r1") == "moved on the dashboard (r1)"
    assert "{backlog}" in TOLD and "needs a reason" in TOLD


# ----- B11-B13: the desk ---------------------------------------------------------------


def test_applying_a_move_to_place_one(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    settle(rt, ask(rt, "s7", 1))
    assert view_of(rt).backlog == ["s7", "s5", "s6"]
    assert rt.state.reorders["r1"] == APPLIED
    assert rt.state.human_order == ["s7", "s5", "s6"]
    [ev] = priority_events(rt)
    assert ev.role is None and ev.story == "s7"
    assert ev.data["source"] == "human (dashboard)"
    assert ev.data["reason"] == "moved on the dashboard (r1)"
    assert ev.data["change"] == "move"
    saved = state_mod.load(rt.config.run_dir)
    assert saved.reorders == {"r1": APPLIED} and saved.human_order == ["s7", "s5", "s6"]


def test_applying_tells_the_po_with_the_exact_line(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    settle(rt, ask(rt, "s7", 1))
    assert rt.state.reorders_told == [
        TOLD.format(story="s7", position=1, id="r1", backlog="s7, s5, s6")
    ]


def test_a_not_started_story_moved_above_a_started_one_is_pulled(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    rt.state.stories["s5"].commit = "abc"
    settle(rt, ask(rt, "s7", 1))
    [ev] = priority_events(rt)
    assert ev.data["pulled"] == ["s7"] and rt.state.pulled == ["s7"]
    assert rt.state.reorders["r1"] == APPLIED


def test_a_sprint_story_is_refused_and_nothing_changes(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    order = list(rt.state.order)
    settle(rt, ask(rt, "s1", 1))
    assert rt.state.reorders["r1"] == SPRINT_STORY.format(story="s1")
    assert rt.state.order == order and priority_events(rt) == []
    assert rt.state.human_order == [] and rt.state.reorders_told == []


def test_a_stale_request_is_refused_with_exactly_stale(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    order = list(rt.state.order)
    settle(rt, Ask("s7", 1, "0123456789ab"))
    assert rt.state.reorders["r1"] == STALE
    assert rt.state.order == order and priority_events(rt) == []


def test_of_two_requests_from_one_version_the_second_is_stale(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    settle(rt, ask(rt, "s7", 1), ask(rt, "s6", 1))
    assert rt.state.reorders == {"r1": APPLIED, "r2": STALE}
    assert view_of(rt).backlog == ["s7", "s5", "s6"]
    assert len(priority_events(rt)) == 1


@pytest.mark.parametrize("bad", [0, 4, True, "2"])
def test_a_bad_place_is_refused_with_the_backlog_length(make_runtime, bad) -> None:
    rt = make_runtime()
    world(rt)
    settle(rt, ask(rt, "s7", bad))
    assert rt.state.reorders["r1"] == BAD_PLACE.format(count=3)
    assert priority_events(rt) == []


def test_an_unknown_story_gets_the_order_refusal_text(make_runtime) -> None:
    from agile_team.priority import order_refusal

    rt = make_runtime()
    world(rt)
    settle(rt, ask(rt, "s99", 1))
    assert rt.state.reorders["r1"] == order_refusal(["s99"], rt.state.stories)


def test_a_done_story_gets_the_order_refusal_text(make_runtime) -> None:
    from agile_team.priority import order_refusal

    rt = make_runtime()
    world(rt)
    rt.state.stories["s6"].status = StoryStatus.DONE
    settle(rt, Ask("s6", 1, view_of(rt).version))
    assert rt.state.reorders["r1"] == order_refusal(["s6"], rt.state.stories)


def test_a_settled_request_is_not_applied_again(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    settle(rt, ask(rt, "s7", 1))
    Desk(rt).apply()
    assert len(priority_events(rt)) == 1 and len(rt.state.reorders_told) == 1


def test_apply_with_no_requests_changes_nothing(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    Desk(rt).apply()
    assert rt.state.reorders == {} and priority_events(rt) == []


def test_requests_apply_in_number_order(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    reqs = Requests(rt.config.run_dir)
    first = reqs.queue(ask(rt, "s7", 1))
    reqs.queue(Ask("s6", 1, "stale"))
    assert first.id == "r1"
    Desk(rt).apply()
    assert list(rt.state.reorders) == ["r1", "r2"]


# ----- B11: the router ---------------------------------------------------------------


def test_tick_applies_pending_requests_before_picking_work(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    Requests(rt.config.run_dir).queue(ask(rt, "s7", 1))
    router = Router(rt)
    assert isinstance(router.desk, Desk)
    seen: list[dict] = []
    router.next_work = lambda: seen.append(dict(rt.state.reorders))  # type: ignore[method-assign]
    asyncio.run(router._tick())
    assert seen and seen[0] == {"r1": APPLIED}


def test_tick_does_not_apply_when_the_checkout_moved(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    Requests(rt.config.run_dir).queue(ask(rt, "s7", 1))
    rt.checkout_moved = lambda: True  # type: ignore[method-assign]
    assert asyncio.run(Router(rt)._tick()) is None
    assert rt.state.reorders == {}


# ----- B15: the PO is told --------------------------------------------------------------


def test_the_next_hand_over_tells_the_po_once_and_saves(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    settle(rt, ask(rt, "s7", 1))
    line = rt.state.reorders_told[0]
    turn = PoRun(rt, Start("t"))._hand_over(Pass([Trigger.REFUSED], ["x"], []), "")
    assert TOLD_HEAD in turn.prompt and line in turn.prompt
    assert rt.state.reorders_told == []
    assert state_mod.load(rt.config.run_dir).reorders_told == []
    again = PoRun(rt, Start("t"))._hand_over(Pass([Trigger.REFUSED], ["x"], []), "")
    assert TOLD_HEAD not in again.prompt


def test_the_lead_comes_before_the_dashboard_lines(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    settle(rt, ask(rt, "s7", 1))
    turn = PoRun(rt, Start("t"))._hand_over(Pass([Trigger.REFUSED], ["x"], []), "LEAD\n\n")
    assert turn.prompt.index("LEAD") < turn.prompt.index(TOLD_HEAD)


def test_a_pass_with_no_kinds_leaves_the_lines_waiting(make_runtime) -> None:
    rt = make_runtime()
    world(rt)
    settle(rt, ask(rt, "s7", 1))
    assert PoRun(rt, Start("t"))._hand_over(Pass([], [], []), "") is None
    assert len(rt.state.reorders_told) == 1


# ----- B17: PO tools ----------------------------------------------------------------------


def po(make_runtime, human) -> Tools:
    t = Tools(make_runtime())
    world(t.runtime, human=human)
    return t


def test_a_move_that_swaps_the_humans_order_needs_a_reason(make_runtime) -> None:
    t = po(make_runtime, ["s5", "s6"])
    before = len(t.runtime.events.events())
    out = call(t.move_story({"story": "s6", "position": 3}))
    assert out["status"] == "refused"
    assert out["reason"] == HUMAN_ORDER.format(stories="s5, s6")
    assert t.runtime.state.order == ["s1", "s2", "s5", "s6", "s7"]
    assert len(t.runtime.events.events()) == before


def test_the_same_move_with_a_reason_applies_and_logs_it(make_runtime) -> None:
    t = po(make_runtime, ["s5", "s6"])
    out = call(t.move_story({"story": "s6", "position": 3, "reason": "s6 unblocks s2"}))
    assert out["status"] == "ordered"
    [ev] = priority_events(t.runtime)
    assert ev.data["reason"] == "s6 unblocks s2" and ev.data["source"] == "product-owner"
    assert t.runtime.state.human_order == ["s5", "s6"]  # the PO does not rewrite it


def test_prioritise_that_swaps_the_humans_order_needs_a_reason(make_runtime) -> None:
    t = po(make_runtime, ["s5", "s6"])
    out = call(t.prioritise({"stories": ["s6", "s5"]}))
    assert out["status"] == "refused" and out["reason"] == HUMAN_ORDER.format(stories="s5, s6")
    assert call(t.prioritise({"stories": ["s6", "s5"], "reason": "why"}))["status"] == "ordered"


def test_a_sprint_story_move_that_keeps_the_humans_order_needs_no_reason(make_runtime) -> None:
    t = po(make_runtime, ["s5", "s6"])
    assert call(t.move_story({"story": "s1", "position": 5}))["status"] == "ordered"


def test_no_human_order_guards_nothing(make_runtime) -> None:
    t = po(make_runtime, [])
    assert call(t.move_story({"story": "s6", "position": 3}))["status"] == "ordered"


def test_start_sprint_is_never_refused_by_the_humans_order(make_runtime) -> None:
    t = po(make_runtime, ["s5", "s6"])
    out = call(t.start_sprint({"goal": "G", "stories": ["s6", "s5"]}))
    assert out.get("status") != "refused" and out["sprint"] == 2


def test_the_schemas_mention_the_dashboard_order() -> None:
    for name in ("prioritise", "move_story"):
        text = po_tools.SCHEMAS[name][0]
        assert "dashboard" in text


def test_the_po_role_explains_the_dashboard_order() -> None:
    text = system.read_text(Path(po_tools.__file__).parent / "roles" / "product-owner.md")
    assert "From the dashboard" in text


# ----- state -------------------------------------------------------------------------------


def test_an_old_state_loads_with_empty_defaults(make_runtime) -> None:
    rt = make_runtime()
    rt.save()
    path = rt.config.run_dir / state_mod.STATE_FILE
    raw = json.loads(system.read_text(path))
    for key in ("human_order", "reorders", "reorders_told"):
        raw.pop(key, None)
    system.write_text(path, json.dumps(raw))
    loaded = state_mod.load(rt.config.run_dir)
    assert (loaded.human_order, loaded.reorders, loaded.reorders_told) == ([], {}, [])


def test_the_new_state_fields_round_trip(make_runtime) -> None:
    rt = make_runtime()
    rt.state.human_order = ["s5"]
    rt.state.reorders = {"r1": APPLIED, "r2": STALE}
    rt.state.reorders_told = ["x"]
    rt.save()
    loaded = state_mod.load(rt.config.run_dir)
    assert loaded.human_order == ["s5"] and loaded.reorders == {"r1": APPLIED, "r2": STALE}
    assert loaded.reorders_told == ["x"]


def test_system_token_is_a_url_safe_string(fake) -> None:
    assert system.token() == "tok1" and system.token() == "tok2"
    assert "token" in system.__all__
