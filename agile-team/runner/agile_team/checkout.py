"""The checkout guard (s61): the runner halts when anyone else moves its branch or HEAD.

``state.checkout`` records the branch and commit the runner expects. Only the
runner's own git writes move it. Every other check compares the live checkout
with the record; a difference is a ``checkout`` halt and the tree is left alone.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import state as state_mod
from . import system
from .config import Config
from .events import EVENTS, Event, EventKind, EventLog
from .gates import StoryState
from .git_ops import Git
from .halt import Halt, HaltKind
from .numbered_queue import NumberedQueue
from .relay import Note, Relay
from .state import CheckoutRecord, RunState, RunStatus
from .workspaces import Workspaces

if TYPE_CHECKING:
    from .dispatch import Runtime

CHECKOUT_HEAD = "checkout changed: "
REASON = CHECKOUT_HEAD + "expected {expected}; found {found}; last HEAD move: {move}"
UNRECORDED = "a branch with no git operation in progress"
DETACHED = "detached HEAD"
IN_PROGRESS = " with a {operation} in progress"
NO_MOVE = "no reflog entry"
MOVE_ARGS = ("log", "-g", "-1", "--date=iso", "--format=%gd %gs", "HEAD")
RESTORED = "restored: {checkout}"
ACCEPTED = "accepted: {checkout}"
ACCEPTED_REASON = "checkout accepted: {checkout}; run `agile-team start --resume`"
NOT_ACCEPTABLE = (
    "cannot accept {found}: check out the team branch and finish or abort any git operation first"
)
OPERATIONS: tuple[tuple[str, str], ...] = (
    ("rebase-merge", "rebase"),
    ("rebase-apply", "rebase"),
    ("MERGE_HEAD", "merge"),
    ("CHERRY_PICK_HEAD", "cherry-pick"),
    ("REVERT_HEAD", "revert"),
    ("BISECT_LOG", "bisect"),
)


class CheckoutChanged(Exception):
    """Raised after the runner recorded a checkout halt; ``halt`` is that halt."""

    def __init__(self, found: Halt) -> None:
        super().__init__(found.reason)
        self.halt = found


class CheckoutError(Exception):
    """``accept-checkout`` cannot accept the live checkout."""


@dataclass(frozen=True)
class Found:
    """The live checkout: branch (``None`` when detached), HEAD, operation in progress."""

    branch: str | None
    head: str
    operation: str | None

    def text(self) -> str:
        """``<branch> at <sha7>`` or ``detached HEAD at <sha7>``, plus the operation (K8)."""
        place = f"{self.branch or DETACHED} at {self.head[:7]}"
        return place + (IN_PROGRESS.format(operation=self.operation) if self.operation else "")


@dataclass(frozen=True)
class Drift:
    """A mismatch: the record, the live checkout and the newest HEAD reflog entry."""

    expected: CheckoutRecord | None
    found: Found
    move: str

    def reason(self) -> str:
        """The halt reason (K8)."""
        expected = self.expected.text() if self.expected else UNRECORDED
        return REASON.format(expected=expected, found=self.found.text(), move=self.move)

    def halt(self) -> Halt:
        """The ``checkout`` halt for this drift."""
        return Halt(HaltKind.CHECKOUT, self.reason())


def operation(git: Git) -> str | None:
    """The first ``OPERATIONS`` name whose path exists in the worktree's git dir."""
    git_dir = Path(git.run("rev-parse", "--absolute-git-dir").strip())
    return next((name for path, name in OPERATIONS if system.exists(git_dir / path)), None)


def read(git: Git) -> Found:
    """The live checkout (K2)."""
    return Found(git.branch(), git.head(), operation(git))


def last_move(git: Git) -> str:
    """The newest HEAD reflog entry, or ``NO_MOVE``."""
    code, out = git.attempt(*MOVE_ARGS)
    return (out.strip() if code == 0 else "") or NO_MOVE


def matches(expected: CheckoutRecord | None, found: Found) -> bool:
    """K2: attached, no operation, and the recorded branch and HEAD when recorded."""
    if found.branch is None or found.operation:
        return False
    return expected is None or (expected.branch, expected.head) == (found.branch, found.head)


def check(git: Git, expected: CheckoutRecord | None) -> Drift | None:
    """``None`` when the checkout matches, else the drift (reads the reflog only then)."""
    found = read(git)
    return None if matches(expected, found) else Drift(expected, found, last_move(git))


