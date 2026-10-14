"""The orchestrator: one human message in, the addressed roles' replies out.

Routing is code, not a model's choice: ``addressing`` picks the responders, each
answers in turn with the whole thread in view, and a reply with a
``HANDOFF: @name`` line passes the floor on, up to ``Limits.max_handoffs`` per
message (fenced code does not count). A handoff to the speaker, to an unknown
name or to a role already waiting in this message's queue is ignored.

The whole message runs under the chat's lock, and state is saved after the
human's message and after every reply, so a model failure never loses work
already paid for: the failure is noted in the thread and ``PartialReplyError``
carries the replies that did arrive. Compaction is best-effort; if the summary
call fails, the turns stay verbatim and the next message tries again.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .addressing import resolve
from .backend import Backend, BackendError
from .compaction import SUMMARY_SYSTEM, split, summary_prompt
from .context import system_prompt, user_prompt
from .decision_log import PREFIX, strip_fences
from .roster import Roster
from .state import HUMAN, ChatState, Store, Turn

HANDOFF_RE = re.compile(PREFIX + r"HANDOFF:(?:\*\*)?[ \t]*@([A-Za-z][A-Za-z0-9-]*)", re.MULTILINE)


class PartialReplyError(BackendError):
    """A model call failed mid-message; ``replies`` holds what did arrive. Re-sending
    the message records the human turn again."""

    def __init__(self, replies: list[Turn], cause: BackendError) -> None:
        super().__init__(str(cause))
        self.replies = replies


@dataclass(frozen=True)
class Limits:
    """Token budget for verbatim turns, turns always kept, handoffs per message."""

    recent_tokens: int = 6000
    keep_turns: int = 4
    max_handoffs: int = 2
    summary_model: str | None = None


def handoff_of(text: str, names: tuple[str, ...], speaker: str) -> str | None:
    """The member a reply hands the floor to, if it names a valid other member."""
    found = [name.lower() for name in HANDOFF_RE.findall(strip_fences(text))]
    valid = [name for name in found if name in names and name != speaker]
    return valid[-1] if valid else None


@dataclass
class GroupChat:
    """A roster, a model backend and a chat directory."""

    roster: Roster
    backend: Backend
    store: Store
    limits: Limits = field(default_factory=Limits)

    def say(self, message: str) -> list[Turn]:
        """Record ``message``, collect the replies, compact, save; return the
        replies (and any orchestrator notes) in order."""
        with self.store.locked():
            state = self.store.load()
            targets = resolve(message, self.roster.names(), state.last_addressed)
            state.add(Turn(HUMAN, message.strip()))
            state.last_addressed = targets
            self.store.save(state)
            replies = self._answer(state, list(targets))
            replies.extend(self._compact(state))
            self.store.save(state)
            return replies

    def _answer(self, state: ChatState, queue: list[str]) -> list[Turn]:
        replies: list[Turn] = []
        hops = 0
        while queue:
            turn = self._reply_or_fail(state, queue.pop(0), replies)
            replies.append(turn)
            nxt = handoff_of(turn.text, self.roster.names(), turn.speaker)
            if nxt is None or nxt in queue:
                continue
            if hops >= self.limits.max_handoffs:
                replies.append(state.note(f"handoff to @{nxt} dropped: limit reached"))
                continue
            hops += 1
            queue.append(nxt)
        return replies

    def _reply_or_fail(self, state: ChatState, name: str, replies: list[Turn]) -> Turn:
        try:
            turn = self._reply(state, name)
        except BackendError as exc:
            note = state.note(f"@{name} could not answer: {exc}")
            self.store.save(state)
            raise PartialReplyError([*replies, note], exc) from exc
        self.store.save(state)
        return turn

    def _reply(self, state: ChatState, name: str) -> Turn:
        role = self.roster.get(name)
        text = self.backend.complete(
            system_prompt(role, self.roster), user_prompt(role, state), role.model
        )
        turn = Turn(name, text)
        state.add(turn)
        return turn

    def _compact(self, state: ChatState) -> list[Turn]:
        evicted, kept = split(state.turns, self.limits.recent_tokens, self.limits.keep_turns)
        if not evicted:
            return []
        prompt = summary_prompt(state.summary, evicted)
        try:
            state.summary = self.backend.complete(SUMMARY_SYSTEM, prompt, self.limits.summary_model)
        except BackendError as exc:
            return [state.note(f"summary skipped, turns kept verbatim: {exc}")]
        state.turns = kept
        return []
