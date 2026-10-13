"""Tool calls of one open query as spans (s98): labels, details, masking, the time split."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from claude_agent_sdk import ToolResultBlock, ToolUseBlock

from .dashboard.step_times import Mark, Platform
from .ledger import PO_ROLE

TOOLS = "tools.jsonl"
LIMIT = 80
DEV = "Dev: "
NAMED_SERVERS: dict[str, str] = {"team": "po", "runner": "runner-tool"}
REASON_KEYS: dict[str, str] = {"Bash": "description"}
DETAIL_KEYS: tuple[str, ...] = (
    "command",
    "file_path",
    "notebook_path",
    "pattern",
    "url",
    "query",
    "path",
    "role",
    "story",
)
WAITING: frozenset[str] = frozenset({"po.run_role"})
STEP_OF_ROLE: dict[str, str] = {PO_ROLE: "po-session"}
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:TOKEN|KEY|SECRET)[A-Z0-9_]*)=(\"[^\"]*\"|'[^']*'|[^\s;&|]+)"
)
TIMED_OUT = re.compile(r"(?i)\btimed out\b")
TIMEOUT_SCAN = 300
ROUND = 3


def _mono_position(mark: Mark) -> float:
    return mark.at if mark.mono is None else mark.mono


def _slept_position(mark: Mark) -> float:
    return mark.at - (mark.slept or 0)


POSITIONS: dict[Platform, Callable[[Mark], float]] = {
    Platform.POSIX: _mono_position,
    Platform.WINDOWS: _slept_position,
}


class Status(StrEnum):
    """How a call ended."""

    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    UNFINISHED = "unfinished"


def masked(text: str) -> str:
    """``text`` with the value of every secret-named assignment replaced by ``***`` (TC10)."""
    return SECRET_ASSIGNMENT.sub(r"\1=***", text)


def awake_gap(platform: Platform, marks: tuple[Mark, Mark]) -> float:
    """Awake seconds between two marks on ``platform``, never negative."""
    position = POSITIONS[platform]
    return round(max(0, position(marks[1]) - position(marks[0])), ROUND)


def shown(text: str) -> str:
    """Masked, whitespace collapsed, cut to ``LIMIT`` characters (TC9)."""
    return " ".join(masked(text).split())[:LIMIT]


def named(tool: str) -> str | None:
    """``po.run_role`` for ``mcp__team__run_role``; ``None`` for any other tool (TC6)."""
    parts = tool.split("__", 2)
    if len(parts) == 3 and parts[0] == "mcp" and parts[1] in NAMED_SERVERS:
        return f"{NAMED_SERVERS[parts[1]]}.{parts[2]}"
    return None


def _reason(use: ToolUseBlock) -> str:
    value = (use.input or {}).get(REASON_KEYS.get(use.name, ""))
    return shown(value) if isinstance(value, str) and value.strip() else use.name


def label(use: ToolUseBlock) -> str:
    """The call's label: its name when named, else ``Dev: <reason>`` (TC6, TC7)."""
    return named(use.name) or DEV + _reason(use)


def detail(tool_input: dict[str, Any]) -> str:
    """The first usable target value of the input, shown (TC8)."""
    values = (tool_input.get(key) for key in DETAIL_KEYS)
    return next((shown(v) for v in values if isinstance(v, str) and v.strip()), "")


def result_text(block: ToolResultBlock) -> str:
    """The result's text: a string as is, text items joined by newlines (TC2)."""
    content = block.content
    if isinstance(content, str):
        return content
    items = content or []
    return "\n".join(i.get("text", "") for i in items if i.get("type") == "text")


def status_of(block: ToolResultBlock) -> Status:
    """``ok``, ``timeout`` or ``error`` (TC2)."""
    if not block.is_error:
        return Status.OK
    found = TIMED_OUT.search(result_text(block)[:TIMEOUT_SCAN])
    return Status.TIMEOUT if found else Status.ERROR


def union(intervals: list[tuple[float, float]]) -> float:
    """The total length covered by ``intervals``, overlaps counted once."""
    total, reach = 0.0, None
    for start, end in sorted(intervals):
        if reach is None or start > reach:
            total += end - start
            reach = end
        elif end > reach:
            total += end - reach
            reach = end
    return total


@dataclass(frozen=True)
class Where:
    """Which step or PO turn a span belongs to (TC5)."""

    role: str
    story: str | None
    step: str | None
    opened_at: float


