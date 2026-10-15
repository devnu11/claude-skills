"""The PO's revert_story tool (s124): revert a story's commits and put it back in the backlog.

The pure rules come first; ``Reverter`` does the git, file, state, event and relay I/O.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from . import priority, revert_log, story_admin, story_spec, system
from .dispatch import Runtime, refused
from .events import Event, EventKind
from .gates import CHECKPOINT_STEPS, FINISHED, StoryState
from .git_ops import GitError
from .holds import HoldKind, PoHold
from .pending_tests import PendingSet
from .relay import Answer, Note
from .revert_log import RevertEntry

NOTHING_TO_REVERT = "story {story} has no commits to revert"
DEPENDED_ON = "started stories depend on {story}: {ids}; revert them first, or keep {story}"
NOT_ON_BRANCH = (
    "story {story}'s first commit {sha} is not on the checked-out branch; nothing was reverted"
)
REVERT_CONFLICT = "reverting story {story} stopped: {why}; nothing was reverted"
REVERT_QUESTION = (
    'Revert story {story} ("{title}") again? It was reverted {count}× already (last: {last}). '  # noqa: RUF001
    'The PO asks because: {reason} Answer "revert" to revert it or "keep" to keep it.'
)
UNCLEAR_REVERT = 'the answer to {question} was neither "revert" nor "keep": {answer}'
REVERT_FAILED = "the human said revert to {question}, but the revert failed: {why}"
REVERT_SUBJECT = "revert({story}): {title}"
REVERT_BODY = "Reverts {commits}.\n\nReason: {reason}"
RECORD_SUBJECT = "chore({story}): record the revert in the story file"
NOTICE = (
    'Story {story} ("{title}") was reverted in sprint {sprint}: {reason} '
    "Reverted commits: {commits}; revert commit {revert}. It is back in the backlog at {step}."
)
TESTS_STEP = "tests"
FIXUP = "fixup! "
REFUSED = "refused"


class Decision(StrEnum):
    """What the human's answer to a revert question means."""

    REVERT = "revert"
    KEEP = "keep"
    UNCLEAR = "unclear"


DECISIONS = {"revert": Decision.REVERT, "keep": Decision.KEEP}


@dataclass(frozen=True)
class Call:
    """One revert: story id, reason, and the answered question for a second revert."""

    story_id: str
    reason: str
    question: str | None = None


@dataclass(frozen=True)
class Back:
    """What the reset story gets (R6)."""

    step: str
    entry: RevertEntry
    owed: list[str]


@dataclass(frozen=True)
class Settling:
    """An answered revert question: the story and the human's answer."""

    story: StoryState
    answer: Answer


def story_commits(log: list[tuple[str, str]], subject: str) -> list[str]:
    """R4 (b): the shas whose subject is ``subject`` or ``fixup! {subject}``, in log order."""
    return [sha for sha, text in log if text in (subject, FIXUP + subject)]


def back_step(steps: list[str], current: str) -> str:
    """R6: the last non-checkpoint step before tests; the current step when it comes earlier."""
    before = steps[: steps.index(TESTS_STEP)] if TESTS_STEP in steps else []
    open_steps = [i for i, s in enumerate(before) if s not in CHECKPOINT_STEPS]
    target = open_steps[-1] if open_steps else 0
    here = steps.index(current) if current in steps else len(steps)
    return steps[min(target, here)]


def worked_roles(events: list[Event], story_id: str) -> list[str]:
    """R8: the distinct roles of the story's step-end events, in first-seen order."""
    roles = [e.role for e in events if e.kind == EventKind.STEP_END and e.story == story_id]
    return list(dict.fromkeys(r for r in roles if r))


def dependents(stories: dict[str, StoryState], story_id: str) -> list[str]:
    """R1 (8): ids of started, unfinished stories that list ``story_id`` in ``depends_on``."""
    return [
        s.id
        for s in stories.values()
        if priority.started(s) and s.status not in FINISHED and story_id in s.depends_on
    ]


def reverted_story(story: StoryState, back: Back) -> StoryState:
    """R6: a fresh story back in the backlog, keeping its identity and its revert history."""
    return StoryState(
        story.id,
        story.title,
        back.step,
        developer=story.developer,
        po_developer=story.po_developer,
        depends_on=story.depends_on,
        file_commits=story.file_commits,
        reverted=[*story.reverted, back.entry],
        revert_owed=back.owed,
        trace=story.trace,
    )


def decision(text: str) -> Decision:
    """R3: what the human's answer means."""
    return DECISIONS.get(text.strip(story_admin.ANSWER_STRIP).lower(), Decision.UNCLEAR)


