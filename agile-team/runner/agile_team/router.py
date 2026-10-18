"""Drives sprint stories through the pipeline between PO turns.

Picks the next step, briefs it, runs it, and stops at a hand-over.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, ClassVar

from . import dependencies, halt, handover, loops, owners, sprint_end, system, threads
from .boundary import BOUNDARY_STALL, Boundary, StepKind, stall_hint
from .boundary_runner import BoundaryRunner
from .checkout import CheckoutRequests
from .config import Config
from .dispatch import FIX_KINDS_SET as FIX_STEPS
from .dispatch import MANAGER, NOT_NOTED, Runtime, StepRequest
from .gates import (
    FINISHED,
    STEP_ROLES,
    Outcome,
    StoryState,
    StoryStatus,
    Verdict,
    role_fits_step,
)
from .handover import Pass, Trigger
from .loops import Rule
from .relay import WAITING_HEAD, Answer, Note, Told
from .reorders import Desk
from .reverts import Reverter
from .sharing import Sharer
from .state import RunStatus
from .story_admin import Clerk
from .story_intake import Intake

POLL_S = 5.0
MANAGER_KEY = "manager"
BOUNDARY_KEY = "boundary"
STEP_HEADING = "Standard brief from the runner. Read the files below; they hold the details."
MANAGER_BRIEF = "Manager review due: {reasons}"
BRIEF_PATHS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Story", (".team/stories/{id}.md",)),
    ("Design", ("{docs}/design/{id}.md", "{docs}/architecture.md")),
    ("Review", (".team/reviews/{id}.md",)),
)
STALL_REASONS: dict[str, str] = {
    "hold": "held ({hold})",
    StoryStatus.NEEDS_MANAGER: "at the round cap",
    StoryStatus.BLOCKED: "escalated to the human",
}
REPEAT_HEADING = (
    "Story {id} hit the same setback {count} times in a row, so the runner stopped the loop. "
    'Find who owns the fault and rule on it: hand off "fault" (the role at fault, or '
    '"runner") and, if needed, a "ruling". The repeated reason, the history and the last '
    "output are in the runner context under repeated_setback."
)
BACKSTOP_HEADING = (
    "Story {id} bounced between {step} and {to_step} {count} times in a row, not always for "
    "the same reason, so the runner stopped the loop. It may be one complaint reworded, or a "
    'fault no role can fix. Find who owns the fault and rule on it: hand off "fault" (the '
    'role at fault, or "runner") and, if needed, a "ruling". Every reason, the history and '
    "the last output are in the runner context under repeated_setback."
)
HEADINGS = {Rule.REPEAT: REPEAT_HEADING, Rule.BACKSTOP: BACKSTOP_HEADING}
QUIET_VERDICTS = frozenset({"next"})
SENT_BACK_LINES = {
    "bounce": "- Sent back to this step: {reason}",
    "return": "- Sent back to this step: {reason}",
    "route": "- Other roles fix items in their files first, then this step runs again: {reason}",
    "escalate": "- The same setback repeated, so the manager ruled on it: {reason}",
}
FIX_HEADING = (
    "Gate fix on story {id}: the {step} gate failed on files you own. Fix only the items "
    "below, then hand off done; the story goes back to {step} with no round counted. "
    "If a fix changes what a test asserts, put the AC or design rule that makes the old "
    'assertion wrong in your handoff\'s "asserts" field. If the failure is not yours to fix, '
    "hand off changes_requested and say why; the story goes back to {step} as a round."
)


@dataclass
class Work:
    """One step to run: the role, its story (``None`` for the Manager) and its finished brief."""

    role: str
    story: StoryState | None
    brief: str
    kind: StepKind = StepKind.ROLE


# ----- role choice -------------------------------------------------------------


def _bounced(story: StoryState) -> bool:
    return bool(story.previous and story.previous.verdict == "bounce")


def _po_pick(story: StoryState) -> str | None:
    return story.po_developer


def _bounce_target(story: StoryState) -> str | None:
    return story.previous.next_role if story.previous and _bounced(story) else None


def _bounce_source(story: StoryState) -> str | None:
    return story.previous.role if story.previous and _bounced(story) else None


def _architect_pick(story: StoryState) -> str | None:
    return story.developer


def _pipeline_role(story: StoryState) -> str | None:
    return STEP_ROLES[story.step]


ROLE_HINTS: tuple[Callable[[StoryState], str | None], ...] = (
    _po_pick,
    _bounce_target,
    _bounce_source,
    _architect_pick,
    _pipeline_role,
)


def step_role(story: StoryState) -> str:
    """The first hinted role that fits the story's step."""
    candidates = (hint(story) for hint in ROLE_HINTS)
    return next(c for c in candidates if c and role_fits_step(c, story.step))


