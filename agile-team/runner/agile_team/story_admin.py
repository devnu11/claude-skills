"""The PO's story admin tools (s53): hold, release and ask to cancel a story.

The rules are pure; ``Clerk`` does the I/O. Only the human's answer cancels a story.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from . import priority
from .dispatch import Runtime, refused
from .events import Event, EventKind
from .gates import FINISHED, StoryState, StoryStatus
from .holds import HoldKind, PoHold
from .relay import Answer, Note
from .state import RunState

UNKNOWN = "unknown story {story!r}; ask the liaison for it with request_story"
NO_REASON = "a reason is required"
FINISHED_TEXT = "story {story} is {status}; there is nothing to {verb}"
CANCEL_PENDING = (
    "story {story} already waits on the human's answer to {question} about cancelling it; "
    "answer {question} instead"
)
REVERT_PENDING = (
    "story {story} already waits on the human's answer to {question} about reverting it; "
    "answer {question} instead"
)
ASKED = "story {story} has an open question; answer {ids} instead"
MANAGER_WAIT = (
    "story {story} waits on the Manager (round cap or repeated setback); run the manager on it"
)
NOTHING_HELD = (
    "story {story} has no PO hold and is not blocked; nothing to release "
    "(continue_story releases a hand-over hold)"
)
CODE_UNSAID = (
    "story {story} has commits ({count}); say in the reason what happens to its code "
    "(kept, reverted by a new story, …)"
)
CANCEL_QUESTION = (
    'Cancel story {story} ("{title}")? The PO asks because: {reason} '
    'Answer "cancel" to cancel it or "keep" to keep it.'
)
UNCLEAR_ANSWER = 'the answer to {question} was neither "cancel" nor "keep": {answer}'
CODE_WORDS = ("code", "commit")
ANSWER_STRIP = " \t\n.!\"'"
PO_ROLE = "product-owner"


class Act(StrEnum):
    """The three tools; values are the MCP tool names."""

    HOLD = "hold_story"
    RELEASE = "release_story"
    REQUEST_CANCEL = "request_cancel"


class Decision(StrEnum):
    """What the human's answer to a cancel request means."""

    CANCEL = "cancel"
    KEEP = "keep"
    UNCLEAR = "unclear"


DECISIONS = {"cancel": Decision.CANCEL, "keep": Decision.KEEP}


@dataclass(frozen=True)
class Case:
    """One tool call: act, story id, reason, the story (None if unknown), open question ids."""

    act: Act
    story_id: str
    reason: str
    story: StoryState | None
    asked: tuple[str, ...]


@dataclass(frozen=True)
class Change:
    """What a successful call applies: the stripped reason and the question posted, if any."""

    reason: str
    question: str | None = None


Check = Callable[[Case], str | None]


def _story(case: Case) -> StoryState:
    assert case.story is not None
    return case.story


def unknown_refusal(case: Case) -> str | None:
    """Refuse an unknown story."""
    return UNKNOWN.format(story=case.story_id) if case.story is None else None


def reason_refusal(case: Case) -> str | None:
    """Refuse a blank reason."""
    return None if case.reason.strip() else NO_REASON


def finished_refusal(case: Case) -> str | None:
    """Refuse a done or cancelled story."""
    story = _story(case)
    if story.status not in FINISHED:
        return None
    verb = TOOLS[case.act].verb
    return FINISHED_TEXT.format(story=story.id, status=story.status, verb=verb)


ASKED_TEXTS = {HoldKind.CANCEL: CANCEL_PENDING, HoldKind.REVERT: REVERT_PENDING}


def asked_text(story: StoryState) -> str | None:
    """The refusal text while a cancel or revert question waits for the human, else None."""
    hold = story.po_hold
    if hold is None or hold.kind not in ASKED_TEXTS:
        return None
    return ASKED_TEXTS[hold.kind].format(story=story.id, question=hold.question)


