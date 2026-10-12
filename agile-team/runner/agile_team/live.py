"""The live meter (s44): turns from a query's stream, the heartbeat file, open steps and chores."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from claude_agent_sdk import AssistantMessage, ToolResultBlock, ToolUseBlock, UserMessage

from .events import INTERRUPTED, Event, EventKind
from .ledger import Tokens
from .providers import Billing
from .salvage import STOP_REASONS, Cause

TURNS = "turns.jsonl"
HEARTBEAT = "heartbeat.json"
HEARTBEAT_VERSION = 1
PER_MILLION = 1_000_000
# $/Mtok: input, output, cache read, cache write.
RATES: dict[str, tuple[float, float, float, float]] = {
    "opus": (5, 25, 0.5, 6.25),
    "sonnet": (3, 15, 0.3, 3.75),
    "haiku": (1, 5, 0.1, 1.25),
}
FAMILIES = tuple(RATES)


class Beat(StrEnum):
    """Whether the runner is still beating."""

    BEATING = "beating"
    ENDED = "ended"


def family(model: str) -> str:
    """``opus``, ``sonnet`` or ``haiku`` when the name has one, else the name itself."""
    lowered = model.lower()
    return next((name for name in FAMILIES if name in lowered), model)


def estimate(model: str, tokens: Tokens) -> float | None:
    """Dollars for ``tokens`` at the model family's rates; ``None`` for an unknown family."""
    rates = RATES.get(family(model))
    if rates is None:
        return None
    counts = (tokens.input, tokens.output, tokens.cache_read, tokens.cache_creation)
    return sum(rate * count for rate, count in zip(rates, counts, strict=True)) / PER_MILLION