# ----- the standard brief --------------------------------------------------------


def _first_existing(config: Config, candidates: tuple[str, ...], story_id: str) -> str | None:
    docs = config.team.docs_dir.rstrip("/")
    paths = (c.format(id=story_id, docs=docs) for c in candidates)
    return next((p for p in paths if system.is_file(config.repo / p)), None)


def _path_lines(config: Config, story_id: str) -> list[str]:
    found = [(label, _first_existing(config, c, story_id)) for label, c in BRIEF_PATHS]
    return [f"- {label}: {path}" for label, path in found if path]


def _history_lines(story: StoryState) -> list[str]:
    lines, prev = [], story.previous
    if prev and prev.verdict not in QUIET_VERDICTS:
        said = f": {prev.summary}" if prev.summary else ""
        lines.append(f"- Previous step: {prev.role} reported {prev.status}{said}")
    if prev and prev.verdict in SENT_BACK_LINES:
        lines.append(SENT_BACK_LINES[prev.verdict].format(reason=prev.reason))
    return lines + ([f"- From the PO: {story.note}"] if story.note else [])


def repeat_brief(config: Config, story: StoryState) -> str:
    """The Manager's brief on a story the runner escalated: the heading and the standard paths."""
    setbacks = loops.trail(story)
    last = setbacks[-1]
    heading = HEADINGS[story.escalated_by or Rule.REPEAT].format(
        id=story.id, count=len(setbacks), step=last.step, to_step=last.to_step
    )
    return "\n".join([heading, *_path_lines(config, story.id)])


def standard_brief(config: Config, work: Work) -> str:
    """The brief every router step gets: heading, artifact paths, history and the PO's note."""
    story = work.story  # story steps only; the Manager's brief is MANAGER_BRIEF
    heading = STEP_HEADING
    extras = BRIEF_EXTRAS.get(work.role, _no_lines)(story)
    return "\n".join([heading, *_path_lines(config, story.id), *_history_lines(story), *extras])


def fix_brief(config: Config, story: StoryState) -> str:
    """The brief of the story's first queued gate fix (R14)."""
    heading = FIX_HEADING.format(id=story.id, step=story.step)
    items = owners.fix_lines(story.fixes[0])
    return "\n".join([heading, *items, *_path_lines(config, story.id)])


def _no_lines(story: StoryState) -> list[str]:
    return []


def _fixed_lines(story: StoryState) -> list[str]:
    """One line per settled gate fix, for the code-reviewer (R19)."""
    return [
        f"- Gate fix by {r.role} (commit {(r.commit or 'none')[:12]}) on "
        f"{', '.join(r.files)}: {owners.fix_note(r)}"
        for r in story.fixed
    ]


BRIEF_EXTRAS: dict[str, Callable[[StoryState], list[str]]] = {"code-reviewer": _fixed_lines}


# ----- the router -------------------------------------------------------------------


def _error_report(work: Work, exc: Exception) -> dict[str, Any]:
    return {"status": "error", "role": work.role, "reason": halt.crash_halt(exc).reason}


