"""The pinned decision log: decisions and open questions that are never summarized.

Anyone in the chat, human or role, updates it with marker lines in a message:

``DECISION: <text>``     records decision ``D<n>``
``QUESTION: <text>``     opens question ``Q<n>``
``RESOLVED: Q<n>[, Q<m>]`` closes the comma-separated ids that open its text

A marker starts its line, optionally after the line's leading @mentions, a
``-``/``*`` bullet or ``**`` bold, so ``@po DECISION: ship Friday`` and
``- **DECISION: ship**`` count. Markers are upper case. Lines inside fenced
code (```` ``` ```` or ``~~~``; an unclosed fence runs to the end) never count,
and a marker whose text is blank or only ``*`` is ignored. The log is code-kept, so it cannot
drift the way a summary can.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .schema import check, check_items

PREFIX = r"^[ \t]*(?:[-*][ \t]+)?(?:@[A-Za-z][A-Za-z0-9-]*[ \t,]*)*(?:\*\*)?"
# ``**`` right after the colon is consumed possessively (``*+``-style atomic
# group), so ``DECISION:**`` with nothing after it has no text to record; a
# trailing ``**`` closing the bold is dropped from the text.
MARKER_RE = re.compile(
    PREFIX + r"(DECISION|QUESTION|RESOLVED):(?>(?:\*\*)?)[ \t]*(\S.*?)(?:\*\*)?[ \t]*$",
    re.MULTILINE,
)
FENCES = ("```", "~~~")
LOG_FIELDS: dict[str, type] = {
    "decisions": list,
    "questions": list,
    "next_decision": int,
    "next_question": int,
}
ENTRY_FIELDS: dict[str, type] = {"id": str, "text": str, "by": str}
RESOLVED_IDS_RE = re.compile(r"Q\d+(?:[ \t]*,[ \t]*Q\d+)*", re.IGNORECASE)
QUESTION_ID_RE = re.compile(r"Q\d+", re.IGNORECASE)


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
        """Apply every marker line in ``text`` outside fenced code, in order."""
        for marker, value in MARKER_RE.findall(strip_fences(text)):
            if value.strip("* \t"):
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
        """JSON-ready form, read back by ``from_dict``."""
        return {
            "decisions": [vars(entry) for entry in self.decisions],
            "questions": [vars(entry) for entry in self.questions],
            "next_decision": self.next_decision,
            "next_question": self.next_question,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionLog:
        """The log saved by ``to_dict``; missing keys take their defaults."""
        return cls(
            [Entry(**entry) for entry in data.get("decisions", [])],
            [Entry(**entry) for entry in data.get("questions", [])],
            data.get("next_decision", 1),
            data.get("next_question", 1),
        )


def validate(data: Any, error: type[Exception]) -> None:
    """Raise ``error`` unless ``data`` has the shape ``DecisionLog.to_dict`` writes."""
    check(data, LOG_FIELDS, "log", error)
    for key in ("decisions", "questions"):
        entries = data.get(key, [])
        check_items(entries, dict, f"log.{key}", error)
        for entry in entries:
            check(entry, ENTRY_FIELDS, f"log.{key} entry", error, required=ENTRY_FIELDS)


def strip_fences(text: str) -> str:
    """``text`` without its fenced code blocks; an unclosed fence runs to the end.
    A backtick line that also closes itself (```` ```x``` ````) is inline code."""
    kept: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        fence, keep = _fence_step(fence, line.lstrip())
        if keep:
            kept.append(line)
    return "\n".join(kept)


def _fence_step(fence: str | None, line: str) -> tuple[str | None, bool]:
    """The fence still open after ``line``, and whether ``line`` is kept."""
    if fence is not None:
        return (None if line.startswith(fence) else fence), False
    opener = next((mark for mark in FENCES if line.startswith(mark)), None)
    if opener is None or opener in line[len(opener) :]:
        return None, True
    return opener, False


def _lines(entries: list[Entry]) -> list[str]:
    return [f"- [{entry.id}] {entry.text} (by {entry.by})" for entry in entries] or ["- none"]


def _decide(log: DecisionLog, speaker: str, text: str) -> None:
    log.decisions.append(Entry(f"D{log.next_decision}", text, speaker))
    log.next_decision += 1


def _ask(log: DecisionLog, speaker: str, text: str) -> None:
    log.questions.append(Entry(f"Q{log.next_question}", text, speaker))
    log.next_question += 1


def _resolve(log: DecisionLog, _speaker: str, text: str) -> None:
    ids = RESOLVED_IDS_RE.match(text)
    closed = {found.upper() for found in QUESTION_ID_RE.findall(ids.group())} if ids else set()
    log.questions = [entry for entry in log.questions if entry.id not in closed]


HANDLERS: dict[str, Callable[[DecisionLog, str, str], None]] = {
    "DECISION": _decide,
    "QUESTION": _ask,
    "RESOLVED": _resolve,
}
