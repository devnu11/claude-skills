"""Repeated-setback detection: normalised keys, streaks and the back-and-forth run.

A setback is a gate outcome that sends a story back or holds it. Two rules
read them: the same reason in a row (the streak) and bounces in a row between
one pair of steps whatever the reasons (the run). Both are data and pure
functions; ``gates.Pipeline`` decides what to do with the answer.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .events import Event
    from .gates import StoryState


class Author(StrEnum):
    """Who wrote a setback's reason: a role's handoff, or the runner's own check."""

    ROLE = "role"
    RUNNER = "runner"


class Fault(StrEnum):
    """Where the Manager puts the blame for a repeated setback."""

    RUNNER = "runner"
    PIPELINE = "pipeline"
    OFF_PIPELINE = "off_pipeline"


class Rule(StrEnum):
    """Which rule escalated a story."""

    REPEAT = "repeat"
    BACKSTOP = "backstop"


NORMALISE: tuple[tuple[re.Pattern[str], str], ...] = (
    # ISO date-times: 2026-10-10t12:00:00.5+02:00
    (
        re.compile(r"\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:z|[+-]\d{2}:?\d{2})?"),
        "<time>",
    ),
    (re.compile(r"[a-z][a-z0-9+.-]*://\S+"), "<url>"),  # URLs, before host:port and paths
    (re.compile(r"\b[\w.-]+:\d{2,5}\b"), "<host>"),  # host:port, 127.0.0.1:8799
    (re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]m)?\b"), "<time>"),  # clock times
    (re.compile(r"[\w.~@+-]*/[\w.~@+/-]*"), "<path>"),  # anything with a slash
    (re.compile(r"\b[a-z]\d+\b"), "<id>"),  # s4, e451, m3, q3
    (re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b"), "<sha>"),  # commit shas
    (re.compile(r"(?<![a-z_])\d+(?:\.\d+)?"), "<n>"),  # counts, codes, durations, pids
    (re.compile(r"\s+"), " "),
)
HISTORY_KINDS = frozenset({"gate", "step-end", "test-dispute", "escalation", "ruling", "fault"})
BACKSTOP_HEAD = (
    "bounced {count} times in a row between {step} and {to_step}, reasons not all the same:"
)
BACKSTOP_LINE = "- {event}: {reason}"
COUNTED = frozenset({"bounce", "return"})


def normalise(reason: str) -> str:
    """The reason with ids, counts, times, ports and paths replaced by placeholders."""
    text = reason.lower()
    for pattern, replacement in NORMALISE:
        text = pattern.sub(replacement, text)
    return text.strip()


@dataclass
class Setback:
    """One bounce, return or hold; ``key`` is always recomputed from the other fields."""

    step: str
    to_step: str
    role: str
    verdict: str
    author: Author
    reason: str
    event: str = ""
    key: str = ""

    def __post_init__(self) -> None:
        self.author = Author(self.author)
        self.verdict = str(self.verdict)
        self.key = f"{self.step}>{self.to_step} {normalise(self.reason)}"

    @property
    def pair(self) -> tuple[str, str]:
        """The two steps the story moved between."""
        return (self.step, self.to_step)


# ----- the same reason in a row ---------------------------------------------


def repeats(streak: list[Setback], setback: Setback) -> int:
    """The length of the streak when ``setback`` has the same key, else 0."""
    return len(streak) if streak and streak[-1].key == setback.key else 0


def extend(streak: list[Setback], setback: Setback) -> list[Setback]:
    """The streak with ``setback`` added, or restarted at it when the key changed."""
    return [*streak, setback] if repeats(streak, setback) else [setback]


# ----- bounces in a row between one pair of steps ---------------------------


def counts(setback: Setback) -> bool:
    """A bounce or return that crosses between two steps."""
    return setback.verdict in COUNTED and setback.to_step != setback.step


def extend_run(run: list[Setback], setback: Setback) -> list[Setback]:
    """The run with ``setback`` added, or restarted at it when the pair changed."""
    same = bool(run) and run[-1].pair == setback.pair
    return [*run, setback] if same else [setback]


def after_pass(run: list[Setback], step: str) -> list[Setback]:
    """Empty when the step that kept sending the story back has now passed it."""
    return [] if run and run[-1].step == step else run


def bounces(run: list[Setback], setback: Setback) -> int:
    """The run length when ``setback`` continues it, else 0."""
    same = bool(run) and counts(setback) and run[-1].pair == setback.pair
    return len(run) if same else 0


def backstop_reason(run: list[Setback]) -> str:
    """Every reason in the run, one line each, under a head line."""
    last = run[-1]
    head = BACKSTOP_HEAD.format(count=len(run), step=last.step, to_step=last.to_step)
    lines = [BACKSTOP_LINE.format(event=s.event or "now", reason=s.reason) for s in run]
    return "\n".join([head, *lines])


TRAILS = {Rule.REPEAT: lambda s: s.streak, Rule.BACKSTOP: lambda s: s.run}


def trail(story: StoryState) -> list[Setback]:
    """The setbacks that made the rule escalate ``story``."""
    return TRAILS[story.escalated_by or Rule.REPEAT](story)


# ----- what the Manager sees ------------------------------------------------


def _number(event_id: str) -> int:
    return int(event_id[1:])


def _first_number(setbacks: list[Setback]) -> int:
    return min((_number(s.event) for s in setbacks if s.event), default=0)


def _history_events(story: StoryState, events: list[Event]) -> list[dict[str, Any]]:
    first = _first_number(trail(story))
    mine = [e for e in events if e.story == story.id and e.kind in HISTORY_KINDS]
    return [asdict(e) for e in mine if _number(e.id) >= first]


def manager_view(story: StoryState, events: list[Event]) -> dict[str, Any]:
    """The ``repeated_setback`` entry of the Manager's runner context."""
    setbacks = trail(story)
    last = setbacks[-1]
    return {
        "story": story.id,
        "reason": story.repeated,
        "rule": story.escalated_by,
        "pair": f"{last.step}>{last.to_step}",
        "key": last.key,
        "count": len(setbacks),
        "author": last.author,
        "history": [asdict(s) for s in setbacks],
        "events": _history_events(story, events),
    }