def _today() -> str:
    return datetime.fromtimestamp(system.now(), UTC).strftime("%Y-%m-%d")


def _shorts(shas: list[str]) -> str:
    return ", ".join(map(revert_log.short, shas))


def _message(story: StoryState, call: Call, shas: list[str]) -> str:
    subject = REVERT_SUBJECT.format(story=story.id, title=story.title)
    return f"{subject}\n\n{REVERT_BODY.format(commits=_shorts(shas), reason=call.reason.strip())}"


def _notice(story: StoryState, entry: RevertEntry) -> str:
    return NOTICE.format(
        story=story.id,
        title=story.title,
        sprint=entry.sprint,
        reason=entry.reason,
        commits=_shorts(entry.commits),
        revert=revert_log.short(entry.revert),
        step=story.step,
    )


def _question_text(story: StoryState, reason: str) -> str:
    return REVERT_QUESTION.format(
        story=story.id,
        title=story.title,
        count=len(story.reverted),
        last=story.reverted[-1].reason,
        reason=reason,
    )


@dataclass
class Reverter:
    """Runs revert_story and settles answered revert questions (R1-R12)."""

    runtime: Runtime

    def run(self, args: dict[str, Any]) -> dict[str, Any]:
        """Settle, check, then ask (a story reverted before) or revert."""
        self.settle()
        call = Call(str(args.get("story", "")), str(args.get("reason") or ""))
        if why := self._refusal(call):
            return refused(why)
        story = self.runtime.state.stories[call.story_id]
        return self._ask(story, call) if story.reverted else self.revert(story, call)

    def settle(self) -> list[str]:
        """R3: settle every answered revert question; the ids settled."""
        rt, answers = self.runtime, self.runtime.relay.answers()
        done = [
            Settling(s, answers[s.po_hold.question])
            for s in rt.state.stories.values()
            if s.po_hold and s.po_hold.kind is HoldKind.REVERT and s.po_hold.question in answers
        ]
        for settling in done:
            self._settle_one(settling)
        if done:
            rt.save()
        return [s.story.id for s in done]

    def _refusal(self, call: Call) -> str | None:
        """R1 (3)-(9): the first refusal."""
        story = self.runtime.state.stories.get(call.story_id)
        if story is None:
            return story_admin.UNKNOWN.format(story=call.story_id)
        checks = [
            lambda: None if call.reason.strip() else story_admin.NO_REASON,
            lambda: self._finished(story),
            lambda: story_admin.asked_text(story),
            lambda: self.unfit(story),
        ]
        return priority.first_refusal(checks)

    def _finished(self, story: StoryState) -> str | None:
        if story.status not in FINISHED:
            return None
        return story_admin.FINISHED_TEXT.format(story=story.id, status=story.status, verb="revert")

    def unfit(self, story: StoryState) -> str | None:
        """R1 (7)-(9): no commits, depended on, or the first commit is off the branch."""
        if story.commit is None:
            return NOTHING_TO_REVERT.format(story=story.id)
        ids = dependents(self.runtime.state.stories, story.id)
        if ids:
            return DEPENDED_ON.format(story=story.id, ids=", ".join(ids))
        if not self.runtime.git.is_ancestor(story.commit):
            return NOT_ON_BRANCH.format(story=story.id, sha=revert_log.short(story.commit))
        return None

    def _ask(self, story: StoryState, call: Call) -> dict[str, Any]:
        """R2: ask the human before reverting a story again."""
        rt, before, reason = self.runtime, story_admin.facts(story), call.reason.strip()
        note = Note("question", _question_text(story, reason), [story.id])
        question = rt.relay.post(note).id
        story.po_hold = PoHold(HoldKind.REVERT, reason, question)
        rt.save()
        data = {"tool": "revert_story", "reason": reason, "question": question}
        self._admin(story_admin.PO_ROLE, story, data | self._facts(before, story))
        return {
            "status": "revert requested",
            "story": story.id,
            "step": story.step,
            "question": question,
        }

    def revert(self, story: StoryState, call: Call) -> dict[str, Any]:
        """R4: revert the story's commits, record it and reset it."""
        if not self.runtime.git.is_clean():
            self.runtime.settle_po()
        try:
            shas, revert = self._undo(story, call)
        except GitError as error:
            return refused(REVERT_CONFLICT.format(story=story.id, why=error))
        entry = RevertEntry(_today(), self.runtime.state.sprint, call.reason.strip(), shas, revert)
        entry.record = self._record(story, entry)
        self.runtime.set_pending(PendingSet(story.id, ()))
        self.runtime.record_checkout()
        return self._done(story, entry, call)

    def _done(self, story: StoryState, entry: RevertEntry, call: Call) -> dict[str, Any]:
        """R6, R7, R10: reset the story, announce it and report."""
        old_step, fresh = story.step, self._reset(story, entry)
        self._announce(fresh, old_step, call)
        return {
            "status": "reverted",
            "story": fresh.id,
            "step": fresh.step,
            "commits": entry.commits,
            "revert": entry.revert,
            "record": entry.record,
            "count": len(fresh.reverted),
        }

    def _undo(self, story: StoryState, call: Call) -> tuple[list[str], str]:
        """R4 (b)-(c): the story's commits (oldest first) and the revert commit's sha."""
        assert story.commit is not None
        log = self.runtime.git.log_from(story.commit)
        shas = story_commits(log, self.runtime.git.subject(story.commit))
        return shas, self.runtime.git.revert_all(shas[::-1], _message(story, call, shas))

    def _record(self, story: StoryState, entry: RevertEntry) -> str:
        """R5: add the entry to the story file and commit it."""
        config = self.runtime.config
        file = story_spec.file_of(config, story.id)
        path = config.repo / file
        system.write_text(path, revert_log.with_entry(system.read_text(path), entry))
        return self.runtime.git.commit([file], RECORD_SUBJECT.format(story=story.id))

    def _reset(self, story: StoryState, entry: RevertEntry) -> StoryState:
        """R6: put a fresh story back in the backlog."""
        rt = self.runtime
        roles = worked_roles(rt.events.events(), story.id)
        back = Back(back_step(rt.pipeline.steps, story.step), entry, roles)
        rt.state.stories[story.id] = fresh = reverted_story(story, back)
        rt.state.pulled = [i for i in rt.state.pulled if i != story.id]
        rt.save()
        return fresh

    def _announce(self, story: StoryState, old_step: str, call: Call) -> None:
        """R7 and R10: the one event and the notification."""
        rt, entry = self.runtime, story.reverted[-1]
        data = {
            "sprint": rt.state.sprint,
            "reason": entry.reason,
            "commits": entry.commits,
            "revert": entry.revert,
            "record": entry.record,
            "count": len(story.reverted),
            "from_step": old_step,
            "step": story.step,
            "roles": story.revert_owed,
            "question": call.question,
        }
        rt.events.emit(Event(EventKind.STORY_REVERTED, story_admin.PO_ROLE, story.id, data))
        rt.relay.post(Note("update", _notice(story, entry), [story.id]))

    def _facts(self, before: dict[str, Any], story: StoryState) -> dict[str, Any]:
        return {"before": before, "after": story_admin.facts(story)}

    def _admin(self, role: str | None, story: StoryState, data: dict[str, Any]) -> None:
        self.runtime.events.emit(Event(EventKind.STORY_ADMIN, role, story.id, data))

    def _settle_one(self, settling: Settling) -> None:
        """R3: apply the human's answer and emit the story-admin event."""
        story, asked = settling.story, settling.story.po_hold
        assert asked is not None
        before, decided = story_admin.facts(story), decision(settling.answer.text)
        failed = OUTCOMES[decided](self, settling)
        data = {
            "tool": "answer",
            "reason": asked.reason,
            "question": asked.question,
            "answer": settling.answer.text,
            "decision": str(decided),
        }
        data |= {"failed": failed} if failed else {}
        after = self.runtime.state.stories[story.id]
        self._admin(None, after, data | self._facts(before, after))