def read_heartbeat(run_dir: Path) -> dict[str, Any] | None:
    """The heartbeat file as parsed; ``None`` when missing, torn or not an object."""
    try:
        data = json.loads((run_dir / HEARTBEAT).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


@dataclass(frozen=True)
class Who:
    """What a meter measures."""

    role: str
    story: str | None
    step: str | None
    configured_model: str
    billing: Billing


@dataclass(frozen=True)
class Stop:
    """Why a step was cut short: the cause and the run's halt reason, if any."""

    cause: Cause
    halt: str | None = None


def interrupted_data(stop: Stop) -> dict[str, Any]:
    """The ``step-end`` data of a step cut short (I3)."""
    return {
        "status": INTERRUPTED,
        "reason": STOP_REASONS[stop.cause],
        "cause": str(stop.cause),
        "halt": stop.halt,
    }


@dataclass(frozen=True)
class Turn:
    """One line of turns.jsonl (T4)."""

    at: float
    role: str
    story: str | None
    step: str | None
    turn: int
    model: str
    tokens: Tokens
    tools: list[str]
    cost_usd: float | None
    message_id: str | None

    def line(self) -> str:
        """The JSON line, keys in field order."""
        return json.dumps(asdict(self))


def _excess(now: Tokens, counted: Tokens) -> Tokens:
    return Tokens(*(max(0, a - b) for a, b in zip(_counts(now), _counts(counted), strict=True)))


def _counts(tokens: Tokens) -> tuple[int, int, int, int]:
    return (tokens.input, tokens.output, tokens.cache_read, tokens.cache_creation)


@dataclass(eq=False)
class Reading:
    """The counts of one open query (pure: no I/O)."""

    who: Who
    started_at: float
    turns: int = 0
    tokens: Tokens = field(default_factory=Tokens)
    cost_usd: float | None = 0.0
    model: str | None = None
    last_turn_at: float | None = None
    tools: dict[str, tuple[str, float]] = field(default_factory=dict)
    counted: dict[str, Tokens] = field(default_factory=dict)

    def take(self, message: Any, now: float) -> Turn | None:
        """Fold in one message (T1-T6); a turn line when it started a turn or added news."""
        if isinstance(message, UserMessage):
            self._close_tools(message)
        elif isinstance(message, AssistantMessage):
            return self._answer(message, now)
        return None

    def _close_tools(self, message: UserMessage) -> None:
        blocks = message.content if isinstance(message.content, list) else []
        for block in blocks:
            if isinstance(block, ToolResultBlock):
                self.tools.pop(block.tool_use_id, None)

    def _answer(self, message: AssistantMessage, now: float) -> Turn | None:
        mid = message.message_id
        fresh = mid is None or mid not in self.counted
        extra = _excess(Tokens.from_usage(message.usage), self.counted.get(mid, Tokens()))
        uses = [b for b in message.content if isinstance(b, ToolUseBlock)]
        self.model = message.model
        if not (fresh or extra.total() or uses):
            return None
        self.turns += 1 if fresh else 0
        if mid is not None:
            self.counted[mid] = self.counted.get(mid, Tokens()) + extra
        for use in uses:
            self.tools.setdefault(use.id, (use.name, now))
        return self._line(message, extra, now)

    def _line(self, message: AssistantMessage, extra: Tokens, now: float) -> Turn:
        self.tokens += extra
        self.last_turn_at = now
        cost = self._price(message.model, extra)
        self.cost_usd = None if cost is None or self.cost_usd is None else self.cost_usd + cost
        tools = [b.name for b in message.content if isinstance(b, ToolUseBlock)]
        who = self.who
        return Turn(
            now, who.role, who.story, who.step, self.turns, message.model,
            extra, tools, cost, message.message_id,
        )  # fmt: skip

    def _price(self, model: str, tokens: Tokens) -> float | None:
        return 0.0 if self.who.billing is Billing.FREE else estimate(model, tokens)

    def tool(self) -> dict[str, Any] | None:
        """The open tool that started first (T5), or ``None``."""
        if not self.tools:
            return None
        name, started = min(self.tools.values(), key=lambda pair: pair[1])
        return {"name": name, "started_at": started}

    def view(self) -> dict[str, Any]:
        """The heartbeat's ``step`` object (H1)."""
        who = self.who
        return {
            "role": who.role,
            "story": who.story,
            "step": who.step,
            "started_at": self.started_at,
            "turn": self.turns,
            "model": self.model,
            "configured_model": who.configured_model,
            "last_turn_at": self.last_turn_at,
            "tool": self.tool(),
            "tokens": asdict(self.tokens),
            "cost_usd": self.cost_usd,
        }

    def interrupted(self, stop: Stop) -> Event:
        """The ``step-end`` event for this step cut short (I3)."""
        data = {
            **interrupted_data(stop),
            "turns": self.turns,
            "tokens": asdict(self.tokens),
            "estimate_usd": self.cost_usd,
            "model": self.model,
        }
        return Event(EventKind.STEP_END, self.who.role, self.who.story, data)


@dataclass(frozen=True)
class Pace:
    """Clock and wait, injectable so tests never sleep (H6); ``wait`` returns True to stop."""

    now: Callable[[], float] = time.time
    wait: Callable[[threading.Event, float], bool] = threading.Event.wait


@dataclass(frozen=True, eq=False)
class Meter:
    """A handle on one open reading in its pulse; what ``collect`` feeds."""

    pulse: Pulse
    reading: Reading

    def take(self, message: Any) -> None:
        """Feed one SDK message."""
        self.pulse.take(self, message)


@dataclass(eq=False)
class Pulse:
    """The heartbeat writer and the stack of open readings (H1-H6)."""

    run_dir: Path
    beat_s: float = 20.0
    pace: Pace = field(default_factory=Pace)
    pid: int = field(default_factory=os.getpid)
    started_at: float = field(init=False)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)
    _open: list[Meter] = field(init=False, default_factory=list)
    _chore: dict[str, Any] | None = field(init=False, default=None)
    _ended: bool = field(init=False, default=False)
    _stop: threading.Event = field(init=False, default_factory=threading.Event)
    _thread: threading.Thread | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.started_at = self.pace.now()

    def open(self, who: Who) -> Meter:
        """Start measuring a query; the newest open meter is the one shown."""
        meter = Meter(self, Reading(who, self.pace.now()))
        with self._lock:
            self._open.append(meter)
        self.write()
        return meter

    def close(self, meter: Meter) -> None:
        """Stop measuring ``meter``, wherever it is in the stack."""
        with self._lock:
            self._open = [m for m in self._open if m is not meter]
        self.write()

    def take(self, meter: Meter, message: Any) -> None:
        """Feed ``message`` to ``meter``; log a turn line and beat when there is news."""
        with self._lock:
            before = len(meter.reading.tools)
            turn = meter.reading.take(message, self.pace.now())
            self._log(turn)
            news = turn is not None or len(meter.reading.tools) < before
        if news:
            self.write()

    def _log(self, turn: Turn | None) -> None:
        if turn is None:
            return
        try:
            with (self.run_dir / TURNS).open("a") as out:
                out.write(turn.line() + "\n")
        except OSError:
            pass  # a lost turn line must never stop the run

    @contextmanager
    def doing(self, what: str) -> Iterator[None]:
        """Mark runner-side work in progress (H5); restores the previous chore on exit."""
        with self._lock:
            previous, self._chore = self._chore, {"what": what, "since": self.pace.now()}
        self.write()
        try:
            yield
        finally:
            with self._lock:
                self._chore = previous
            self.write()

    def start(self) -> None:
        """Write at once and keep beating from a daemon thread (D2)."""
        self.write()
        self._thread = threading.Thread(target=self.beats, daemon=True)
        self._thread.start()

    def end(self) -> None:
        """Stop the thread and write ``ended`` (H3)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        with self._lock:
            self._ended = True
        self.write()

    def beats(self) -> None:
        """The thread body: write every ``beat_s`` until told to stop."""
        while not self.pace.wait(self._stop, self.beat_s):
            self.write()

    def write(self) -> None:
        """Write the heartbeat atomically; a failed write is retried by the next beat (H4)."""
        with self._lock:
            data = self.heartbeat()
            try:
                tmp = self.run_dir / (HEARTBEAT + ".tmp")
                tmp.write_text(json.dumps(data))
                os.replace(tmp, self.run_dir / HEARTBEAT)
            except OSError:
                pass  # the next beat retries; a heartbeat must never crash the runner

    def heartbeat(self) -> dict[str, Any]:
        """The H1 dict as of now; call with the lock held."""
        live = not self._ended
        step = self._open[-1].reading.view() if live and self._open else None
        return {
            "version": HEARTBEAT_VERSION,
            "pid": self.pid,
            "beat": str(Beat.BEATING if live else Beat.ENDED),
            "at": self.pace.now(),
            "started_at": self.started_at,
            "chore": self._chore if live else None,
            "step": step,
        }