def check_worktree(git: Git, story: StoryState) -> Drift | None:
    """B5: ``None`` when the story's worktree is on its branch at the recorded head."""
    return check(git, CheckoutRecord(story.branch, story.worktree_head))


def recorded(git: Git) -> CheckoutRecord:
    """The live branch and HEAD as a record; callers have checked the checkout (K1)."""
    return CheckoutRecord(git.branch() or "", git.head())


def answer_open(relay: Relay, text: str) -> None:
    """Answer every open question whose text starts with ``CHECKOUT_HEAD`` with ``text``."""
    for question in relay.open_questions():
        if question.text.startswith(CHECKOUT_HEAD):
            relay.answer(question.id, text)


@dataclass
class Guard:
    """The checkout check outside a live ``Runtime``: ``start`` and ``accept-checkout``."""

    run_dir: Path
    git: Git

    def on_start(self) -> Halt | None:
        """K6: escalate and return the halt on a mismatch; else record, answer RESTORED."""
        state = state_mod.load(self.run_dir)
        drift = check(self.git, state.checkout)
        if drift is not None:
            return self._escalate(state, drift.halt())
        self._restore(state)
        return None

    def accept(self) -> CheckoutRecord:
        """K7 (the live-runner check is the CLI's): record, status, event, answers."""
        found = read(self.git)
        if found.branch is None or found.operation:
            raise CheckoutError(NOT_ACCEPTABLE.format(found=found.text()))
        state = state_mod.load(self.run_dir)
        old, state.checkout = state.checkout, recorded(self.git)
        self._reopen(state)
        self._log_accepted(old, state.checkout)
        answer_open(Relay(self.run_dir), ACCEPTED.format(checkout=state.checkout.text()))
        return state.checkout

    def _escalate(self, state: RunState, found: Halt) -> Halt:
        state.mark(found.rule.status, found.reason)
        state_mod.save(self.run_dir, state)
        relay, text = Relay(self.run_dir), found.message()
        if all(q.text != text for q in relay.open_questions()):
            relay.post(Note(found.rule.note_kind, text))
        return found

    def _restore(self, state: RunState) -> None:
        if state.checkout is None:
            state.checkout = recorded(self.git)
            state_mod.save(self.run_dir, state)
        text = RESTORED.format(checkout=state.checkout.text())
        answer_open(Relay(self.run_dir), text)

    def _reopen(self, state: RunState) -> None:
        if state.status is RunStatus.CHECKOUT_CHANGED:
            state.mark(RunStatus.STOPPED, ACCEPTED_REASON.format(checkout=state.checkout.text()))
        state_mod.save(self.run_dir, state)

    def _log_accepted(self, old: CheckoutRecord | None, new: CheckoutRecord) -> None:
        data = {"action": "accepted", "from": asdict(old) if old else None, "to": asdict(new)}
        EventLog(self.run_dir / EVENTS).emit(Event(EventKind.CHECKOUT, data=data))


CHECKOUTS = "checkouts"


@dataclass(frozen=True)
class CheckoutRequests:
    """B6: ``accept-checkout --story`` requests, queued while the runner runs."""

    config: Config

    @property
    def numbered(self) -> NumberedQueue:
        """The numbered request files."""
        return NumberedQueue(self.config.run_dir / CHECKOUTS, "c", ".json")

    def publish(self, story_id: str) -> str:
        """Queue a request for ``story_id``; the request's id."""
        return self.numbered.publish(json.dumps({"story": story_id})).id

    def apply(self, runtime: Runtime) -> list[str]:
        """Accept every queued worktree: record its head, clear its drift and hold."""
        accepted = []
        for entry in self.numbered.entries():
            story_id = self._accept(runtime, json.loads(system.read_text(entry.path)))
            system.remove(entry.path)
            accepted += [story_id] if story_id else []
        return accepted

    def _accept(self, runtime: Runtime, request: dict[str, Any]) -> str | None:
        story = runtime.state.stories.get(request.get("story", ""))
        if story is None:
            return None
        tree = Workspaces(runtime.git, runtime.config).path_of(story.id)
        story.worktree_head = Git(tree).head()
        story.drift, story.hold = [], None
        data = {"action": "accepted", "story": story.id, "to": story.worktree_head}
        runtime.events.emit(Event(EventKind.CHECKOUT, story=story.id, data=data))
        runtime.save()
        return story.id