def _do_revert(reverter: Reverter, settling: Settling) -> str | None:
    """The human said revert: revert; on failure hold the story."""
    story, asked = settling.story, settling.story.po_hold
    assert asked is not None
    why = reverter.unfit(story)
    result = (
        refused(why)
        if why
        else reverter.revert(story, Call(story.id, asked.reason, asked.question))
    )
    if result["status"] != REFUSED:
        return None
    text = str(result["reason"])
    story.po_hold = PoHold(HoldKind.HOLD, REVERT_FAILED.format(question=asked.question, why=text))
    return text


def _do_keep(reverter: Reverter, settling: Settling) -> str | None:
    """The human kept the story: the request ends."""
    settling.story.po_hold = None
    return None


def _do_unclear(reverter: Reverter, settling: Settling) -> str | None:
    """An unclear answer: hold the story for the PO."""
    asked = settling.story.po_hold
    question = asked.question if asked else ""
    reason = UNCLEAR_REVERT.format(question=question, answer=settling.answer.text)
    settling.story.po_hold = PoHold(HoldKind.HOLD, reason)
    return None


OUTCOMES: dict[Decision, Callable[[Reverter, Settling], str | None]] = {
    Decision.REVERT: _do_revert,
    Decision.KEEP: _do_keep,
    Decision.UNCLEAR: _do_unclear,
}