@dataclass(frozen=True)
class Call:
    """One open call: id, SDK tool name, label, detail and its start."""

    tool_use_id: str
    tool: str
    label: str
    detail: str
    start: Mark

    @classmethod
    def of(cls, use: ToolUseBlock, start: Mark) -> Call:
        """The call a ``ToolUseBlock`` opens at ``start``."""
        return cls(use.id, use.name, label(use), detail(use.input or {}), start)


OPEN = "open"


def start_row(where: Where, call: Call) -> dict[str, Any]:
    """A call's TC11 keys up to ``slept``: who, what and its start."""
    return {
        "role": where.role,
        "story": where.story,
        "step": where.step,
        "opened_at": where.opened_at,
        "tool": call.tool,
        "tool_use_id": call.tool_use_id,
        "label": call.label,
        "detail": call.detail,
        "at": call.start.at,
        "mono": call.start.mono,
        "slept": call.start.slept,
    }


def open_row(where: Where, call: Call) -> dict[str, Any]:
    """An open call as a heartbeat row (N11): ``start_row`` plus ``"status": "open"``."""
    return {**start_row(where, call), "status": OPEN}


@dataclass(frozen=True)
class ToolSpan:
    """One finished call (TC11)."""

    where: Where
    call: Call
    end: Mark
    seconds: float
    status: Status

    def as_dict(self) -> dict[str, Any]:
        """The span line's object, keys in order."""
        return {
            **start_row(self.where, self.call),
            "seconds": self.seconds,
            "ended_at": self.end.at,
            "status": str(self.status),
        }

    def line(self) -> str:
        """The JSON line."""
        return json.dumps(self.as_dict())


@dataclass(frozen=True)
class Split:
    """A meter's time split (TC12)."""

    tool_s: float
    model_s: float
    waiting_s: float

    def as_dict(self) -> dict[str, float]:
        """The three fields as event data."""
        return {"tool_s": self.tool_s, "model_s": self.model_s, "waiting_s": self.waiting_s}


@dataclass(eq=False)
class Calls:
    """The calls of one reading: open ones by id, every closed span, the spans not yet written."""

    where: Where
    platform: Platform = Platform.POSIX
    open: dict[str, Call] = field(default_factory=dict)
    spans: list[ToolSpan] = field(default_factory=list)
    fresh: list[ToolSpan] = field(default_factory=list)

    def _position(self, mark: Mark) -> float:
        return POSITIONS[self.platform](mark)

    def start(self, uses: list[ToolUseBlock], mark: Mark) -> None:
        """Open a call for each use not seen before (TC1)."""
        for use in uses:
            self.open.setdefault(use.id, Call.of(use, mark))

    def finish(self, results: list[ToolResultBlock], mark: Mark) -> None:
        """Close the open call each result answers; ignore the rest (TC1)."""
        for block in results:
            call = self.open.pop(block.tool_use_id, None)
            if call is not None:
                self._close(call, mark, status_of(block))

    def abandon(self, mark: Mark) -> None:
        """Close every call still open at ``mark`` as unfinished (TC3)."""
        calls, self.open = list(self.open.values()), {}
        for call in calls:
            self._close(call, mark, Status.UNFINISHED)

    def _close(self, call: Call, mark: Mark, status: Status) -> None:
        span = ToolSpan(
            self.where, call, mark, awake_gap(self.platform, (call.start, mark)), status
        )
        self.spans.append(span)
        self.fresh.append(span)

    def opened(self) -> list[dict[str, Any]]:
        """The open calls as heartbeat rows, in opening order."""
        return [open_row(self.where, c) for c in self.open.values()]

    def take_fresh(self) -> list[ToolSpan]:
        """The spans closed since the last call, once."""
        fresh, self.fresh = self.fresh, []
        return fresh

    def _interval(self, span: ToolSpan) -> tuple[float, float]:
        begin = self._position(span.call.start)
        return begin, max(begin, self._position(span.end))

    def split(self, start: Mark, end: Mark) -> Split:
        """The time split of a reading opened at ``start`` and closed at ``end`` (TC12)."""
        awake = max(0, self._position(end) - self._position(start))
        busy = union([self._interval(s) for s in self.spans])
        waiting = union([self._interval(s) for s in self.spans if s.call.label in WAITING])
        return Split(
            round(busy - waiting, ROUND),
            round(max(0, awake - busy), ROUND),
            round(waiting, ROUND),
        )