@dataclass
class Router:
    """Runs pipeline steps until something needs the PO."""

    runtime: Runtime
    steps: int = field(default=0, init=False)
    boundaries: BoundaryRunner = field(init=False)
    desk: Desk = field(init=False)
    sharer: Sharer = field(init=False)
    intake: Intake = field(init=False)
    clerk: Clerk = field(init=False)
    reverter: Reverter = field(init=False)

    def __post_init__(self) -> None:
        self.boundaries = BoundaryRunner(self.runtime)
        self.desk = Desk(self.runtime)
        self.sharer = Sharer(self.runtime)
        self.intake = Intake(self.runtime)
        self.clerk = Clerk(self.runtime)
        self.reverter = Reverter(self.runtime)

    async def advance(self) -> Pass:
        """Run steps until a hand-over trigger, the end of the sprint or the end of the run."""
        self.steps = 0
        while not self._ended():
            found = await self._tick()
            if found:
                return replace(found, steps=self.steps)
        return Pass([], [], [], self.steps)

    async def _tick(self) -> Pass | None:
        if self.runtime.checkout_moved():
            return None
        self.desk.apply()
        self.sharer.apply()
        self.intake.apply()
        self.clerk.settle()
        self.reverter.settle()
        answers, told = self._news(), self._unread()
        if answers or told:
            return self._deliver(answers, told)
        work = self.next_work()
        if work:
            return await self._step(work)
        if self.boundaries.open_end():
            return None  # the boundary just opened is the next work; do not wait for it
        idle = self._idle()
        if idle is None:
            await self._wait()
        return idle

    def _ended(self) -> bool:
        rt = self.runtime
        stop = rt.stop_requested() or bool(rt.halted_by) or rt.state.halted()
        return stop or bool(rt.state.repin)

    # ----- picking work

    def _boundary_work(self) -> Work | None:
        due = self.boundaries.due()
        return Work(due.role, None, due.brief, due.kind) if due else None

    def _manager_work(self) -> Work | None:
        due = self.runtime.state.manager_due
        return Work(MANAGER, None, MANAGER_BRIEF.format(reasons="; ".join(due))) if due else None

    def _repeat_work(self) -> Work | None:
        story = self._first_ranked(self._escalated)
        if story is None:
            return None
        return Work(MANAGER, story, repeat_brief(self.runtime.config, story))

    def _first_ranked(self, wanted: Callable[[StoryState], bool]) -> StoryState | None:
        rt = self.runtime
        return next((s for s in rt.priority().ranked(rt.state.stories.values()) if wanted(s)), None)

    def _escalated(self, story: StoryState) -> bool:
        rt = self.runtime
        in_sprint = story.sprint == rt.state.sprint and story.status is StoryStatus.NEEDS_MANAGER
        waiting = story.repeated is not None and story.hold is None
        free = story.po_hold is None and story.id not in rt.relay.blocked_stories()
        return in_sprint and waiting and free

    def _land_work(self) -> Work | None:
        """Pass the stories at ``land``: with no story branches yet their commits are landed."""
        rt = self.runtime
        landing = [s for s in rt.state.stories.values() if s.step == "land" and self._movable(s)]
        for story in landing:
            rt.pipeline.advance(story, Outcome(Verdict.PASS, "landed"))
            rt.save()
        return None

    def _story_work(self) -> Work | None:
        story = self._first_ranked(self._movable)
        if story is None:
            return None
        return self._fix_work(story) if story.fixes else self._briefed(step_role(story), story)

    def _fix_work(self, story: StoryState) -> Work:
        brief = fix_brief(self.runtime.config, story)
        return Work(story.fixes[0].role, story, brief, StepKind.GATE_FIX)

    def _movable(self, story: StoryState) -> bool:
        rt = self.runtime
        return sprint_end.can_move(story, rt.state) and story.id not in rt.relay.blocked_stories()

    def _briefed(self, role: str, story: StoryState) -> Work:
        return Work(role, story, standard_brief(self.runtime.config, Work(role, story, "")))

    # ----- the scheduler's views (s159 C1)

    def works(  # house-rules: allow verb-name -- name fixed by the s159 tests
        self,
        running: frozenset[str],
    ) -> list[Work]:
        """Every startable work, in picker order, skipping the keys that already run."""
        found = [w for w in self._offered if w is not None]
        return [w for w in found if find_key(w) not in running]

    @property
    def _offered(self) -> list[Work | None]:
        return [
            self._boundary_work(),
            self._manager_work(),
            self._repeat_work(),
            *self._story_offers,
        ]

    @property
    def _story_offers(self) -> list[Work | None]:
        rt = self.runtime
        ranked = rt.priority().ranked(rt.state.stories.values())
        return [self._pick_work(s) for s in ranked if self._movable(s)]

    def _pick_work(self, story: StoryState) -> Work:
        """The next work of a movable story: its queued rebase, its land, a fix or its step."""
        if story.rebase is not None:
            return Work(
                story.rebase.role, story, self._write_rebase_brief(story), StepKind.STORY_REBASE
            )
        if story.step == "land":
            return Work("runner", story, "", StepKind.LAND)
        return self._fix_work(story) if story.fixes else self._briefed(step_role(story), story)

    def _write_rebase_brief(self, story: StoryState) -> str:
        return standard_brief(self.runtime.config, Work(story.rebase.role, story, ""))  # type: ignore[union-attr]

    def apply_queues(self) -> None:
        """C1: apply the request queues of stories with no running task."""
        self.desk.apply()
        self.sharer.apply()
        self.intake.apply()
        self.clerk.settle()
        self.reverter.settle()
        CheckoutRequests(self.runtime.config).apply(self.runtime)

    def news(  # house-rules: allow query-property -- name fixed by the s159 tests
        self,
    ) -> Pass | None:
        """The human's new answers and tells as a pass, once each."""
        answers, told = self._news(), self._unread()
        return self._deliver(answers, told) if answers or told else None

    def mark_wait(self) -> None:
        """Name what the run waits on in ``status_reason`` (W3)."""
        self._show_wait()

    def end_wait(self) -> None:
        """Clear a waiting reason once work starts (W4)."""
        self._end_wait()

    def idle(  # house-rules: allow verb-name, query-property -- name fixed by the s159 tests
        self,
    ) -> Pass | None:
        """The pass for a run with nothing to start: sprint end, stuck, stalled; or ``None``."""
        return self._idle()

    PICKERS: ClassVar[tuple[Callable[[Router], Work | None], ...]] = (
        _boundary_work,
        _manager_work,
        _repeat_work,
        _land_work,
        _story_work,
    )

    def next_work(self) -> Work | None:
        """The first step due: boundary, Manager (review, repeat), then a story."""
        works = (pick(self) for pick in self.PICKERS)
        return next((w for w in works if w), None)

    # ----- running a step

    async def _step(self, work: Work) -> Pass | None:
        self._end_wait()
        self.steps += 1
        self.runtime.state.clear_stuck()
        report = await self._dispatch(work)
        kinds = handover.triggers(report)
        sid = work.story.id if work.story else None
        if not kinds:
            return None
        return Pass(kinds, handover.report_lines(report, sid), [sid] if sid else [])

    async def _dispatch(self, work: Work) -> dict[str, Any]:
        story = work.story
        try:
            report = await self._run(work)
        except Exception as exc:
            report = _error_report(work, exc)
        report = {"role": work.role, **report}
        self._after(story, report)
        if work.kind in FIX_STEPS:
            self.boundaries.after_fix(report)
        return report

    async def _run(self, work: Work) -> dict[str, Any]:
        if work.kind is StepKind.BOUNDARY:
            return self.boundaries.step()
        story = work.story
        return await self.runtime.run_role(
            StepRequest(work.role, work.brief, story.id if story else None, work.kind)
        )

    def _after(self, story: StoryState | None, report: dict[str, Any]) -> None:
        if story is None:
            return
        if report["status"] in ("refused", "error"):
            self.runtime.note_step(story, report)
        if report["status"] not in NOT_NOTED:
            story.note = ""
        self.runtime.save()

    # ----- run-level passes

    def _news(self) -> list[Answer]:
        delivered = self.runtime.state.delivered or []
        return [a for a in self.runtime.relay.answers().values() if a.id not in delivered]

    def _unread(self) -> list[Told]:
        return self.runtime.relay.unread(self.runtime.state.told)

    def _deliver(self, answers: list[Answer], told: list[Told]) -> Pass:
        state = self.runtime.state
        self._clear_wait()
        state.delivered = [*(state.delivered or []), *(a.id for a in answers)]
        state.told = [*state.told, *(t.id for t in told)]
        self.runtime.save()
        lines = self._answer_lines(answers) + self._told_lines(told)
        stories = [*self._answer_stories(answers), *threads.told_stories(told)]
        return Pass([Trigger.HUMAN_MESSAGE], lines, list(dict.fromkeys(stories)))

    def _answer_lines(self, answers: list[Answer]) -> list[str]:
        asked = {m.id: m for m in self.runtime.relay.messages()}
        return [f'The human answered {a.id} ("{asked[a.id].text}"): {a.text}' for a in answers]

    def _answer_stories(self, answers: list[Answer]) -> list[str]:
        asked = {m.id: m for m in self.runtime.relay.messages()}
        return list(dict.fromkeys(s for a in answers for s in asked[a.id].stories))

    def _told_lines(self, told: list[Told]) -> list[str]:
        repo = self.runtime.config.repo
        return [threads.told_line(t, repo) for t in told]

    def _sprint_stories(self) -> list[StoryState]:
        state = self.runtime.state
        return [s for s in state.stories.values() if s.sprint == state.sprint]

    def _idle(self) -> Pass | None:
        """S2: sprint end, wait on a question, the stuck Sprint Backlog, or today's stall."""
        pending = self.runtime.state.boundary
        unfinished = [s for s in self._sprint_stories() if s.status not in FINISHED]
        if pending is None and self.runtime.state.sprint_complete():
            return self._sprint_end()
        if self.runtime.relay.open_questions():
            return None
        if pending is None and unfinished:
            return self._hand_over_stuck(unfinished)
        return self._stalled(unfinished)

    @property
    def _ready_ids(self) -> list[str]:
        stories = self.runtime.state.stories
        queue = self.runtime.priority().queue(stories.values())
        return sprint_end.select_ready_product_backlog(stories, queue)

    def _hand_over_stuck(self, unfinished: list[StoryState]) -> Pass:
        """S3/S4: hand over the stuck Sprint Backlog with each reason; past the cap, block."""
        state = self.runtime.state
        reasons = self._list_stall_lines(unfinished)
        if state.stuck_asks >= sprint_end.SPRINT_STUCK_CAP:
            return self._block(sprint_end.format_stuck_blocked_text(state, reasons))
        state.stuck_asks += 1
        self.runtime.save()
        lines = sprint_end.list_stuck(state, reasons)
        return Pass([Trigger.SPRINT_BACKLOG_STUCK], lines, [s.id for s in unfinished])

    def _sprint_end(self) -> Pass:
        state = self.runtime.state
        lines = [f"Sprint {state.sprint} is complete: every story in it is done."]
        if state.upstream.report:
            lines.append(f"Review: {state.upstream.report}")
        ready = self._ready_ids
        if state.cadence != sprint_end.UNTIL_BLOCKER or not ready:
            return Pass([Trigger.SPRINT_END], lines, [])
        lines += sprint_end.next_sprint_lines(state.stories, ready)
        return self._asked(Pass([Trigger.NEXT_SPRINT], lines, []))

    def _asked(self, found: Pass) -> Pass:
        """K4: count a keep-going hand-over; past the cap, block the run instead."""
        state = self.runtime.state
        if state.keep_going_asks < sprint_end.KEEP_GOING_CAP:
            state.keep_going_asks += 1
            self.runtime.save()
            return found
        ids = sprint_end.ids_text(self._ready_ids)
        stuck = sprint_end.KEEP_GOING_STUCK.format(count=state.keep_going_asks, ids=ids)
        return self._block(stuck)

    def _block(self, text: str) -> Pass:
        """Post text to the liaison and wait on the human (I4); the run stays running."""
        state = self.runtime.state
        sent = self.runtime.relay.messages()
        if not sent or (sent[-1].kind, sent[-1].text) != ("blocked", text):
            self.runtime.relay.post(Note("blocked", text, []))  # polling repeats; post once
        state.mark(RunStatus.RUNNING, text)
        self.runtime.save()
        return Pass([], [], [])

    def _stalled(self, unfinished: list[StoryState]) -> Pass:
        n = self.runtime.state.sprint
        lines = [f"Nothing in sprint {n} can move.", *self._stall_lines(unfinished)]
        return Pass([Trigger.STALLED], lines, [s.id for s in unfinished])

    def _stall_lines(self, unfinished: list[StoryState]) -> list[str]:
        pending = self.runtime.state.boundary
        if pending:
            return [_boundary_stall(pending)]
        if unfinished:
            return self._list_stall_lines(unfinished)
        lines = [
            f"No story is in sprint {self.runtime.state.sprint}; "
            "start_sprint with the stories to work on."
        ]
        in_product = [
            s.id for s in self.runtime.state.stories.values() if _is_in_product_backlog(s)
        ]
        return lines + ([f"Product Backlog: {', '.join(in_product)}"] if in_product else [])

    def _list_stall_lines(self, unfinished: list[StoryState]) -> list[str]:
        """One "<id> at <step>: <why>" line per story."""
        stories = self.runtime.state.stories
        return [f"{s.id} at {s.step}: {_why(s, stories)}" for s in unfinished]

    async def _wait(self) -> None:
        self._show_wait()
        await system.async_sleep(POLL_S)

    def _show_wait(self) -> None:
        """Name what the run waits on in `status_reason`, saving only on change (W3)."""
        state, reason = self.runtime.state, self.runtime.relay.waiting()
        if state.status_reason != reason:
            state.mark(state.status, reason)
            self.runtime.save()

    def _clear_wait(self) -> bool:
        """Drop a waiting reason from the state; say whether there was one (W4)."""
        state = self.runtime.state
        waiting = (state.status_reason or "").startswith(WAITING_HEAD)
        if waiting:
            state.mark(state.status)
        return waiting

    def _end_wait(self) -> None:
        """Clear a waiting reason once the wait ends, and save (W4)."""
        if self._clear_wait():
            self.runtime.save()


def find_key(work: Work) -> str:
    """C2: one task per key: the story, the Manager review, or the boundary."""
    if work.role == MANAGER:
        return MANAGER_KEY
    return work.story.id if work.story else BOUNDARY_KEY


def _boundary_stall(b: Boundary) -> str:
    return BOUNDARY_STALL.format(
        sprint=b.sprint, edge=b.edge, stage=b.stage, hold=b.hold, hint=stall_hint(b.hold)
    )


def _why(story: StoryState, stories: dict[str, StoryState]) -> str:
    if story.po_hold:
        return story.po_hold.shown
    if story.hold:
        return STALL_REASONS["hold"].format(hold=story.hold)
    if waiting := dependencies.waiting_on(story, stories):
        return dependencies.WAITING.format(ids=", ".join(waiting))
    return STALL_REASONS.get(story.status, str(story.status))


def _is_in_product_backlog(story: StoryState) -> bool:
    return story.sprint is None and story.status not in FINISHED
