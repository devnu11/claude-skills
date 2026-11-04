"""s180 C10: no story branch is forked while a landing runs."""

from __future__ import annotations

from agile_team.boundary import Permission, StepKind
from agile_team.router import Work
from agile_team.scheduler import REVERT_KEY, WAIT_TEXTS
from agile_team.waits import WaitReason

from .test_s159_scheduler import scheduler, story, work

TEXT = "waits for the running landing before forking its branch"


def test_the_wait_reason_and_text_c10() -> None:
    assert WaitReason.LANDING_FORK == "landing_fork"
    assert WAIT_TEXTS[WaitReason.LANDING_FORK] == TEXT


def test_a_step_without_a_worktree_waits_while_a_land_runs_c10(make_runtime) -> None:
    lander, fresh = story("s1", "land"), story("s2")
    rt, s = scheduler(make_runtime, lander, fresh)
    rt.state.upstream.push = Permission.YES
    s.running["land"] = Work("runner", lander, "", StepKind.LAND)
    assert s.check_fork(work(fresh)) == TEXT
    assert s.can_start(work(fresh)) == TEXT


def test_a_step_without_a_worktree_waits_while_a_revert_landing_runs_c10(make_runtime) -> None:
    fresh = story("s2")
    _, s = scheduler(make_runtime, fresh)
    s.tasks[REVERT_KEY] = object()
    assert s.check_fork(work(fresh)) == TEXT


def test_a_step_with_a_worktree_does_not_wait_c10(make_runtime) -> None:
    lander, forked = story("s1", "land"), story("s2", worktree_head="a" * 40)
    _, s = scheduler(make_runtime, lander, forked)
    s.running["land"] = Work("runner", lander, "", StepKind.LAND)
    assert s.check_fork(work(forked)) is None


def test_nothing_waits_while_no_landing_runs_c10(make_runtime) -> None:
    fresh = story("s2")
    _, s = scheduler(make_runtime, fresh)
    assert s.check_fork(work(fresh)) is None
    assert s.is_landing is False


def test_a_running_land_makes_is_landing_true_c10(make_runtime) -> None:
    lander = story("s1", "land")
    _, s = scheduler(make_runtime, lander)
    s.running["land"] = Work("runner", lander, "", StepKind.LAND)
    assert s.is_landing is True


def test_a_running_role_step_is_not_a_landing_c10(make_runtime) -> None:
    a = story("s1", worktree_head="a" * 40)
    _, s = scheduler(make_runtime, a)
    s.running["s1"] = work(a)
    assert s.is_landing is False


def test_a_storyless_step_does_not_wait_c10(make_runtime) -> None:
    lander = story("s1", "land")
    _, s = scheduler(make_runtime, lander)
    s.running["land"] = Work("runner", lander, "", StepKind.LAND)
    assert s.check_fork(Work("devops", None, "brief", StepKind.ROLE)) is None


def test_a_land_step_itself_does_not_wait_c10(make_runtime) -> None:
    lander, other = story("s1", "land"), story("s2", "land")
    _, s = scheduler(make_runtime, lander, other)
    s.running["land"] = Work("runner", lander, "", StepKind.LAND)
    assert s.check_fork(Work("runner", other, "", StepKind.LAND)) is None
