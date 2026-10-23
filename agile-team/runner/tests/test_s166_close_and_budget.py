"""s166: a merged PR counts as closed (REQ-174); costless running work holds no reserve."""

from __future__ import annotations

import json

import pytest
from agile_team import upstream as up
from agile_team.boundary import StepKind
from agile_team.gates import StoryState
from agile_team.router import BOUNDARY_KEY, Work

from .late import Late
from .test_s159_landing import checks, land
from .test_s159_landing import setup as land_setup

sched = Late("scheduler")
MERGED_TEXT = "can't be closed because it was already merged"


class Gh:
    """A scripted ``gh``: the close and the view each reply as told; every call is kept."""

    def __init__(self, close: tuple[int, str], view: tuple[int, str]) -> None:
        self.close_reply, self.view_reply = close, view
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        self.calls.append(argv)
        return self.close_reply if argv[2] == "close" else self.view_reply


def state(name: str) -> tuple[int, str]:
    return 0, json.dumps({"state": name})


# ---------- AC1: GhPrs.close ----------


def test_a_failed_close_of_a_merged_pr_returns_after_the_close_then_the_view() -> None:
    gh = Gh((1, MERGED_TEXT), state("MERGED"))
    up.GhPrs(gh).close(7, "note")
    assert [c[2] for c in gh.calls] == ["close", "view"]
    assert gh.calls[1][:3] == ["gh", "pr", "view"] and "state" in gh.calls[1]


def test_the_state_decides_not_the_message() -> None:
    gh = Gh((1, "boom"), state("MERGED"))
    up.GhPrs(gh).close(7, "note")
    assert len(gh.calls) == 2


@pytest.mark.parametrize("name", ["OPEN", "CLOSED"])
def test_a_failed_close_of_an_unmerged_pr_raises_the_close_error(name: str) -> None:
    gh = Gh((1, "  boom\n"), state(name))
    with pytest.raises(up.UpstreamError) as err:
        up.GhPrs(gh).close(7, "note")
    assert str(err.value) == "boom"


@pytest.mark.parametrize(
    "view", [(1, "not found"), (0, "not json"), (0, "[]"), (0, '{"x": 1}'), (0, "")]
)
def test_an_unreadable_state_raises_the_close_error(view: tuple[int, str]) -> None:
    gh = Gh((1, "close failed"), view)
    with pytest.raises(up.UpstreamError) as err:
        up.GhPrs(gh).close(7, "note")
    assert str(err.value) == "close failed"


def test_a_failed_view_of_a_merged_state_is_not_merged() -> None:
    gh = Gh((1, "close failed"), (1, json.dumps({"state": "MERGED"})))
    with pytest.raises(up.UpstreamError):
        up.GhPrs(gh).close(7, "note")


def test_a_successful_close_makes_one_call_and_never_views() -> None:
    gh = Gh((0, ""), state("MERGED"))
    up.GhPrs(gh).close(7, "the note")
    [argv] = gh.calls
    assert argv[argv.index("--comment") + 1] == "the note"


@pytest.mark.parametrize("close", [(0, ""), (1, MERGED_TEXT)])
def test_no_call_is_a_comment(close: tuple[int, str]) -> None:
    gh = Gh(close, state("MERGED"))
    up.GhPrs(gh).close(7, "note")
    assert all(c[2] != "comment" for c in gh.calls)


def test_a_landing_whose_story_pr_is_already_merged_completes(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, entry = land_setup(make_runtime, fake)
    rt.prs.close = up.GhPrs(Gh((1, MERGED_TEXT), state("MERGED"))).close
    out = land(rt, story)
    assert out["gate"]["verdict"] == "pass" and story.landed is not None
    assert entry.pr is not None


# ---------- AC2: the budget ----------


def story(sid: str = "s1") -> StoryState:
    return StoryState(id=sid, title="T", step="implement", sprint=1)


def scheduler(make_runtime, reserve: float = 1.0, budget: float = 100.0):
    rt = make_runtime()
    rt.state.sprint = 1
    rt.config.team.budget_usd = budget
    rt.config.team.step_reserve_usd = reserve
    return sched.Scheduler(rt, None)


def role_work(s: StoryState) -> Work:
    return Work("developer-cli", s, "brief")


def test_a_running_landing_does_not_crash_the_budget_check(make_runtime) -> None:
    a, b = story("s1"), story("s2")
    s = scheduler(make_runtime)
    s.running["s1"] = Work("runner", a, "", StepKind.LAND)
    assert s.check_budget(role_work(b)) is None


@pytest.mark.parametrize("new", ["manager", "developer-cli"])
def test_a_running_boundary_does_not_crash_the_budget_check(make_runtime, new: str) -> None:
    b = story("s2")
    s = scheduler(make_runtime)
    s.running[BOUNDARY_KEY] = Work("runner", None, "", StepKind.BOUNDARY)
    work = Work(new, None if new == "manager" else b, "brief")
    assert s.check_budget(work) is None


def test_a_running_landing_adds_nothing_but_a_running_role_step_does(make_runtime) -> None:
    a, b = story("s1"), story("s2")
    s = scheduler(make_runtime, reserve=6.0, budget=10.0)
    s.running["s1"] = Work("runner", a, "", StepKind.LAND)
    assert s.check_budget(role_work(b)) is None
    s.running["s1"] = role_work(a)
    assert "budget" in (s.check_budget(role_work(b)) or "")


def test_costly_work_drops_costless_kinds_and_keeps_the_rest_in_order(make_runtime) -> None:
    s = scheduler(make_runtime)
    kinds = [
        StepKind.LAND,
        StepKind.BOUNDARY,
        StepKind.ROLE,
        StepKind.TEAM_FIX,
        StepKind.REBASE_FIX,
        StepKind.GATE_FIX,
    ]
    for i, kind in enumerate(kinds):
        s.running[f"k{i}"] = Work("developer-cli", None, "", kind)
    new = Work("manager", None, "new")
    got = s.select_costly_work(new)
    assert [w.kind for w in got] == [*kinds[2:], StepKind.ROLE] and got[-1] is new


def test_a_new_costless_work_still_starts_at_once(make_runtime) -> None:
    s = scheduler(make_runtime, reserve=50.0, budget=10.0)
    assert s.check_budget(Work("runner", None, "", StepKind.LAND)) is None
