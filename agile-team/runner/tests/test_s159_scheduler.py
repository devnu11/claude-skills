"""s159 slice 7: Scheduler (C1 to C4, C10), Router.works, Runtime.at (B3), the land step (L1)."""

from __future__ import annotations

import asyncio

import pytest
from agile_team import gates, router
from agile_team.boundary import StepKind
from agile_team.gates import Outcome, StoryState, StoryStatus, Verdict
from agile_team.po_tools import Start
from agile_team.router import Work

from .late import Late

sched = Late("scheduler")


def story(sid: str, step: str = "implement", **kw) -> StoryState:
    return StoryState(id=sid, title=f"T{sid}", step=step, sprint=1, **kw)


def setup(make_runtime, *stories: StoryState, **team):
    rt = make_runtime()
    rt.state.sprint = 1
    rt.state.stories = {s.id: s for s in stories}
    for key, value in team.items():
        setattr(rt.config.team, key, value)
    return rt


def scheduler(make_runtime, *stories: StoryState, **team):
    rt = setup(make_runtime, *stories, **team)
    return rt, sched.Scheduler(rt, Start("task"))


def work(s: StoryState, kind: StepKind = StepKind.ROLE) -> Work:
    return Work("developer-cli", s, "brief", kind)


# ---------- constants and shape ----------


def test_constants_c1() -> None:
    assert sched.POLL_S == 5.0 and sched.MANAGER_KEY == "manager"


def test_a_new_scheduler_has_no_tasks_and_is_not_limited_c1(make_runtime) -> None:
    _, s = scheduler(make_runtime)
    assert s.tasks == {} and s.limited is False
    assert isinstance(s.main_lock, asyncio.Lock)


# ---------- can_start ----------


def test_an_open_story_may_always_run_c3(make_runtime) -> None:
    a, b = story("s1", worktree_head="a" * 40), story("s2")
    _, s = scheduler(make_runtime, a, b, max_open_stories=1)
    assert s.can_start(work(a)) is None


def test_a_story_without_a_worktree_waits_at_the_cap_c3(make_runtime) -> None:
    a, b = story("s1", worktree_head="a" * 40), story("s2")
    _, s = scheduler(make_runtime, a, b, max_open_stories=1)
    assert "max_open_stories" in s.can_start(work(b))


def test_a_story_without_a_worktree_starts_under_the_cap_c3(make_runtime) -> None:
    b = story("s2")
    _, s = scheduler(make_runtime, b, max_open_stories=2)
    assert s.can_start(work(b)) is None


def test_only_the_head_of_the_land_queue_lands_l2(make_runtime) -> None:
    a, b = story("s1", "land"), story("s2", "land")
    rt, s = scheduler(make_runtime, a, b)
    rt.state.land_queue = ["s1", "s2"]
    assert s.can_start(work(a, StepKind.LAND)) is None
    assert "s1" in s.can_start(work(b, StepKind.LAND))


def test_a_land_waits_for_the_push_permission_l3(make_runtime) -> None:
    a = story("s1", "land")
    rt, s = scheduler(make_runtime, a)
    rt.state.land_queue = ["s1"]
    assert "permission" in (s.can_start(work(a, StepKind.LAND)) or "")


def test_a_dependency_at_land_still_blocks_d1(make_runtime) -> None:
    a, b = story("s1", "land"), story("s2", depends_on=["s1"])
    _, s = scheduler(make_runtime, a, b)
    assert s.can_start(work(b)) is not None


def test_the_budget_edge_starts_nothing_c4(make_runtime) -> None:
    a = story("s1")
    rt, s = scheduler(make_runtime, a, budget_usd=10.0, step_reserve_usd=1.0)
    rt.ledger.total = lambda: 9.5
    assert "budget" in (s.can_start(work(a)) or "")


# ---------- ended, stop, limit ----------


def test_a_stop_request_ends_the_run_c10(make_runtime) -> None:
    _, s = scheduler(make_runtime)
    s.runtime.stop_requested = lambda: True
    assert s.ended() is True