def pending_refusal(case: Case) -> str | None:
    """Refuse while a cancel or revert question waits for the human."""
    return asked_text(_story(case))


def asked_refusal(case: Case) -> str | None:
    """Refuse a release while an open question names the story."""
    ids = ", ".join(case.asked)
    return ASKED.format(story=case.story_id, ids=ids) if case.asked else None


def manager_refusal(case: Case) -> str | None:
    """Refuse a release of a story that waits on the Manager."""
    waits = _story(case).status is StoryStatus.NEEDS_MANAGER
    return MANAGER_WAIT.format(story=case.story_id) if waits else None


def nothing_refusal(case: Case) -> str | None:
    """Refuse a release when nothing is held."""
    story = _story(case)
    if story.po_hold or story.status is StoryStatus.BLOCKED:
        return None
    return NOTHING_HELD.format(story=case.story_id)


def _commits(story: StoryState) -> int:
    return len({story.commit, *story.code_commits} - {None})


def code_refusal(case: Case) -> str | None:
    """Refuse a cancel request for a story with commits when the reason skips its code."""
    story = _story(case)
    if not (priority.started(story) or story.code_commits):
        return None
    if any(w in case.reason.lower() for w in CODE_WORDS):
        return None
    return CODE_UNSAID.format(story=case.story_id, count=_commits(story))


def facts(story: StoryState) -> dict[str, Any]:
    """The story facts an event records (H10)."""
    return {
        "status": str(story.status),
        "step": story.step,
        "sprint": story.sprint,
        "hold": story.hold,
        "po_hold": asdict(story.po_hold) if story.po_hold else None,
    }


def hold(story: StoryState, change: Change) -> None:
    """Hold the story (H2)."""
    story.po_hold = PoHold(HoldKind.HOLD, change.reason)


def release(story: StoryState, change: Change) -> None:
    """Release the story to the step it stopped at (H5)."""
    story.po_hold, story.hold = None, None
    story.status, story.note = StoryStatus.ACTIVE, change.reason


def request(story: StoryState, change: Change) -> None:
    """Hold the story as a cancel request (H6)."""
    story.po_hold = PoHold(HoldKind.CANCEL, change.reason, change.question)


def no_note(case: Case) -> Note | None:
    """No question is posted."""
    return None


def cancel_note(case: Case) -> Note:
    """The question that asks the human to cancel."""
    story = _story(case)
    reason = case.reason.strip()
    text = CANCEL_QUESTION.format(story=story.id, title=story.title, reason=reason)
    return Note("question", text, [story.id])


@dataclass(frozen=True)
class Tool:
    """One row of TOOLS: checks, question, effect, result status and verb."""

    checks: tuple[Check, ...]
    note: Callable[[Case], Note | None]
    effect: Callable[[StoryState, Change], None]
    status: str
    verb: str


SHARED: tuple[Check, ...] = (unknown_refusal, reason_refusal, finished_refusal)
TOOLS: dict[Act, Tool] = {
    Act.HOLD: Tool((pending_refusal,), no_note, hold, "held", "hold"),
    Act.RELEASE: Tool(
        (asked_refusal, manager_refusal, nothing_refusal), no_note, release, "released", "release"
    ),
    Act.REQUEST_CANCEL: Tool(
        (pending_refusal, code_refusal), cancel_note, request, "cancel requested", "cancel"
    ),
}


def refusal(case: Case) -> str | None:
    """H8: the first refusal of the shared checks, then the tool's own."""
    checks = [lambda c=c: c(case) for c in (*SHARED, *TOOLS[case.act].checks)]
    return priority.first_refusal(checks)


def decision(text: str) -> Decision:
    """H7: what the human's answer means."""
    return DECISIONS.get(text.strip(ANSWER_STRIP).lower(), Decision.UNCLEAR)


@dataclass(frozen=True)
class Settled:
    """An answered cancel request: the story and the human's answer."""

    story: StoryState
    answer: Answer


