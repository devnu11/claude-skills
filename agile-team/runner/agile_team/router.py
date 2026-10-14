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
from .config import Config
from .dispatch import FIX_KINDS_SET as FIX_STEPS
from .dispatch import MANAGER, NOT_NOTED, Runtime, StepRequest
from .gates import FINISHED, STEP_ROLES, StoryState, StoryStatus, role_fits_step
from .handover import Pass, Trigger
from .loops import Rule
from .relay import WAITING_HEAD, Answer, Told
from .reorders import Desk
from .reverts import Reverter
from .story_admin import Clerk

POLL_S = 5.0
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
    clerk: Clerk = field(init=False)
    reverter: Reverter = field(init=False)

    def __post_init__(self) -> None:
        self.boundaries = BoundaryRunner(self.runtime)
        self.desk = Desk(self.runtime)
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
        return rt.stop_requested() or bool(rt.halted_by) or rt.state.halted()

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
        in_sprint = story.sprint == rt.state.sprint and story.status is StoryStatus.ACTIVE
        free = story.hold is None and story.po_hold is None and rt.state.boundary is None
        ready = not dependencies.waiting_on(story, rt.state.stories)
        return in_sprint and free and ready and story.id not in rt.relay.blocked_stories()

    def _briefed(self, role: str, story: StoryState) -> Work:
        return Work(role, story, standard_brief(self.runtime.config, Work(role, story, "")))

    PICKERS: ClassVar[tuple[Callable[[Router], Work | None], ...]] = (
        _boundary_work,
        _manager_work,
        _repeat_work,
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
        mine = self._sprint_stories()
        pending = self.runtime.state.boundary
        unfinished = [s for s in mine if s.status not in FINISHED]
        if pending is None and self.runtime.state.sprint_complete():
            return self._sprint_end()
        if pending is None and (offer := self._offer(unfinished)):
            return offer
        if self.runtime.relay.open_questions():
            return None
        return self._stalled(unfinished)

    def _ready(self) -> list[str]:
        stories = self.runtime.state.stories
        return sprint_end.ready_backlog(stories, self.runtime.priority().queue(stories.values()))

    def _offer(self, unfinished: list[StoryState]) -> Pass | None:
        """K2: hand the PO the ready backlog once per set of stuck and ready stories."""
        state, ready = self.runtime.state, self._ready()
        key = [*(s.id for s in unfinished), *ready]
        if not (state.sprint_open() and unfinished and ready) or key == state.offered:
            return None
        state.offered = key
        self.runtime.save()
        stalled = self._stalled(unfinished)
        lines = [*stalled.lines, *sprint_end.ready_lines(state.stories, ready)]
        return Pass([Trigger.READY_BACKLOG], lines, [])

    def _sprint_end(self) -> Pass:
        state = self.runtime.state
        lines = [f"Sprint {state.sprint} is complete: every story in it is done."]
        if state.upstream.report:
            lines.append(f"Review: {state.upstream.report}")
        return Pass([Trigger.SPRINT_END], lines, [])

    def _stalled(self, unfinished: list[StoryState]) -> Pass:
        n = self.runtime.state.sprint
        lines = [f"Nothing in sprint {n} can move.", *self._stall_lines(unfinished)]
        return Pass([Trigger.STALLED], lines, [s.id for s in unfinished])

    def _stall_lines(self, unfinished: list[StoryState]) -> list[str]:
        pending = self.runtime.state.boundary
        if pending:
            return [_boundary_stall(pending)]
        stories = self.runtime.state.stories
        if unfinished:
            return [f"{s.id} at {s.step}: {_why(s, stories)}" for s in unfinished]
        lines = [
            f"No story is in sprint {self.runtime.state.sprint}; "
            "start_sprint with the stories to work on."
        ]
        backlog = [s.id for s in self.runtime.state.stories.values() if _in_backlog(s)]
        return lines + ([f"Backlog: {', '.join(backlog)}"] if backlog else [])

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


def _in_backlog(story: StoryState) -> bool:
    return story.sprint is None and story.status not in FINISHED
