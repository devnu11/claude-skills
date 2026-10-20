"""s159 slice 8: kept-session wiring (K1), interrupted story steps (I1), leaving (E2, E5),
accept-checkout --story (B6) and the waiting heartbeat (I5)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agile_team import cli, live, story_admin, system
from agile_team import state as state_mod
from agile_team.dispatch import StepRequest
from agile_team.gates import StoryState
from agile_team.salvage import Cause
from agile_team.state import RunStatus
from agile_team.story_branches import KeptSession, Landed

from .fake_system import FAKE_IDS, FakeSystem
from .late import Late
from .test_s61 import accept_args, commit_file, stored

reverts = Late("reverts")


def story_in(rt, **kw) -> StoryState:
    story = StoryState("s1", "One", "implement", sprint=1, **kw)
    rt.state.sprint = 1
    rt.state.stories["s1"] = story
    return story


# ---------- K1: a kept session is resumed when nothing changed ----------


def test_a_step_resumes_the_roles_kept_session_k1(make_runtime) -> None:
    rt = make_runtime()
    role = rt.resolve("developer-cli")
    story = story_in(rt)
    story.sessions["developer-cli"] = KeptSession("sess-1", role.model, role.effort, role.provider)
    plan = rt.plan(StepRequest("developer-cli", "go", "s1"))
    assert plan.launch.resume == "sess-1"


def test_a_changed_model_starts_fresh_k1(make_runtime) -> None:
    rt = make_runtime()
    role = rt.resolve("developer-cli")
    story = story_in(rt)
    story.sessions["developer-cli"] = KeptSession(
        "sess-1", "other-model", role.effort, role.provider
    )
    assert rt.plan(StepRequest("developer-cli", "go", "s1")).launch.resume is None


def test_a_role_without_a_kept_session_starts_fresh_k1(make_runtime) -> None:
    rt = make_runtime()
    story_in(rt)
    assert rt.plan(StepRequest("developer-cli", "go", "s1")).launch.resume is None


def test_a_story_step_runs_in_the_story_worktree_b3(make_runtime) -> None:
    rt = make_runtime()
    story = story_in(rt, branch="team/story-s1", worktree_head="a" * 40)
    view = rt.get_story_view(story)
    plan = view.plan(StepRequest("developer-cli", "go", "s1"))
    assert plan.scope.repo == rt.config.run_dir / "worktrees" / "s1"


# ---------- I1: an interrupted story step keeps its worktree ----------


def test_an_interrupted_story_step_records_in_flight_and_makes_no_salvage_commit_i1(
    make_runtime, fake: FakeSystem
) -> None:
    rt = make_runtime()
    story = story_in(rt, branch="team/story-s1", worktree_head="a" * 40)
    view = rt.get_story_view(story)
    asyncio.run(view.take_off(view.plan(StepRequest("developer-cli", "go", "s1"))))
    view.save_interrupted(Cause.CRASH)
    assert story.in_flight is not None and story.in_flight.role == "developer-cli"
    assert rt.state.in_flight is None
    assert not [c for c in fake.commands if "commit" in c.argv]


# ---------- E5: unlanded stories can be cancelled at any step ----------


def case(story: StoryState | None, reason: str = "not needed"):
    return story_admin.Case(story_admin.Act.REQUEST_CANCEL, "s1", reason, story, ())


def test_an_unlanded_story_with_commits_is_cancelled_without_the_code_words_e5() -> None:
    story = StoryState("s1", "t", "implement", code_commits=["c1"])
    assert story_admin.code_refusal(case(story)) is None


def test_a_landed_story_still_needs_the_code_words_e5() -> None:
    story = StoryState("s1", "t", "done", code_commits=["c1"], landed=Landed("m" * 40))
    assert story_admin.code_refusal(case(story)) is not None


def test_a_story_at_land_cannot_be_cancelled_e5() -> None:
    assert "landing" in story_admin.LANDING_REFUSAL
    assert story_admin.LANDING_REFUSAL.format(story="s1") == (
        "story s1 is landing; wait for land to end"
    )


# ---------- E2: reverting an unlanded story drops its branch ----------


def test_reverting_an_unlanded_story_drops_the_branch_with_no_commit_e2(
    make_runtime, fake: FakeSystem
) -> None:
    rt = make_runtime()
    story = story_in(
        rt, branch="team/story-s1", base_sha="b" * 40, pushed="c" * 40, pr=5, replays=2
    )
    story.sessions["developer-cli"] = KeptSession("x", "m", "e", "p")
    out = reverts.Reverter(rt).run({"story": "s1", "reason": "wrong approach"})
    assert out.get("status") in ("reverted", "landing", "asked")
    assert (story.branch, story.base_sha, story.pushed, story.pr) == ("", "", "", None)
    assert story.replays == 2 and story.sessions == {}
    assert not [c for c in fake.commands if "revert" in c.argv]


# ---------- B6: accept-checkout --story while the runner runs ----------


def test_accept_checkout_for_a_story_queues_a_request_while_running_b6(
    configured: Path, key_home: Path, capsys
) -> None:
    run_dir = stored(configured, status=RunStatus.RUNNING)
    system.write_text(run_dir / state_mod.PID_FILE, str(FAKE_IDS[0]))
    args = [*accept_args(configured, key_home), "--story", "s1"]
    assert cli.main(args) == 0
    [request] = system.list_dir(run_dir / "checkouts")
    assert request.name.startswith("c") and json.loads(system.read_text(request)) == {"story": "s1"}


def test_accept_checkout_without_story_still_refuses_a_live_runner_b6(
    configured: Path, key_home: Path, capsys
) -> None:
    run_dir = stored(configured, status=RunStatus.RUNNING)
    system.write_text(run_dir / state_mod.PID_FILE, str(FAKE_IDS[0]))
    commit_file(configured)
    assert cli.main(accept_args(configured, key_home)) == 1


# ---------- I5: the heartbeat says what the run waits for ----------


def test_the_pulse_can_say_what_the_run_waits_for_i5() -> None:
    assert hasattr(live.Pulse, "set_waiting")
