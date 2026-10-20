"""The parallel scheduler (s159 C1 to C10): story steps, lands and the PO's turns run side by side.

Each tick the scheduler drains the writer, applies the request queues, starts what the router
offers within the caps, and hands the PO its queued passes one turn at a time. A story has one
task at a time, keyed by its id; the Manager review and a boundary's fix step have keys of their
own. Everything that changes the run's state happens on the run_loop thread.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import replace
from typing import Any

from . import budget_reserve, dependencies, handover, system
from .boundary import Permission, StepKind
from .ci import CiVerdict
from .dispatch import MANAGER, NOT_NOTED, Runtime, StepRequest, StepResult
from .gates import FINISHED, Outcome, StoryState, Verdict
from .halt import crash_halt
from .handover import Pass, Scope, Trigger
from .landing import Lander
from .landing_queue import LandingQueue
from .loops import Author
from .overlaps import Overlaps
from .po_desk import PoDesk
from .po_tools import (
    RESUME_NOTE,
    PoRun,
    PoTurn,
    Start,
    first_prompt,
    resume_prompt,
    resume_session,
)
from .relay import Note
from .reverts import Call, Reverter
from .router import BOUNDARY_KEY, MANAGER_KEY, POLL_S, Router, Work, find_key
from .state import RunStatus
from .story_ci import StoryCiPoll
from .waits import WaitReason
from .workspaces import Workspaces

__all__ = ["BOUNDARY_KEY", "MANAGER_KEY", "POLL_S", "Scheduler"]

FIX_STEPS = frozenset({StepKind.TEAM_FIX, StepKind.REBASE_FIX})
COSTLESS = frozenset({StepKind.LAND, StepKind.BOUNDARY})
REVERT_KEY = "revert"
NOTED_BY_RUNNER = frozenset({"refused", "error", "land"})
WAITS = frozenset({"waiting"})
WAIT_TEXTS = {
    WaitReason.LAND_QUEUE: "waits to land after {id}",
    WaitReason.PERMISSION: "waits for the push permission",
    WaitReason.OPEN_CAP: "waits for a free worktree (max_open_stories {n})",
    WaitReason.RESERVE: "waits for budget headroom: {why}",
}
ONE_AT_A_TIME = "story branches are off: one step at a time"
REVERT_REFUSED = "reverting story {story} was refused: {why}. The sprint branch is untouched."
LATER = " Later stories touching the same files: {ids}."


BOUNDARY_FIXES = (StepKind.TEAM_FIX, StepKind.REBASE_FIX)


class Scheduler:
    """Runs the pipeline's tasks and the PO's turns until the run ends."""

    follow_task: asyncio.Task[None] | None = None

    def __init__(self, runtime: Runtime, start: Start) -> None:
        self.runtime = runtime
        self.start = start
        self.po = PoRun(runtime, start)
        self.router: Router = self.po.router
        self.desk = PoDesk()
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.running: dict[str, Work] = {}
        self.limited = False
        self.main_lock = self.po.main_lock
        self.paused_by: str | None = None
        self.po_task: asyncio.Task[None] | None = None
        self.opening: PoTurn | None = None
        self.lead = ""
        self.steps = 0
        self.hurry = False
        self.turns = 0
        self.told_permission = False
        self.result = StepResult("", 0.0)
        runtime.main_lock = self.main_lock
        self.lander = Lander(runtime, self.main_lock)
        runtime.landings = self.landings = LandingQueue(runtime)
        self.ci_poll = StoryCiPoll(runtime)
        self.followed_at = float("-inf")
        self.ci_task: asyncio.Task[None] | None = None

    # ----- the run

    async def run(self) -> StepResult:
        """C1: run until the run ends; the last PO turn's result."""
        rt = self.runtime
        rt.writer.bind(asyncio.get_running_loop(), asyncio.current_task())  # type: ignore[arg-type]
        try:
            self.begin()
            await self.run_loop()
        finally:
            await self.stop_tasks()
            rt.pulse.set_waiting(None)
            rt.writer.release()
        self.finish_run()
        return self.result

    def begin(self) -> None:
        """The run's first moves: the setup the sequential driver made, then the opening turn."""
        rt, state = self.runtime, self.runtime.state
        rt.halted_by = None
        if state.delivered is None:
            state.delivered = list(rt.relay.answers())
        state.unsaved = None
        state.mark(RunStatus.RUNNING)
        rt.save()
        self.opening = None if rt.enforce_ceiling() else self.open_turn()

    def open_turn(self) -> PoTurn | None:
        """The PO's first turn: a kickoff, or the resume note with the human's task."""
        told = self.po._take_interrupted()
        session = resume_session(self.runtime, self.start)
        if session is None:
            return PoTurn(_join_prompts(first_prompt(self.runtime, self.start), told), None)
        if self.start.task or told:
            return PoTurn(_join_prompts(resume_prompt(self.start.task), told), session)
        self.lead = RESUME_NOTE + "\n\n"
        return None

    def finish_run(self) -> None:
        """The run's last status: idle unless something else already ended it."""
        state = self.runtime.state
        if state.status is RunStatus.RUNNING:
            state.mark(RunStatus.IDLE, self.po.ended_by)
            self.runtime.save()

    async def run_loop(self) -> None:
        """Tick, start what can start, then wait for the next change."""
        while True:
            self.tick()
            if self.is_finished:
                return
            self.start_turn()
            self.start_work()
            self.show_waiting()
            if not (self.hurry or self.is_finished or self.has_pass_to_hear):
                await self.wait_for_change()
            self.hurry = False

    @property
    def has_pass_to_hear(self) -> bool:
        """A pass queued by this iteration's work (the idle report) waits for a PO turn (s164)."""
        return self.po_task is None and not self.desk.is_empty

    def tick(self) -> None:
        """C1 steps 1 to 4: drain the writer, reap done tasks, queues, guard, passes."""
        rt = self.runtime
        rt.writer.drain()
        self.collect_done()
        if self.ended():
            return
        if self.may_apply_queues:
            if rt.checkout_moved():
                return
            self.router.apply_queues()
            Overlaps(rt).lift_due()
        self.queue_news()
        self.ask_permission()
        self.poll_story_ci()
        self.follow_boundary()

    @property
    def may_apply_queues(self) -> bool:
        """K1, B5: the request queues wait while git moves the checkout or a stage task runs."""
        return not self.main_lock.locked() and BOUNDARY_KEY not in self.tasks

    @property
    def is_finished(self) -> bool:
        """The run is over: it ended (or the PO has nothing left to hear) and nothing is running."""
        busy = bool(self.tasks) or self.po_task is not None
        return not busy and (self.ended() or self.po.ended_by is not None)

    def ended(  # house-rules: allow verb-name, query-property -- name fixed by the s159 tests
        self,
    ) -> bool:
        """C10, I4: a halt, a stop, a re-pin or a halting status ends the run; waiting does not."""
        rt = self.runtime
        stopped = rt.stop_requested() or rt.halted_by is not None or rt.state.halted()
        return bool(stopped or rt.state.repin)

    # ----- reaping and stopping

    def collect_done(self) -> None:
        """Forget the tasks that are done; a task that raised ends the run (the caller halts)."""
        for key, task in list(self.tasks.items()):
            if task.done():
                del self.tasks[key]
                self.check_task(task)
        if self.po_task is not None and self.po_task.done():
            task, self.po_task = self.po_task, None
            self.check_task(task)
        self.halt_if_limited()

    def check_task(self, task: asyncio.Task[None]) -> None:
        """Re-raise what a finished task raised (a cancelled one raised nothing)."""
        if not task.cancelled() and task.exception() is not None:
            raise task.exception()  # type: ignore[misc]

    def halt_if_limited(self) -> None:
        """I6: nothing new starts after the usage limit; with nothing running, halt the run."""
        rt = self.runtime
        found = rt.flags.limited
        self.limited = self.limited or found is not None
        if found is not None and not self.tasks and rt.halted_by is None:
            rt.halt_run(found)

    async def stop_tasks(self) -> None:
        """C10: ``stop --now`` (a cancelled scheduler) cancels every task."""
        pending = [*self.tasks.values(), *([self.po_task] if self.po_task else [])]
        pending += [self.follow_task] if self.follow_task else []
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self.tasks.clear()

    async def wait_for_change(self) -> None:
        """C1 step 8: wait for a task to end, a write to be submitted, or ``POLL_S``."""
        self.runtime.writer.flush()  # our own lines land first and never wake the wait
        wake = self.runtime.writer.wake
        woken = asyncio.ensure_future(wake.wait()) if wake is not None else None
        busy = [*self.tasks.values(), *([self.po_task] if self.po_task else [])]
        waiting = [*busy, *([woken] if woken else [])]
        await asyncio.wait(waiting, timeout=POLL_S, return_when=asyncio.FIRST_COMPLETED)
        if woken is not None:
            woken.cancel()
        if wake is not None:
            wake.clear()

    # ----- what may start

    @property
    def is_blocked(self) -> bool:
        """C1 step 2: nothing new starts after a stop, a halt, a re-pin, a limit or a pause."""
        return self.ended() or self.limited or self.paused_by is not None

    @property
    def busy_keys(self) -> frozenset[str]:
        """The keys with a task here, or a PO-started step on the story."""
        return frozenset(self.tasks) | frozenset(self.runtime.flags.running)

    def start_work(self) -> None:
        """C1 steps 5 and 6: a due boundary stage, or the work the router offers."""
        if self.is_blocked:
            return
        started = self.start_revert()
        self.hurry = self.router.boundaries.open_end() or self.hurry
        for work in self.router.works(self.busy_keys):
            if self.is_held_by_boundary(work):
                continue
            started = self.start_one(work) or started
        if not started and not self.tasks and self.po_task is None:
            self.check_idle()

    def is_held_by_boundary(self, work: Work) -> bool:
        """C7, N4: a due boundary starts nothing new but the Manager's review."""
        if work.kind in BOUNDARY_FIXES or work.kind is StepKind.BOUNDARY or work.role == MANAGER:
            return False
        return self.is_boundary_due

    @property
    def is_boundary_due(self) -> bool:
        """A boundary stage is due (it waits for the running tasks to end)."""
        return self.router.boundaries.due() is not None

    def start_one(self, work: Work) -> bool:
        """Start ``work`` if it may; otherwise say why on the heartbeat."""
        if work.kind is StepKind.BOUNDARY:
            return self.start_boundary(work)
        reason = self.can_start(work)
        if reason is not None:
            self.runtime.pulse.set_waiting(reason)
            return False
        self.launch(work)
        return True

    def can_start(self, work: Work) -> str | None:
        """C2 to C4, L2, L3, D1: why ``work`` has to wait, or ``None``."""
        checks = (self.check_free, self.check_deps, self.check_land, self.check_cap)
        reasons = (check(work) for check in checks)
        return next((r for r in reasons if r is not None), None) or self.check_budget(work)

    def check_free(self, work: Work) -> str | None:
        """C2: one task per key; with story branches off, one step at a time."""
        if find_key(work) in self.busy_keys:
            return f"a task for {find_key(work)} is running"
        return None if self.runtime.state.story_branches or not self.tasks else ONE_AT_A_TIME

    def check_deps(self, work: Work) -> str | None:
        """D1: a story starts only when every dependency is done (landed)."""
        story = work.story
        if story is None or work.role == MANAGER:
            return None
        ids = dependencies.waiting_on(story, self.runtime.state.stories)
        return dependencies.WAITING.format(ids=", ".join(ids)) if ids else None

    def check_land(self, work: Work) -> str | None:
        """L2, L3, Q1: only the next in the landing queue lands, once the push is allowed."""
        if work.kind is not StepKind.LAND or work.story is None:
            return None
        state, next_up = self.runtime.state, self.landings.next_up()
        if next_up is not None and next_up != work.story.id:
            return WAIT_TEXTS[WaitReason.LAND_QUEUE].format(id=next_up)
        if state.upstream.push is Permission.UNASKED:
            state.permission_asked = True
            return WAIT_TEXTS[WaitReason.PERMISSION]
        return None

    def check_cap(self, work: Work) -> str | None:
        """C3: a story without a worktree starts only under ``max_open_stories``."""
        story, rt = work.story, self.runtime
        if story is None or work.kind is not StepKind.ROLE or story.worktree_head:
            return None
        cap = rt.config.team.max_open_stories
        open_ = Workspaces(rt.git, rt.config).open_count(rt.state.stories.values())
        return WAIT_TEXTS[WaitReason.OPEN_CAP].format(n=cap) if open_ >= cap else None

    def check_budget(self, work: Work) -> str | None:
        """C4: nothing starts when spend plus every running step's reserve reaches the ceiling."""
        if work.kind in COSTLESS:
            return None
        rt = self.runtime
        floor, entries = rt.config.team.step_reserve_usd, rt.ledger.entries()
        reserves = [self.find_reserve(entries, w, floor) for w in (*self.running.values(), work)]
        headroom = budget_reserve.Headroom(rt.ledger.total(), rt.config.team.budget_usd)
        why = budget_reserve.start_refusal(headroom, reserves)
        return None if why is None else WAIT_TEXTS[WaitReason.RESERVE].format(why=why)

    def find_reserve(self, entries: list[Any], work: Work, floor: float) -> float:
        """What one step of this work's role and model may still cost."""
        role = self.runtime.resolve(work.role)
        return budget_reserve.reserve(entries, budget_reserve.Who(role.name, role.model, floor))

    # ----- starting tasks

    def launch(self, work: Work) -> None:
        """Start the task of ``work`` under its key."""
        key = find_key(work)
        self.steps += 1
        self.router.end_wait()
        self.runtime.state.clear_stuck()
        self.running[key] = work
        self.tasks[key] = asyncio.create_task(self.run_work(work), name=key)

    async def run_work(self, work: Work) -> None:
        """One task: dispatch the work, note its report, queue its pass (C2)."""
        key = find_key(work)
        try:
            report = await self.dispatch(work)
        except Exception as exc:
            report = {"status": "error", "role": work.role, "reason": crash_halt(exc).reason}
        finally:
            self.running.pop(key, None)
        self.report_back(work, {"role": work.role, **report})

    async def dispatch(self, work: Work) -> dict[str, Any]:
        """Run the work: a land, or a role step under the lock its checkout needs."""
        if work.kind is StepKind.LAND:
            return await self.land(work)
        if work.kind is StepKind.BOUNDARY:
            return await self.router.boundaries.run_step()
        story = work.story
        request = StepRequest(work.role, work.brief, story.id if story else None, work.kind)
        async with self.runtime.lock_for(request):
            return await self.runtime.run_role(request)

    async def land(self, work: Work) -> dict[str, Any]:
        """L1 to L12: land the story; its verdict goes through the gate like a role's."""
        story = work.story
        assert story is not None
        self.landings.begin(story.id)
        report = await self.land_report(story)
        self.landings.finish(story.id)
        return report

    async def land_report(self, story: StoryState) -> dict[str, Any]:
        """The land's report: an unbranched story passes at once, else the lander decides."""
        if not story.branch:
            return self.pass_unbranched(story)
        return self.settle_land(story, await self.lander.land(story))

    def pass_unbranched(self, story: StoryState) -> dict[str, Any]:
        """A story that never had a branch (before story branches) passes land at once."""
        outcome = Outcome(Verdict.PASS, "landed", author=Author.RUNNER)
        gate = self.runtime.advance_as_runner(story, outcome)
        return {"role": "runner", "status": "land", "story": story.id, "gate": gate}

    def settle_land(self, story: StoryState, report: dict[str, Any]) -> dict[str, Any]:
        """Send a land's verdict through the story's gate; a wait or a halt changes nothing."""
        found = report.get("gate")
        if found is None:
            return report
        outcome = Outcome(found["verdict"], found["reason"], found["bounce_to"], Author.RUNNER)
        report["gate"] = self.runtime.advance_as_runner(story, outcome)
        if story.status in FINISHED:
            self.runtime.drop_worktree(story)
        return report

    # ----- landing reverts (E3)

    def start_revert(self) -> bool:
        """E3: the next queued revert lands as a task of its own, one at a time."""
        queue = self.runtime.revert_queue
        if not queue or REVERT_KEY in self.tasks or self.is_boundary_due:
            return False
        call = next((c for c in queue if c.story_id == self.landings.next_up()), None)
        if call is None:
            return False
        queue.remove(call)
        story = self.runtime.state.stories.get(call.story_id)
        if story is None or story.landed is None:
            return False
        self.landings.begin_revert(story.id)
        self.tasks[REVERT_KEY] = asyncio.create_task(self.run_revert(story, call), name=REVERT_KEY)
        return True

    async def run_revert(self, story: StoryState, call: Call) -> None:
        """Land the revert; on green record it and reset the story, else tell why."""
        try:
            report = await self.lander.land_revert(story, call.reason)
        finally:
            self.landings.finish(story.id)
        if report.get("gate", {}).get("verdict") == Verdict.PASS:
            async with self.main_lock:
                Reverter(self.runtime).finish_landing(story, call, report["land"]["merge"])
            return
        self.refuse_revert(story, report)

    def refuse_revert(self, story: StoryState, report: dict[str, Any]) -> None:
        """E4: the revert is refused; the liaison hears why and which later stories overlap."""
        why = report.get("reason") or report.get("gate", {}).get("reason", "")
        text = REVERT_REFUSED.format(story=story.id, why=why)
        later = report.get("land", {}).get("later") or []
        text += LATER.format(ids=", ".join(later)) if later else ""
        self.runtime.relay.post(Note("update", text, [story.id]))

    # ----- boundaries

    def start_boundary(self, work: Work) -> bool:
        """C7, B1: a boundary stage is a task, started once only the Manager's review runs."""
        if any(key != MANAGER_KEY for key in self.tasks):
            return False
        self.launch(work)
        return True

    def follow_boundary(self) -> None:
        """R9, B6: a CI hold follows a remote head that moved, as a task, once per beat."""
        self.check_follow_task()
        busy = BOUNDARY_KEY in self.tasks or self.follow_task is not None
        now = system.monotonic()
        if busy or now - self.followed_at < self.runtime.config.health.beat_s:
            return
        self.followed_at = now
        self.follow_task = asyncio.create_task(self.router.boundaries.run_follow(), name="follow")

    def check_follow_task(self) -> None:
        """Forget a finished follow, re-raising what it raised."""
        if self.follow_task is not None and self.follow_task.done():
            task, self.follow_task = self.follow_task, None
            self.check_task(task)

    # ----- reports and passes

    def report_back(self, work: Work, report: dict[str, Any]) -> None:
        """Note a finished work, settle a fix step's boundary, queue the PO's pass for it."""
        self.note_finished(work, report)
        if work.kind in FIX_STEPS:
            self.router.boundaries.after_fix(report)
        kinds = handover.triggers(report)
        sid = work.story.id if work.story else None
        if kinds:
            self.queue_pass(Pass(kinds, handover.report_lines(report, sid), [sid] if sid else []))

    def note_finished(self, work: Work, report: dict[str, Any]) -> None:
        """Note a refused or crashed story step on the story; spend the PO's one-time note."""
        story = work.story
        if story is None:
            return
        if report["status"] in NOTED_BY_RUNNER:
            self.runtime.note_step(story, report)
        if report["status"] not in NOT_NOTED | WAITS:
            story.note = ""
        self.runtime.save()

    def queue_pass(self, found: Pass) -> None:
        """C5, H2: queue a pass; a run-wide trigger also pauses new starts until a turn ends."""
        self.desk.queue(replace(found, steps=self.steps))
        self.told_permission = self.told_permission or Trigger.PUSH_PERMISSION in found.kinds
        if any(handover.SCOPES[kind] is Scope.RUN for kind in found.kinds):
            self.paused_by = str(found.kinds[0])

    def queue_news(self) -> None:
        """The human's new answers and tells are a pass of their own."""
        found = self.router.news()
        if found is not None:
            self.queue_pass(found)

    def ask_permission(self) -> None:
        """P1: the first push due while the answer is unasked raises one push_permission pass."""
        state = self.runtime.state
        if not state.permission_asked or self.told_permission:
            return
        if state.upstream.push is not Permission.UNASKED:
            return
        stack = state.upstream.stack
        branches = [e.branch for e in stack[-1:]]
        report = {"boundary": {"waiting": "push_permission", "branches": branches}}
        report["boundary"]["sprint"] = state.sprint  # type: ignore[assignment]
        lines = handover.report_lines(report, None)
        self.queue_pass(Pass([Trigger.PUSH_PERMISSION], lines, []))

    def poll_story_ci(self) -> None:
        """SC1, SC2: read each open story's PR CI; a red one hands over and holds nothing."""
        if self.ci_task is None or self.ci_task.done():
            self.check_ci_task()
            self.ci_task = asyncio.create_task(self.run_ci_poll(), name="story-ci")

    def check_ci_task(self) -> None:
        """Re-raise what the last poll raised (D4: a failing ``gh`` never gets this far)."""
        if self.ci_task is not None:
            self.check_task(self.ci_task)

    async def run_ci_poll(self) -> None:
        """Read the PRs' CI in worker threads; record and hand over on the loop (C6)."""
        now = system.monotonic()
        stories = list(self.runtime.state.stories.values())
        due = [s for s in stories if self.ci_poll.claim_due(s, now)]
        for story in due:
            sha = story.pushed
            checks = await system.in_thread(self.ci_poll.read_checks, story)
            self.record_story_ci(story, self.ci_poll.settle(story, checks, sha))

    def record_story_ci(self, story: StoryState, found: Any) -> None:
        """A red result for the story's head is handed over; anything else holds nothing."""
        if found is not None and found.verdict == CiVerdict.RED:
            self.queue_story_ci(story, found)

    def queue_story_ci(self, story: StoryState, found: Any) -> None:
        report = {"story_ci": {"verdict": "red", "sha": found.sha, "checks": [found.verdict]}}
        lines = handover.report_lines(report, story.id)
        self.queue_pass(Pass([Trigger.STORY_CI_RED], lines, [story.id]))

    def check_idle(self) -> None:
        """Nothing runs and nothing can start: sprint end, stuck, stalled, or waiting (I4)."""
        if not self.desk.is_empty:
            return
        found = self.router.idle()
        if found is None or not found.kinds:
            return
        if self.turns and replace(found, steps=self.steps).quiet():
            self.po.ended_by = found.lines[0] if found.lines else "idle"
            return
        self.queue_pass(found)
        self.steps = 0

    def show_waiting(self) -> None:
        """I3, I5: with nothing running, name what the run waits on; else name nothing."""
        busy = bool(self.tasks) or self.po_task is not None
        if not busy:
            self.router.mark_wait()
        reason = None if busy else self.runtime.relay.waiting()
        self.runtime.pulse.set_waiting(reason)

    # ----- the PO's turns

    def start_turn(self) -> None:
        """C1 step 7, C5: one PO turn at a time, over every queued pass."""
        if self.po_task is not None or self.ended():
            return
        turn = self.opening or self.build_turn(self.desk.take())
        self.opening = None
        if turn is None:
            return
        self.steps = 0
        self.turns += 1
        self.po_task = asyncio.create_task(self.run_turn(turn), name="po")

    def build_turn(self, found: Pass | None) -> PoTurn | None:
        """The prompt of a turn over the merged passes (the resume lead goes first, once)."""
        if found is None:
            return None
        lead, self.lead = self.lead, ""
        return self.po._hand_over(found, lead)

    async def run_turn(self, turn: PoTurn) -> None:
        """Run one PO turn, renewing its session first; its passes are dropped when it ends."""
        try:
            turn = await self.po._renewed(turn)
            self.result = await self.po._turn(turn)
        finally:
            self.paused_by = None
        if self.runtime.halted_by is None:
            self.desk.done()


def _join_prompts(*parts: str) -> str:
    return "\n\n".join(p for p in parts if p)
