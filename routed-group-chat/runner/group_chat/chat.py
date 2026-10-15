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
from .compaction import SUMMARY_SYSTEM, build_summary_prompt, split
from .context import build_system_prompt, build_user_prompt
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


def find_handoff(turn: Turn, names: tuple[str, ...]) -> str | None:
    """The member ``turn`` hands the floor to, if it names a valid other member."""
    found = [name.lower() for name in HANDOFF_RE.findall(strip_fences(turn.text))]
    valid = [name for name in found if name in names and name != turn.speaker]
    return valid[-1] if valid else None


@dataclass
class Exchange:
    """One human message in progress: who is still to answer, what came back, handoffs taken."""

    state: ChatState
    queue: list[str]
    replies: list[Turn] = field(default_factory=list)
    hops: int = 0


@dataclass
class GroupChat:
    """A roster, a model backend and a chat directory."""

    roster: Roster
    backend: Backend
    store: Store
    limits: Limits = field(default_factory=Limits)

    def send(self, message: str) -> list[Turn]:
        """Record ``message``, collect the replies, compact, save; return the
        replies (and any orchestrator notes) in order."""
        with self.store.hold_lock():
            state = self.store.load()
            targets = self._record_message(state, message)
            replies = self._answer(Exchange(state, list(targets)))
            replies.extend(self._summarize_old_turns(state))
            self.store.save(state)
            return replies

    def _record_message(self, state: ChatState, message: str) -> tuple[str, ...]:
        """Add the human's message, remember who it addresses and save; the addressees."""
        targets = resolve(message, self.roster.names, state.last_addressed)
        state.add(Turn(HUMAN, message.strip()))
        state.last_addressed = targets
        self.store.save(state)
        return targets

    def _answer(self, exchange: Exchange) -> list[Turn]:
        while exchange.queue:
            turn = self._collect_reply(exchange)
            exchange.replies.append(turn)
            self._pass_floor(exchange, turn)
        return exchange.replies

    def _pass_floor(self, exchange: Exchange, turn: Turn) -> None:
        """Queue the member ``turn`` hands off to, or note that the handoff limit dropped it."""
        target = find_handoff(turn, self.roster.names)
        if target is None or target in exchange.queue:
            return
        if exchange.hops >= self.limits.max_handoffs:
            exchange.replies.append(
                exchange.state.note(f"handoff to @{target} dropped: limit reached")
            )
            return
        exchange.hops += 1
        exchange.queue.append(target)

    def _collect_reply(self, exchange: Exchange) -> Turn:
        name = exchange.queue.pop(0)
        try:
            turn = self._ask_role(exchange.state, name)
        except BackendError as exc:
            note = exchange.state.note(f"@{name} could not answer: {exc}")
            self.store.save(exchange.state)
            raise PartialReplyError([*exchange.replies, note], exc) from exc
        self.store.save(exchange.state)
        return turn

    def _ask_role(self, state: ChatState, name: str) -> Turn:
        role = self.roster.get(name)
        text = self.backend.complete(
            build_system_prompt(role, self.roster), build_user_prompt(role, state), role.model
        )
        turn = Turn(name, text)
        state.add(turn)
        return turn

    def _summarize_old_turns(self, state: ChatState) -> list[Turn]:
        evicted, kept = split(state.turns, self.limits.recent_tokens, self.limits.keep_turns)
        if not evicted:
            return []
        prompt = build_summary_prompt(state.summary, evicted)
        try:
            state.summary = self.backend.complete(SUMMARY_SYSTEM, prompt, self.limits.summary_model)
        except BackendError as exc:
            return [state.note(f"summary skipped, turns kept verbatim: {exc}")]
        state.turns = kept
        return []
