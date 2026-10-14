"""The pinned decision log: decisions and open questions that are never summarized.

Anyone in the chat, human or role, updates it with marker lines in a message:

``DECISION: <text>``  records decision ``D<n>``
``QUESTION: <text>``  opens question ``Q<n>``
``RESOLVED: Q<n>``    closes that question

A marker starts its line, optionally after the line's leading @mentions, so
``@po DECISION: ship Friday`` counts. The log is code-kept, so it cannot drift
the way a summary can.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

MARKER_RE = re.compile(
    r"^\s*(?:@[a-z][a-z0-9-]*[ \t,]*)*(DECISION|QUESTION|RESOLVED):[ \t]*(.+?)[ \t]*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Entry:
    """A numbered decision or question and who raised it."""

    id: str
    text: str
    by: str


@dataclass
class DecisionLog:
    """Decisions (kept forever) and open questions (until resolved)."""

    decisions: list[Entry] = field(default_factory=list)
    questions: list[Entry] = field(default_factory=list)
    next_decision: int = 1
    next_question: int = 1

    def apply(self, speaker: str, text: str) -> None:
        """Apply every marker line in ``text``, in order."""
        for marker, value in MARKER_RE.findall(text):
            HANDLERS[marker](self, speaker, value)

    def render(self) -> str:
        """Markdown for the pinned block."""
        return "\n".join(
            [
                "## Decisions",
                *_lines(self.decisions),
                "## Open questions",
                *_lines(self.questions),
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decisions": [vars(entry) for entry in self.decisions],
            "questions": [vars(entry) for entry in self.questions],
            "next_decision": self.next_decision,
            "next_question": self.next_question,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionLog:
        return cls(
            [Entry(**entry) for entry in data.get("decisions", [])],
            [Entry(**entry) for entry in data.get("questions", [])],
            data.get("next_decision", 1),
            data.get("next_question", 1),
        )


def _lines(entries: list[Entry]) -> list[str]:
    return [f"- [{entry.id}] {entry.text} (by {entry.by})" for entry in entries] or ["- none"]


def _decide(log: DecisionLog, speaker: str, text: str) -> None:
    log.decisions.append(Entry(f"D{log.next_decision}", text, speaker))
    log.next_decision += 1


def _ask(log: DecisionLog, speaker: str, text: str) -> None:
    log.questions.append(Entry(f"Q{log.next_question}", text, speaker))
    log.next_question += 1


def _resolve(log: DecisionLog, _speaker: str, text: str) -> None:
    wanted = text.split(maxsplit=1)[0].upper()
    log.questions = [entry for entry in log.questions if entry.id != wanted]


HANDLERS: dict[str, Callable[[DecisionLog, str, str], None]] = {
    "DECISION": _decide,
    "QUESTION": _ask,
    "RESOLVED": _resolve,
}