def answered(state: RunState, answers: dict[str, Answer]) -> list[Settled]:
    """Stories with a cancel request whose question has an answer, in state order."""
    return [
        Settled(s, answers[s.po_hold.question])
        for s in state.stories.values()
        if s.po_hold and s.po_hold.kind is HoldKind.CANCEL and s.po_hold.question in answers
    ]


def _without(ids: list[str], story_id: str) -> None:
    ids[:] = [i for i in ids if i != story_id]


def cancel(state: RunState, settled: Settled) -> None:
    """H11: the only place a story becomes CANCELLED."""
    story = settled.story
    story.status = StoryStatus.CANCELLED
    story.sprint, story.po_hold, story.hold = None, None, None
    for ids in (state.order, state.pulled, state.human_order):
        _without(ids, story.id)


def keep(state: RunState, settled: Settled) -> None:
    """The human kept the story: the request ends."""
    settled.story.po_hold = None


def unclear(state: RunState, settled: Settled) -> None:
    """An unclear answer: hold the story for the PO."""
    asked = settled.story.po_hold
    question = asked.question if asked else ""
    reason = UNCLEAR_ANSWER.format(question=question, answer=settled.answer.text)
    settled.story.po_hold = PoHold(HoldKind.HOLD, reason)


OUTCOMES: dict[Decision, Callable[[RunState, Settled], None]] = {
    Decision.CANCEL: cancel,
    Decision.KEEP: keep,
    Decision.UNCLEAR: unclear,
}


@dataclass
class Clerk:
    """Runs the PO's story admin tools and settles answered cancel requests (H7-H10)."""

    runtime: Runtime

    def run(self, act: Act, args: dict[str, Any]) -> dict[str, Any]:
        """Settle, then refuse or apply, post, save and emit once."""
        self.settle()
        case = self._case(act, args)
        if reason := refusal(case):
            return refused(reason)
        return self._apply(case)

    def settle(self) -> list[str]:
        """Apply every answered cancel request; the ids settled."""
        rt = self.runtime
        done = answered(rt.state, rt.relay.answers())
        for settled in done:
            self._settle_one(settled)
        if done:
            rt.save()
        return [s.story.id for s in done]

    def _case(self, act: Act, args: dict[str, Any]) -> Case:
        sid = str(args.get("story", ""))
        asked = tuple(m.id for m in self.runtime.relay.open_questions() if sid in m.stories)
        story = self.runtime.state.stories.get(sid)
        return Case(act, sid, str(args.get("reason") or ""), story, asked)

    def _apply(self, case: Case) -> dict[str, Any]:
        rt, row, story = self.runtime, TOOLS[case.act], _story(case)
        before = facts(story)
        note = row.note(case)
        question = rt.relay.post(note).id if note else None
        reason = case.reason.strip()
        row.effect(story, Change(reason, question))
        rt.save()
        data = {"tool": str(case.act), "reason": reason, "question": question}
        self._emit(PO_ROLE, story, data | {"before": before, "after": facts(story)})
        return {
            "status": row.status,
            "story": story.id,
            "step": story.step,
            "story_status": str(story.status),
            "question": question,
        }

    def _settle_one(self, settled: Settled) -> None:
        story, asked = settled.story, settled.story.po_hold
        assert asked is not None
        before, decided = facts(story), decision(settled.answer.text)
        OUTCOMES[decided](self.runtime.state, settled)
        data = {
            "tool": "answer",
            "reason": asked.reason,
            "question": asked.question,
            "answer": settled.answer.text,
            "decision": str(decided),
        }
        self._emit(None, story, data | {"before": before, "after": facts(story)})

    def _emit(self, role: str | None, story: StoryState, data: dict[str, Any]) -> None:
        self.runtime.events.emit(Event(EventKind.STORY_ADMIN, role, story.id, data))