def test_waiting_on_the_human_does_not_end_the_run_i4(make_runtime) -> None:
    rt, s = scheduler(make_runtime, story("s1"))
    rt.state.mark(gates_status("running"), "waiting for the PO")
    assert s.ended() is False


def gates_status(name: str):
    from agile_team.state import RunStatus

    return RunStatus(name)


# ---------- Router.works / pickers ----------


def test_works_offers_every_startable_story_in_order_c1(make_runtime) -> None:
    rt = setup(make_runtime, story("s1"), story("s2"))
    ws = router.Router(rt).works(frozenset())
    assert [w.story.id for w in ws if w.story] == ["s1", "s2"]


def test_works_skips_running_keys_c2(make_runtime) -> None:
    rt = setup(make_runtime, story("s1"), story("s2"))
    ws = router.Router(rt).works(frozenset({"s1"}))
    assert [w.story.id for w in ws if w.story] == ["s2"]


def test_a_land_story_is_picked_as_a_land_step_l1(make_runtime) -> None:
    rt = setup(make_runtime, story("s1", "land"))
    [w] = router.Router(rt).works(frozenset())
    assert w.kind is StepKind.LAND


def test_a_story_with_a_queued_rebase_is_picked_as_a_story_rebase_s1(make_runtime) -> None:
    from agile_team.story_branches import StoryRebase

    a = story("s1", rebase=StoryRebase("o", "b", "old", "new", ["a.py"], "developer"))
    rt = setup(make_runtime, a)
    [w] = router.Router(rt).works(frozenset())
    assert w.kind is StepKind.STORY_REBASE


def test_the_router_has_the_request_queue_methods_c1() -> None:
    for name in ("apply_queues", "idle", "news", "works"):
        assert hasattr(router.Router, name)


# ---------- gates: land is last (L1) ----------


def test_a_pass_at_acceptance_moves_to_land_l1(make_runtime) -> None:
    rt = setup(make_runtime, story("s1", "acceptance"))
    rt.pipeline.advance(rt.state.stories["s1"], Outcome(Verdict.PASS, "ok"))
    assert rt.state.stories["s1"].step == "land"
    assert rt.state.stories["s1"].status is StoryStatus.ACTIVE


def test_only_a_pass_at_land_marks_the_story_done_l1(make_runtime) -> None:
    rt = setup(make_runtime, story("s1", "land"))
    rt.pipeline.advance(rt.state.stories["s1"], Outcome(Verdict.PASS, "landed"))
    assert rt.state.stories["s1"].status is StoryStatus.DONE


def test_land_is_the_runners_text_l1() -> None:
    assert gates.LAND_IS_RUNNERS == "story {id} is at land; the runner lands it"


# ---------- Runtime.at (B3) ----------


def test_runtime_at_views_the_worktree_b3(make_runtime) -> None:
    rt = setup(make_runtime, story("s1", worktree_head="a" * 40))
    view = rt.at(rt.state.stories["s1"])
    assert view.config.repo == rt.config.run_dir / "worktrees" / "s1"
    assert view.config.run_dir == rt.config.run_dir
    assert view.git.repo == view.config.repo
    assert view.state is rt.state and view.events is rt.events and view.ledger is rt.ledger
    assert view.step_meter is None and view is not rt


def test_runtime_has_the_split_step_methods_c6() -> None:
    from agile_team.dispatch import Runtime

    for name in ("take_off", "settle_work", "apply_settled", "at"):
        assert hasattr(Runtime, name)


def test_runtime_halted_by_lives_in_the_shared_flags_c6(make_runtime) -> None:
    rt = setup(make_runtime)
    view = rt.at(story("s1"))
    rt.halted_by = "x"
    assert view.halted_by == "x" and rt.flags.halted_by == "x"


@pytest.mark.parametrize("name", ["pipeline_for", "writer"])
def test_runtime_carries_the_new_collaborators_c6(make_runtime, name: str) -> None:
    rt = setup(make_runtime)
    assert hasattr(rt, name)
