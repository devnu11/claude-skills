"""s122: add_to_sprint adds stories to the running sprint; restarts need a reason."""

import json

from agile_team import boundary as bd
from agile_team import dependencies, po_tools
from agile_team.boundary import Edge
from agile_team.dependencies import Scope
from agile_team.gates import StoryState, StoryStatus
from agile_team.po_tools import Tools
from agile_team.state import RunState

from .fake_system import Done, FakeSystem
from .test_boundary_runner import NEW, Env
from .test_po_tools import call, open_stories, snapshot


def sprint_of(make_runtime, *, backlog: tuple[str, ...] = ("s2",)):
    """Sprint 1 holds s1 (the start boundary passed); ``backlog`` stories are open."""
    rt = make_runtime()
    t = Tools(rt)
    open_stories(t, "s1", *backlog)
    call(t.start_sprint({"goal": "G", "stories": ["s1"]}))
    rt.state.boundary = None
    rt.state.manager_due, rt.state.po_renew_due = [], []
    rt.save()
    return rt, t


def add(t: Tools, stories, reason: str = "why") -> dict:
    return call(t.add_to_sprint({"stories": stories, "reason": reason}))


def kinds(rt) -> list[str]:
    return [e.kind for e in rt.events.events()]


# ----- AC1: keeps the sprint


def test_add_keeps_the_sprint_and_runs_nothing(make_runtime) -> None:
    rt, t = sprint_of(make_runtime)
    before = (
        rt.state.sprint, rt.state.goal, rt.state.status, rt.state.manager_due,
        rt.state.po_renew_due, rt.state.upstream.team_branch,
    )  # fmt: skip
    n_start = kinds(rt).count("sprint-start")
    out = add(t, ["s2"])
    after = (
        rt.state.sprint, rt.state.goal, rt.state.status, rt.state.manager_due,
        rt.state.po_renew_due, rt.state.upstream.team_branch,
    )  # fmt: skip
    assert after == before and rt.state.boundary is None
    assert rt.state.stories["s2"].sprint == 1
    assert kinds(rt).count("sprint-start") == n_start and "boundary" not in kinds(rt)
    assert out == {"status": "added", "sprint": 1, "stories": ["s2"], "order": rt.state.order}
    assert out["order"][0] == "s2" or out["order"][:2] == ["s1", "s2"]


def test_add_dedupes_ids_keeping_order(make_runtime) -> None:
    _, t = sprint_of(make_runtime, backlog=("s2", "s3"))
    out = add(t, ["s3", "s2", "s3"])
    assert out["stories"] == ["s3", "s2"]


# ----- SA2 placement


def test_placement_puts_ids_first_but_started_stories_stay_first(make_runtime) -> None:
    rt, t = sprint_of(make_runtime, backlog=("s2", "s3"))
    call(t.add_to_sprint({"stories": ["s3"], "reason": "x"}))
    rt.state.stories["s1"].commit = "c" * 40  # s1 is started
    pulled = list(rt.state.pulled)
    out = add(t, ["s2"], "need it")
    assert out["order"].index("s1") < out["order"].index("s2") < out["order"].index("s3")
    assert list(rt.state.pulled) == pulled
    events = [e for e in rt.events.events() if e.kind == "priority"]
    assert events[-1].data["change"] == "sprint" and "need it" in json.dumps(events[-1].data)


def test_listed_ids_go_first_in_the_order_given(make_runtime) -> None:
    _, t = sprint_of(make_runtime, backlog=("s2", "s3"))
    out = add(t, ["s3", "s2"])
    assert out["order"][:2] == ["s3", "s2"]


# ----- SA6 event


def test_one_sprint_add_event_before_the_priority_event(make_runtime) -> None:
    rt, t = sprint_of(make_runtime)
    n = len(rt.events.events())
    add(t, ["s2"])
    new = rt.events.events()[n:]
    adds = [e for e in new if e.kind == "sprint-add"]
    assert len(adds) == 1
    assert adds[0].data == {"sprint": 1, "stories": ["s2"], "reason": "why"}
    assert adds[0].role == "product-owner" and adds[0].story is None
    new_kinds = [e.kind for e in new]
    assert new_kinds.index("sprint-add") < new_kinds.index("priority")


# ----- SA3 refusals


def refused(rt, t: Tools, args: dict, reason: str) -> None:
    rt.save()
    before = snapshot(rt)
    order = list(rt.state.order)
    assert call(t.add_to_sprint(args)) == {"status": "refused", "reason": reason}
    assert snapshot(rt) == before and list(rt.state.order) == order


