"""Drives sprint stories through the pipeline between PO turns.

Picks the next step, briefs it, runs it, and stops at a hand-over.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any, ClassVar

from . import halt, handover, loops
from .boundary import BOUNDARY_STALL, Boundary, StepKind
from .boundary_runner import BoundaryRunner
from .config import Config
from .dispatch import FIX_KINDS_SET as FIX_STEPS
from .dispatch import MANAGER, NOT_NOTED, SCRIBE, Runtime, StepRequest
from .gates import STEP_ROLES, StoryState, StoryStatus, role_fits_step
from .handover import Pass, Trigger
from .loops import Rule
from .relay import Answer

POLL_S = 5.0
STEP_HEADING = "Standard brief from the runner. Read the files below; they hold the details."
MANAGER_BRIEF = "Manager review due: {reasons}"
BRIEF_HEADINGS = {
    SCRIBE: "Story {id} is done. Record its decisions as ADRs and refresh the role briefs. "
    "Read the files below.",
}
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
SENT_BACK_LINES = {
    "bounce": "- Sent back to this step: {reason}",
    "return": "- Sent back to this step: {reason}",
    "escalate": "- The same setback repeated, so the manager ruled on it: {reason}",
}

Sleep = Callable[[float], Awaitable[None]]


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


def _scribable(story: StoryState) -> bool:
    """A story the Scribe may run on: unheld, or done (its hold is the final step's)."""
    return not story.hold or story.status is StoryStatus.DONE


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
    return next((p for p in paths if (config.repo / p).is_file()), None)


def _path_lines(config: Config, story_id: str) -> list[str]:
    found = [(label, _first_existing(config, c, story_id)) for label, c in BRIEF_PATHS]
    return [f"- {label}: {path}" for label, path in found if path]


def _history_lines(story: StoryState) -> list[str]:
    lines, prev = [], story.previous
    if prev:
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
    heading = BRIEF_HEADINGS.get(work.role, STEP_HEADING).format(id=story.id)  # type: ignore[union-attr]
    return "\n".join([heading, *_path_lines(config, story.id), *_history_lines(story)])


# ----- the router -------------------------------------------------------------------


def _error_report(work: Work, exc: Exception) -> dict[str, Any]:
    return {"status": "error", "role": work.role, "reason": halt.crash_halt(exc).reason}


@dataclass
class Router:
    """Runs pipeline steps until something needs the PO."""

    runtime: Runtime
    sleep: Sleep = asyncio.sleep
    steps: int = field(default=0, init=False)
    boundaries: BoundaryRunner = field(init=False)

    def __post_init__(self) -> None:
        self.boundaries = BoundaryRunner(self.runtime)

    async def advance(self) -> Pass:
        """Run steps until a hand-over trigger, the end of the sprint or the end of the run."""
        self.steps = 0
        while not self._ended():
            found = await self._tick()
            if found:
                return replace(found, steps=self.steps)
        return Pass([], [], [], self.steps)

    async def _tick(self) -> Pass | None:
        news = self._news()
        if news:
            return self._deliver(news)
        work = self.next_work()
        if work:
            return await self._step(work)
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

    def _scribe_work(self) -> Work | None:
        rt = self.runtime
        blocked = rt.relay.blocked_stories()
        ids = (i for i in rt.state.scribe_due if i in rt.state.stories and i not in blocked)
        story = next((s for s in map(rt.state.stories.get, ids) if s and _scribable(s)), None)
        return self._briefed(SCRIBE, story) if story else None

    def _repeat_work(self) -> Work | None:
        story = next((s for s in self.runtime.state.stories.values() if self._escalated(s)), None)
        if story is None:
            return None
        return Work(MANAGER, story, repeat_brief(self.runtime.config, story))

    def _escalated(self, story: StoryState) -> bool:
        rt = self.runtime
        in_sprint = story.sprint == rt.state.sprint and story.status is StoryStatus.NEEDS_MANAGER
        waiting = story.repeated is not None and story.hold is None
        return in_sprint and waiting and story.id not in rt.relay.blocked_stories()

    def _story_work(self) -> Work | None:
        story = next((s for s in self.runtime.state.stories.values() if self._movable(s)), None)
        return self._briefed(step_role(story), story) if story else None

    def _movable(self, story: StoryState) -> bool:
        rt = self.runtime
        in_sprint = story.sprint == rt.state.sprint and story.status is StoryStatus.ACTIVE
        free = story.hold is None and rt.state.boundary is None
        return in_sprint and free and story.id not in rt.relay.blocked_stories()

    def _briefed(self, role: str, story: StoryState) -> Work:
        return Work(role, story, standard_brief(self.runtime.config, Work(role, story, "")))

    PICKERS: ClassVar[tuple[Callable[[Router], Work | None], ...]] = (
        _boundary_work,
        _manager_work,
        _repeat_work,
        _scribe_work,
        _story_work,
    )

    def next_work(self) -> Work | None:
        """The first step due: boundary, Manager (review, repeat), Scribe, then a story."""
        works = (pick(self) for pick in self.PICKERS)
        return next((w for w in works if w), None)

    # ----- running a step

    async def _step(self, work: Work) -> Pass | None:
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

    def _deliver(self, answers: list[Answer]) -> Pass:
        state, relay = self.runtime.state, self.runtime.relay
        state.delivered = [*(state.delivered or []), *(a.id for a in answers)]
        self.runtime.save()
        asked = {m.id: m for m in relay.messages()}
        lines = [f'The human answered {a.id} ("{asked[a.id].text}"): {a.text}' for a in answers]
        stories = [s for a in answers for s in asked[a.id].stories]
        return Pass([Trigger.HUMAN_MESSAGE], lines, list(dict.fromkeys(stories)))

    def _sprint_stories(self) -> list[StoryState]:
        state = self.runtime.state
        return [s for s in state.stories.values() if s.sprint == state.sprint]

    def _idle(self) -> Pass | None:
        mine = self._sprint_stories()
        pending = self.runtime.state.boundary
        if pending is None and mine and all(s.status is StoryStatus.DONE for s in mine):
            return self._sprint_end()
        if self.runtime.relay.open_questions():
            return None
        return self._stalled([s for s in mine if s.status is not StoryStatus.DONE])

    def _sprint_end(self) -> Pass | None:
        if self.boundaries.open_end():
            return None
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
        if unfinished:
            return [f"{s.id} at {s.step}: {_why(s)}" for s in unfinished]
        lines = [
            f"No story is in sprint {self.runtime.state.sprint}; "
            "start_sprint with the stories to work on."
        ]
        backlog = [s.id for s in self.runtime.state.stories.values() if _in_backlog(s)]
        return lines + ([f"Backlog: {', '.join(backlog)}"] if backlog else [])

    async def _wait(self) -> None:
        await self.sleep(POLL_S)


def _boundary_stall(b: Boundary) -> str:
    return BOUNDARY_STALL.format(sprint=b.sprint, edge=b.edge, stage=b.stage, hold=b.hold)


def _why(story: StoryState) -> str:
    if story.hold:
        return STALL_REASONS["hold"].format(hold=story.hold)
    return STALL_REASONS.get(story.status, str(story.status))


def _in_backlog(story: StoryState) -> bool:
    return story.sprint is None and story.status is not StoryStatus.DONE
