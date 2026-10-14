"""The orchestrator: one human message in, the addressed roles' replies out.

Routing is code, not a model's choice: ``addressing`` picks the responders, each
answers in turn with the whole thread in view, and a reply ending in
``HANDOFF: @name`` passes the floor on, up to ``Limits.max_handoffs`` per message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .addressing import resolve
from .backend import Backend
from .compaction import SUMMARY_SYSTEM, split, summary_prompt
from .context import system_prompt, user_prompt
from .roster import Roster
from .state import HUMAN, ORCHESTRATOR, ChatState, Store, Turn

HANDOFF_RE = re.compile(r"^\s*HANDOFF:\s*@([a-z][a-z0-9-]*)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Limits:
    """Token budget for verbatim turns, turns always kept, handoffs per message."""

    recent_tokens: int = 6000
    keep_turns: int = 4
    max_handoffs: int = 2
    summary_model: str | None = None


def handoff_of(text: str, names: tuple[str, ...], speaker: str) -> str | None:
    """The member a reply hands the floor to, if it names a valid other member."""
    found = [name for name in HANDOFF_RE.findall(text) if name in names and name != speaker]
    return found[-1] if found else None


@dataclass
class GroupChat:
    roster: Roster
    backend: Backend
    store: Store
    limits: Limits = field(default_factory=Limits)

    def say(self, message: str) -> list[Turn]:
        """Record ``message``, collect the replies, compact, save; return the replies."""
        state = self.store.load()
        targets = resolve(message, self.roster.names(), state.last_addressed)
        state.add(Turn(HUMAN, message.strip()))
        replies = self._answer(state, list(targets))
        state.last_addressed = targets
        self._compact(state)
        self.store.save(state)
        return replies

    def _answer(self, state: ChatState, queue: list[str]) -> list[Turn]:
        replies: list[Turn] = []
        hops = 0
        while queue:
            turn = self._reply(state, queue.pop(0))
            replies.append(turn)
            nxt = handoff_of(turn.text, self.roster.names(), turn.speaker)
            if nxt is None:
                continue
            if hops >= self.limits.max_handoffs:
                replies.append(self._note(state, f"handoff to @{nxt} dropped: limit reached"))
                continue
            hops += 1
            queue.append(nxt)
        return replies

    def _reply(self, state: ChatState, name: str) -> Turn:
        role = self.roster.get(name)
        text = self.backend.complete(
            system_prompt(role, self.roster), user_prompt(role, state), role.model
        )
        turn = Turn(name, text)
        state.add(turn)
        return turn

    def _note(self, state: ChatState, text: str) -> Turn:
        turn = Turn(ORCHESTRATOR, text)
        state.turns.append(turn)
        return turn

    def _compact(self, state: ChatState) -> None:
        evicted, kept = split(state.turns, self.limits.recent_tokens, self.limits.keep_turns)
        if not evicted:
            return
        prompt = summary_prompt(state.summary, evicted)
        state.summary = self.backend.complete(SUMMARY_SYSTEM, prompt, self.limits.summary_model)
        state.turns = kept