def test_refused_while_a_boundary_is_pending(make_runtime) -> None:
    rt, t = sprint_of(make_runtime)
    rt.state.boundary = bd.Boundary(Edge.END, 1)
    text = po_tools.SPRINT_REFUSAL_BOUNDARY.format(
        sprint=1, edge=Edge.END, stage=rt.state.boundary.stage, held=""
    )
    refused(rt, t, {"stories": ["s2"], "reason": "why"}, text)
    # a boundary refusal wins over a blank reason (SA3 order)
    refused(rt, t, {"stories": ["s2"], "reason": ""}, text)


def test_refused_with_no_sprint(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    open_stories(t, "s2")
    refused(rt, t, {"stories": ["s2"], "reason": "why"}, po_tools.NO_OPEN_SPRINT.format(sprint=0))


def test_refused_after_the_sprint_has_ended(make_runtime) -> None:
    rt, t = sprint_of(make_runtime)
    rt.state.upstream.closed = 1
    refused(rt, t, {"stories": ["s2"], "reason": "why"}, po_tools.NO_OPEN_SPRINT.format(sprint=1))


def test_refused_for_an_empty_list(make_runtime) -> None:
    rt, t = sprint_of(make_runtime)
    refused(rt, t, {"stories": [], "reason": "why"}, po_tools.priority.NO_STORIES)
    refused(rt, t, {"reason": "why"}, po_tools.priority.NO_STORIES)


def test_refused_for_unknown_done_and_cancelled_ids(make_runtime) -> None:
    rt, t = sprint_of(make_runtime, backlog=("s2", "s3", "s4"))
    rt.state.stories["s3"].status = StoryStatus.DONE
    rt.state.stories["s4"].status = StoryStatus.CANCELLED
    p = po_tools.priority
    refused(rt, t, {"stories": ["s9"], "reason": "w"}, p.UNKNOWN.format(ids="s9"))
    refused(rt, t, {"stories": ["s3"], "reason": "w"}, p.DONE.format(ids="s3"))
    refused(rt, t, {"stories": ["s4"], "reason": "w"}, p.CANCELLED_IDS.format(ids="s4"))


def test_refused_for_a_story_already_in_the_sprint(make_runtime) -> None:
    rt, t = sprint_of(make_runtime)
    refused(
        rt, t, {"stories": ["s2", "s1"], "reason": "w"}, po_tools.ALREADY_IN_SPRINT.format(
            sprint=1, ids="s1"
        ),
    )  # fmt: skip


def with_dependency(make_runtime):
    rt, t = sprint_of(make_runtime, backlog=("s2", "s4"))
    rt.state.stories["s2"].depends_on = ["s4"]
    return rt, t


def test_refused_for_an_unmet_dependency(make_runtime) -> None:
    rt, t = with_dependency(make_runtime)
    text = dependencies.UNMET.format(pairs="s2 on s4")
    refused(rt, t, {"stories": ["s2"], "reason": "w"}, text)


def test_a_dependency_in_the_same_call_is_allowed(make_runtime) -> None:
    rt, t = with_dependency(make_runtime)
    assert add(t, ["s2", "s4"])["status"] == "added"
    assert rt.state.stories["s4"].sprint == 1


def test_a_dependency_already_in_the_sprint_but_not_done_is_allowed(make_runtime) -> None:
    rt, t = with_dependency(make_runtime)
    rt.state.stories["s4"].sprint = 1
    assert add(t, ["s2"])["status"] == "added"


def test_a_done_dependency_is_met(make_runtime) -> None:
    rt, t = with_dependency(make_runtime)
    rt.state.stories["s4"].status = StoryStatus.DONE
    assert add(t, ["s2"])["status"] == "added"


def test_refused_for_a_blank_reason(make_runtime) -> None:
    rt, t = sprint_of(make_runtime)
    text = po_tools.ADD_NEEDS_REASON.format(sprint=1)
    refused(rt, t, {"stories": ["s2"], "reason": "  "}, text)
    refused(rt, t, {"stories": ["s2"]}, text)


def test_dependency_refusal_comes_before_the_reason_one(make_runtime) -> None:
    rt, t = with_dependency(make_runtime)
    refused(rt, t, {"stories": ["s2"], "reason": ""}, dependencies.UNMET.format(pairs="s2 on s4"))


# ----- SA9 restart reason


def test_restart_without_reason_is_refused_while_unfinished(make_runtime) -> None:
    rt, t = sprint_of(make_runtime)
    rt.save()
    before = snapshot(rt)
    out = call(t.start_sprint({"goal": "two", "stories": ["s1", "s2"]}))
    text = po_tools.RESTART_NEEDS_REASON.format(sprint=1, ids="s1")
    assert out == {"status": "refused", "reason": text}
    assert snapshot(rt) == before and rt.state.sprint == 1


def test_restart_with_a_reason_logs_it(make_runtime) -> None:
    rt, t = sprint_of(make_runtime)
    out = call(t.start_sprint({"goal": "two", "stories": ["s1", "s2"], "reason": "pivot"}))
    assert out["sprint"] == 2
    start = [e for e in rt.events.events() if e.kind == "sprint-start"][-1]
    assert start.data["reason"] == "pivot"


def test_restart_needs_no_reason_when_the_sprint_is_finished(make_runtime) -> None:
    rt, t = sprint_of(make_runtime)
    rt.state.stories["s1"].status = StoryStatus.DONE
    out = call(t.start_sprint({"goal": "two", "stories": ["s2"]}))
    assert out["sprint"] == 2
    start = [e for e in rt.events.events() if e.kind == "sprint-start"][-1]
    assert "reason" not in start.data


def test_first_sprint_needs_no_reason(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    open_stories(t, "s1")
    assert call(t.start_sprint({"goal": "G", "stories": ["s1"]}))["sprint"] == 1


# ----- SA8 visible


def test_the_board_sees_the_added_story(make_runtime) -> None:
    rt, t = sprint_of(make_runtime)
    add(t, ["s2"])
    shown = call(t.story_status({}))
    assert shown["stories"]["s2"]["sprint"] == rt.state.sprint


def test_the_end_entry_and_pr_body_include_the_added_story(make_runtime, fake: FakeSystem) -> None:
    env = Env(make_runtime)
    t = Tools(env.rt)
    open_stories(t, "s2")
    env.rt.state.stories["s1"].status = StoryStatus.DONE
    env.rt.state.goal = "G"
    assert add(t, ["s2"])["status"] == "added"
    env.rt.state.stories["s2"].status = StoryStatus.DONE
    fake.reply(("git", "rev-parse", "HEAD"), Done(0, NEW + "\n"))
    entry = env.br._entry(bd.Boundary(Edge.END, 1), "0" * 40)
    assert entry.stories == ["s1", "s2"]
    assert "- s2: s2" in env.br._body(entry)


# ----- schema


def test_schemas_carry_the_new_arguments() -> None:
    assert set(po_tools.SCHEMAS["add_to_sprint"][1]) == {"stories", "reason"}
    assert "reason" in po_tools.SCHEMAS["start_sprint"][1]


# ----- pure helpers


def story(sid: str, status=StoryStatus.ACTIVE, sprint=None, deps=()) -> StoryState:
    s = StoryState(sid, sid, "design", status=status, sprint=sprint)
    s.depends_on = list(deps)
    return s


def test_unmet_refusal_names_pairs_in_order_and_skips_members_and_done() -> None:
    stories = {
        "s3": story("s3"),
        "s4": story("s4"),
        "s6": story("s6", StoryStatus.DONE),
        "s7": story("s7"),
        "s5": story("s5", deps=["s3", "s4", "s6", "s7"]),
        "s8": story("s8", deps=["s3"]),
    }
    scope = Scope(stories, frozenset({"s7"}))
    got = dependencies.unmet_refusal(["s5", "s8"], scope)
    assert got == dependencies.UNMET.format(pairs="s5 on s3, s5 on s4, s8 on s3")


def test_unmet_refusal_is_none_when_all_met() -> None:
    stories = {"s1": story("s1"), "s2": story("s2", deps=["s1"])}
    assert dependencies.unmet_refusal(["s2"], Scope(stories, frozenset({"s1"}))) is None


def test_run_state_sprint_helpers() -> None:
    st = RunState()
    assert not st.sprint_open() and st.sprint_ids() == []
    st.sprint = 2
    st.stories = {
        "a": story("a", StoryStatus.DONE, 2),
        "b": story("b", StoryStatus.ACTIVE, 2),
        "c": story("c", StoryStatus.ACTIVE, 1),
        "d": story("d", StoryStatus.CANCELLED, 2),
    }
    assert st.sprint_ids() == ["a", "b", "d"]
    assert st.unfinished_in_sprint() == ["b"]
    assert st.sprint_open()
    st.upstream.closed = 1
    assert st.sprint_open()
    st.upstream.closed = 2
    assert not st.sprint_open()


def test_run_state_add_to_sprint_changes_only_sprint() -> None:
    st = RunState()
    st.sprint = 1
    st.stories = {"a": story("a"), "b": story("b")}
    st.add_to_sprint(["b"])
    assert st.stories["b"].sprint == 1 and st.stories["a"].sprint is None
    assert st.sprint == 1
