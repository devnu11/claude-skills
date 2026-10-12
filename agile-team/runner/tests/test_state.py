"""Run state round trip."""

import json

from agile_team import state, system
from agile_team.gates import StoryState, StoryStatus

from .fake_system import FAKE_REPO


def test_round_trip() -> None:
    tmp_path = FAKE_REPO
    assert state.load(tmp_path).status == "idle"
    st = state.RunState(cadence="until-blocker", sprint=2)
    st.stories["s1"] = StoryState("s1", "Add", "tests", rounds=1)
    st.overrides["developer"] = state.ModelOverride("opus", "high", "hard")
    state.save(tmp_path / "run", st)
    back = state.load(tmp_path / "run")
    assert back.stories["s1"].rounds == 1
    assert back.runtime_overrides("developer") == {
        "model": "opus",
        "effort": "high",
        "provider": "anthropic",
    }
    assert back.runtime_overrides("architect") == {}


def test_legacy_story_without_sprint_loads_into_backlog() -> None:
    legacy = {
        "sprint": 3,
        "stories": {
            "s1": {
                "id": "s1",
                "title": "Add",
                "step": "implement",
                "rounds": 2,
                "status": "active",
                "commit": "abc",
            }
        },
    }
    back = state.RunState.from_json(json.dumps(legacy))
    s1 = back.stories["s1"]
    assert s1.sprint is None
    assert (s1.step, s1.rounds, s1.status, s1.commit) == ("implement", 2, "active", "abc")
    assert back.sprint == 3


def test_story_sprint_round_trips() -> None:
    st = state.RunState(sprint=2)
    st.stories["s1"] = StoryState("s1", "Add", "tests", sprint=2)
    st.stories["s2"] = StoryState("s2", "Two", "design")
    back = state.RunState.from_json(st.to_json())
    assert back.stories["s1"].sprint == 2 and back.stories["s2"].sprint is None


def _sprint_state() -> state.RunState:
    st = state.RunState(sprint=1)
    st.stories["s1"] = StoryState("s1", "One", "tests", sprint=1)
    st.stories["s2"] = StoryState("s2", "Two", "done", status=StoryStatus.DONE, sprint=1)
    st.stories["s3"] = StoryState("s3", "Three", "design")
    st.stories["s4"] = StoryState("s4", "Legacy", "done", status=StoryStatus.DONE)
    return st


def test_unknown_stories_keeps_order() -> None:
    st = _sprint_state()
    assert st.unknown_stories(["s9", "s1", "s7"]) == ["s9", "s7"]
    assert st.unknown_stories([]) == []


def test_begin_sprint_replaces_scope() -> None:
    st = _sprint_state()
    st.begin_sprint(["s3"])
    assert st.sprint == 2
    sprints = {k: v.sprint for k, v in st.stories.items()}
    assert sprints == {"s1": None, "s2": 1, "s3": 2, "s4": None}


def test_begin_sprint_never_moves_done_stories() -> None:
    st = _sprint_state()
    st.begin_sprint(["s2", "s4", "s1"])
    sprints = {k: v.sprint for k, v in st.stories.items()}
    assert sprints == {"s1": 2, "s2": 1, "s3": None, "s4": None}


# ----- s19: new story and run fields --------------------------------------------


def test_new_fields_default_for_old_state_files() -> None:
    from agile_team.gates import PreviousStep  # noqa: F401

    legacy = {"stories": {"s1": {"id": "s1", "title": "t", "step": "design", "sprint": 1}}}
    back = state.RunState.from_json(json.dumps(legacy))
    s1 = back.stories["s1"]
    assert (s1.developer, s1.po_developer, s1.hold, s1.note, s1.previous) == (
        None,
        None,
        None,
        "",
        None,
    )
    assert back.scribe_due == [] and back.delivered is None


def test_story_defaults_come_after_sprint() -> None:
    s = StoryState(
        "s1", "t", "design", 0, StoryStatus.ACTIVE, None, None, 1, "dev", "po", "held", "n"
    )
    assert (s.sprint, s.developer, s.po_developer, s.hold, s.note, s.previous) == (
        1,
        "dev",
        "po",
        "held",
        "n",
        None,
    )


def test_previous_step_round_trips_as_a_dataclass() -> None:
    from agile_team.gates import PreviousStep

    st = state.RunState(sprint=1, scribe_due=["s1"], delivered=["m1"])
    prev = PreviousStep("code-reviewer", "changes_requested", "s", "bounce", "r", "developer-gui")
    st.stories["s1"] = StoryState("s1", "t", "implement", sprint=1, previous=prev, hold="stopped")
    st.stories["s2"] = StoryState("s2", "t", "design")
    back = state.RunState.from_json(st.to_json())
    assert back.stories["s1"].previous == prev
    assert isinstance(back.stories["s1"].previous, PreviousStep)
    assert back.stories["s2"].previous is None and back.stories["s1"].hold == "stopped"
    assert back.scribe_due == ["s1"] and back.delivered == ["m1"]


def test_previous_step_defaults() -> None:
    from agile_team.gates import PreviousStep

    p = PreviousStep("architect", "done")
    assert (p.summary, p.verdict, p.reason, p.next_role) == ("", "", "", None)


# ----- s29: boundary, upstream, goal ----------------------------------------


def test_boundary_and_upstream_round_trip() -> None:
    from agile_team import boundary as bd
    from agile_team.loops import Setback

    st = state.RunState(goal="ship it")
    fail = bd.Failure(bd.Stage.CHECK, bd.FixCase.TEAM_CHECK, "lint broke", files=["a.py"])
    boundary = bd.Boundary(bd.Edge.END, 2, stage=bd.Stage.CHECK, failure=fail, rounds=1)
    boundary.hold = bd.BoundaryHold.ESCALATED
    boundary.streak = [bd.setback(boundary, fail)]
    st.boundary = boundary
    entry = bd.StackEntry(2, "team/sprint-2", "aa", "bb", stories=["s1"], pr=7, mode="draft")
    st.upstream = bd.UpstreamState(push=bd.Permission.YES, stack=[entry], last_end="bb", closed=1)
    back = state.RunState.from_json(st.to_json())
    assert back.goal == "ship it"
    assert back.boundary == boundary and isinstance(back.boundary.failure, bd.Failure)
    assert isinstance(back.boundary.streak[0], Setback) and back.boundary.edge is bd.Edge.END
    assert back.upstream == st.upstream and isinstance(back.upstream.stack[0], bd.StackEntry)
    assert back.upstream.push is bd.Permission.YES


def test_older_state_loads_with_no_boundary_and_empty_upstream() -> None:
    from agile_team import boundary as bd

    back = state.RunState.from_json('{"sprint": 2, "status": "idle"}')
    assert back.boundary is None and back.goal == ""
    assert back.upstream == bd.UpstreamState()
    assert back.upstream.push == "unasked" and back.upstream.closed == 0


def test_order_round_trips_and_legacy_loads_empty() -> None:
    tmp_path = FAKE_REPO / "run"
    st = state.RunState(order=["s3", "s1"])
    state.save(tmp_path, st)
    assert state.load(tmp_path).order == ["s3", "s1"]
    path = tmp_path / "state.json"
    raw = json.loads(system.read_text(path))
    del raw["order"]
    system.write_text(path, json.dumps(raw))
    assert state.load(tmp_path).order == []
