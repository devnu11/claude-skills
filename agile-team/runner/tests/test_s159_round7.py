"""s159 round-6 review: the tests the round 4 to 6 fixes lacked (T2, N9, R1b, R3, N10, N11b, N12,
N13, N14, N15)."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from agile_team import system, test_reports
from agile_team.boundary import Permission, StackEntry
from agile_team.dispatch import MANAGER, Cause, StepKind
from agile_team.gates import StoryState
from agile_team.roles import Handoff, HandoffError
from agile_team.story_ci import StoryPusher

from .late import Late
from .s29_helpers import FakePrs
from .test_s159_landing import checks as fake_checks
from .test_s159_landing import land
from .test_s159_landing import setup as landing_setup

rp = Late("replay")
landing = Late("landing")
HEAD, SPRINT_HEAD, SHA = "a" * 40, "b" * 40, "d" * 40


def story_of(sid: str = "s1", **kw) -> StoryState:
    return StoryState(id=sid, title="t", step="implement", sprint=1, **kw)


def plan_of(story: StoryState | None, role: str = "developer-cli", kind=StepKind.ROLE):
    cancel = SimpleNamespace(requested=False, reason="")
    return SimpleNamespace(
        story=story, role=SimpleNamespace(name=role), cancel=cancel, kind=kind, gated=None
    )


# ---------- N9, T2: the real push_off_loop sends only the commands to threads ----------


class Upstream:
    """Records each lease pushed and answers with ``refusal`` (``None`` is accepted)."""

    def __init__(self, refusal: str | None = None) -> None:
        self.leases: list = []
        self.refusal = refusal

    def push(self, lease) -> str | None:
        self.leases.append(lease)
        return self.refusal


def pusher_for(make_runtime, monkeypatch, refusal: str | None = None, **kw):
    rt = make_runtime(prs=FakePrs())
    rt.state.sprint = 1
    rt.state.upstream.push = kw.get("permission", Permission.YES)
    entry = StackEntry(1, "team/sprint-1", SPRINT_HEAD, SPRINT_HEAD, head=SPRINT_HEAD)
    rt.state.upstream.stack = [entry]
    rt.upstream = Upstream(refusal)
    story = story_of(branch="team/story-s1", worktree_head=HEAD)
    threads: list[str] = []

    async def run_in_thread(fn, *args):
        threads.append(getattr(fn, "__name__", repr(fn)))
        return fn(*args)

    monkeypatch.setattr(system, "run_in_thread", run_in_thread)
    return rt, story, entry, threads


def test_push_off_loop_pushes_the_sprint_branch_then_the_story_and_opens_a_draft_n9(
    make_runtime, monkeypatch
) -> None:
    rt, story, entry, threads = pusher_for(make_runtime, monkeypatch)
    refused = asyncio.run(StoryPusher(rt).push_off_loop(story))
    assert refused is None
    assert [lease.branch for lease in rt.upstream.leases] == ["team/sprint-1", "team/story-s1"]
    assert threads == ["push", "push", "create"]
    assert (entry.pushed, story.pushed, story.pr) == (SPRINT_HEAD, HEAD, 1)


def test_push_off_loop_returns_the_refusal_and_records_nothing_n9(
    make_runtime, monkeypatch
) -> None:
    rt, story, entry, _ = pusher_for(make_runtime, monkeypatch, refusal="stale info")
    # the sprint branch is already up, so only the story's own push is refused
    entry.pushed = SPRINT_HEAD
    refused = asyncio.run(StoryPusher(rt).push_off_loop(story))
    assert refused == "stale info" and story.pushed == "" and story.pr is None


def test_push_off_loop_does_nothing_when_the_head_has_not_moved_n9(
    make_runtime, monkeypatch
) -> None:
    rt, story, _, threads = pusher_for(make_runtime, monkeypatch)
    story.pushed = HEAD
    assert asyncio.run(StoryPusher(rt).push_off_loop(story)) is None
    assert threads == [] and rt.upstream.leases == []


def test_push_off_loop_asks_for_permission_when_unasked_n9(make_runtime, monkeypatch) -> None:
    rt, story, _, _ = pusher_for(make_runtime, monkeypatch, permission=Permission.UNASKED)
    assert asyncio.run(StoryPusher(rt).push_off_loop(story)) is None
    assert rt.state.permission_asked and rt.upstream.leases == []


def test_push_off_loop_keeps_an_existing_pr_n9(make_runtime, monkeypatch) -> None:
    rt, story, _, threads = pusher_for(make_runtime, monkeypatch)
    story.pr = 9
    asyncio.run(StoryPusher(rt).push_off_loop(story))
    assert story.pr == 9 and "create" not in threads


def test_two_stories_open_the_sprint_branch_once_n9(make_runtime, monkeypatch) -> None:
    rt, story, entry, _ = pusher_for(make_runtime, monkeypatch)
    other = story_of("s2", branch="team/story-s2", worktree_head=HEAD)

    async def both() -> None:
        await asyncio.gather(
            StoryPusher(rt).push_off_loop(story), StoryPusher(rt).push_off_loop(other)
        )

    asyncio.run(both())
    sprint_pushes = [lease for lease in rt.upstream.leases if lease.branch == "team/sprint-1"]
    assert len(sprint_pushes) == 1 and entry.pushed == SPRINT_HEAD


# ---------- R1b, T2: the gate's commands run in a thread; the loop uses the verdict ----------


def pregate(make_runtime, monkeypatch, plan, parsed):
    rt = make_runtime()
    threads: list[str] = []

    async def run_in_thread(fn, *args):
        threads.append(fn.__name__)
        return fn(*args)

    monkeypatch.setattr(system, "run_in_thread", run_in_thread)
    rt._evaluate = lambda p, h: "outcome"  # type: ignore[method-assign]
    asyncio.run(rt._run_pregate(plan, parsed))
    return threads


def test_the_pregate_evaluates_the_gate_in_a_thread_and_keeps_the_outcome_r1b(
    make_runtime, monkeypatch
) -> None:
    plan = plan_of(story_of("s1"))
    handoff = Handoff("done")
    assert pregate(make_runtime, monkeypatch, plan, handoff) == ["<lambda>"]
    assert plan.gated == "outcome"


def test_the_pregate_skips_the_manager_r1b(make_runtime, monkeypatch) -> None:
    plan = plan_of(story_of("s1"), role=MANAGER)
    assert pregate(make_runtime, monkeypatch, plan, Handoff("done")) == []
    assert plan.gated is None


def test_the_pregate_skips_a_bad_handoff_r1b(make_runtime, monkeypatch) -> None:
    plan = plan_of(story_of("s1"))
    assert pregate(make_runtime, monkeypatch, plan, HandoffError("bad")) == []
    assert plan.gated is None


def test_the_pregate_skips_steps_with_their_own_effect_r1b(make_runtime, monkeypatch) -> None:
    plan = plan_of(story_of("s1"), kind=StepKind.GATE_FIX)
    assert pregate(make_runtime, monkeypatch, plan, Handoff("done")) == []
    assert plan.gated is None


# ---------- R3, T2: the Manager settles under the main lock ----------


def test_the_manager_settles_under_the_main_lock_once_branches_are_on_r3(make_runtime) -> None:
    rt = make_runtime()
    rt.main_lock = asyncio.Lock()
    rt.state.story_branches = True
    assert rt.settle_lock(plan_of(None, role=MANAGER)) is rt.main_lock


def test_other_roles_and_the_old_flow_take_no_lock_r3(make_runtime) -> None:
    rt = make_runtime()
    rt.main_lock = asyncio.Lock()
    rt.state.story_branches = True
    assert rt.settle_lock(plan_of(story_of(), role="developer-cli")) is not rt.main_lock
    rt.state.story_branches = False
    assert rt.settle_lock(plan_of(None, role=MANAGER)) is not rt.main_lock


def test_a_settle_outside_a_worktree_is_the_plain_settle_r3(make_runtime) -> None:
    rt = make_runtime()
    rt.settle = lambda plan, result: {"plain": True}  # type: ignore[method-assign]
    assert asyncio.run(rt.settle_work(plan_of(story_of()), None)) == {"plain": True}


# ---------- N10: a gone stash is told to the PO with its sha ----------


def test_restore_tells_the_po_the_sha_of_a_gone_stash_n10(make_runtime, monkeypatch) -> None:
    rt = make_runtime()
    posted: list = []
    monkeypatch.setattr(rt.relay, "post", posted.append)
    replay = rp.StoryReplay(rt)
    monkeypatch.setattr(replay, "find_stash_ref", lambda tree, stashed: "")
    replay.restore_edits(None, rp.Stash("s1", True, SHA))
    [note] = posted
    assert SHA in note.text and "gone" in note.text and note.stories == ["s1"]


# ---------- N11b, N15: each gate reports in its own folder ----------


def run_dir_view(make_runtime):
    rt = make_runtime()
    reports = rt.config.run_dir / test_reports.FOLDER
    rt.pipeline.checks.reporting = test_reports.Reporting(folder=reports)
    return rt


def folder_of(runtime) -> Path:
    return runtime.pipeline.checks.reporting.folder


def test_each_story_view_reports_in_its_own_folder_n11b(make_runtime) -> None:
    rt = run_dir_view(make_runtime)
    one, two = rt.get_story_view(story_of("s1")), rt.get_story_view(story_of("s2"))
    run = rt.config.run_dir
    assert folder_of(one) == run / test_reports.STORY_FOLDER / "s1"
    assert folder_of(two) == run / test_reports.STORY_FOLDER / "s2"


def test_no_report_folder_is_inside_another_n11b(make_runtime) -> None:
    rt = run_dir_view(make_runtime)
    run = rt.config.run_dir
    folders = [
        folder_of(rt),
        folder_of(rt.get_story_view(story_of("s1"))),
        folder_of(rt.get_story_view(story_of("s2"))),
        run / test_reports.LANDING_FOLDER,
    ]
    for one in folders:
        assert [f for f in folders if f != one and one in f.parents] == []


def test_the_landing_checks_report_in_the_landing_folder_n11b(
    make_runtime, fake, monkeypatch
) -> None:
    rt, story, _ = landing_setup(make_runtime, fake)
    fake_checks(monkeypatch)
    seen: list[str] = []
    monkeypatch.setattr(
        landing.fullcheck, "full_checks", lambda config, folder: seen.append(folder)
    )
    land(rt, story)
    assert seen == [test_reports.LANDING_FOLDER]


def test_a_story_view_leaves_the_parents_pipeline_alone_n15(make_runtime) -> None:
    rt = run_dir_view(make_runtime)
    before = (rt.pipeline, rt.pipeline.checks, folder_of(rt), rt.pipeline.checks.stages)
    view = rt.get_story_view(story_of("s1"))
    assert view.pipeline is not rt.pipeline and view.pipeline.checks is not rt.pipeline.checks
    assert (rt.pipeline, rt.pipeline.checks, folder_of(rt), rt.pipeline.checks.stages) == before
    assert view.pipeline.checks.stages == view.stage_log.open


def test_a_view_of_a_plain_runtime_does_not_nest_the_folder_n15(make_runtime) -> None:
    rt = run_dir_view(make_runtime)
    view = rt.get_story_view(story_of("s1"))
    assert folder_of(view).parent.parent == rt.config.run_dir  # reports-story/<id>, once
    assert folder_of(view).parts.count(test_reports.STORY_FOLDER) == 1


# ---------- N12, N14: a cancel lets the settle finish, pushes, and still cancels ----------


async def spin(times: int = 5) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


def settling(make_runtime, failure: Exception | None = None):
    rt = make_runtime()
    rt.worktree_of = "s1"
    release, log = asyncio.Event(), []

    async def threaded(plan, result):
        await release.wait()
        log.append("settled")
        if failure:
            raise failure
        return {"status": "done"}

    async def applied(plan, settled):
        log.append("pushed")
        return settled

    async def executed(plan):
        return None

    rt._settle_threaded, rt.apply_settled, rt._execute = threaded, applied, executed  # type: ignore[method-assign]
    return rt, release, log


async def cancel_twice(task: asyncio.Future, release: asyncio.Event) -> None:
    await spin()
    task.cancel()
    await spin()
    task.cancel()
    await spin()
    assert not task.done()  # neither cancel reached the settle
    release.set()


def test_a_twice_cancelled_settle_finishes_pushes_once_and_still_cancels_n14(
    make_runtime,
) -> None:
    rt, release, log = settling(make_runtime)

    async def scenario() -> None:
        task = asyncio.ensure_future(rt._settle_uncut(plan_of(story_of()), None))
        await cancel_twice(task, release)
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert log == ["settled", "pushed"]


def test_an_uncancelled_settle_returns_its_report_and_does_not_push_here_n14(
    make_runtime,
) -> None:
    rt, release, log = settling(make_runtime)
    release.set()
    got = asyncio.run(rt._settle_uncut(plan_of(story_of()), None))
    assert got == {"status": "done"} and log == ["settled"]


def test_a_cancelled_planned_step_saves_as_interrupted_after_its_push_n12(make_runtime) -> None:
    rt, release, log = settling(make_runtime)
    saved: list[Cause] = []
    rt.save_interrupted = saved.append  # type: ignore[method-assign]

    async def scenario() -> None:
        task = asyncio.ensure_future(rt._run_planned(plan_of(story_of())))
        await cancel_twice(task, release)
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert log == ["settled", "pushed"] and saved == [Cause.SIGTERM]


def test_a_settle_error_during_a_cancel_reaches_step_failed_not_a_bare_cancel_n14(
    make_runtime,
) -> None:
    boom = RuntimeError("boom")
    rt, release, log = settling(make_runtime, failure=boom)
    failed: list[Exception] = []
    rt._step_failed = lambda plan, exc: failed.append(exc) or {"status": "failed"}  # type: ignore[method-assign]

    async def scenario() -> dict:
        task = asyncio.ensure_future(rt._run_planned(plan_of(story_of())))
        await cancel_twice(task, release)
        return await task

    assert asyncio.run(scenario()) == {"status": "failed"}
    assert failed == [boom] and log == ["settled"]


# ---------- N13: the pulse names the settling story step ----------


def test_the_pulse_names_the_settling_for_a_story_steps_head_and_tail_n13(make_runtime) -> None:
    rt = make_runtime()
    seen: list[tuple[str, str | None]] = []

    @contextmanager
    def doing(what: str, story: str | None = None):
        seen.append((what, story))
        yield

    async def pregate(plan, parsed) -> None:
        return None

    rt.pulse.doing = doing  # type: ignore[method-assign]
    rt._settle_head = lambda plan, result: ("report", "parsed")  # type: ignore[method-assign]
    rt._settle_tail = lambda plan, parsed, report: {"ok": 1}  # type: ignore[method-assign]
    rt._run_pregate = pregate  # type: ignore[method-assign]
    assert asyncio.run(rt._settle_threaded(plan_of(story_of()), None)) == {"ok": 1}
    assert len(seen) == 2 and seen[0] == seen[1]
    assert seen[0][1] == "s1"  # s181 CH5: the chore carries the story id
    assert seen[0].startswith("settling ") and "s1" in seen[0]
