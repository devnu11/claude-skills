"""The live meter (s44): turns from a query's stream, the heartbeat file, open steps and chores."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from claude_agent_sdk import AssistantMessage, ToolResultBlock, ToolUseBlock, UserMessage

from . import halt, rates, system, tool_calls
from .dashboard.step_times import Mark, Platform, platform_of
from .events import EVENTS, INTERRUPTED, Event, EventKind
from .ledger import Tokens
from .providers import Billing
from .salvage import STOP_REASONS, Cause

TURNS = "turns.jsonl"
HEARTBEAT = "heartbeat.json"
HEARTBEAT_VERSION = 2
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
    return (
        sum(rate * count for rate, count in zip(rates, _counts(tokens), strict=True)) / PER_MILLION
    )


def read_heartbeat(run_dir: Path) -> dict[str, Any] | None:
    """The heartbeat file as parsed; ``None`` when missing, torn or not an object."""
    try:
        data = json.loads(system.read_text(run_dir / HEARTBEAT))
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

    @classmethod
    def from_line(cls, text: str) -> Turn:
        """Parse one turns.jsonl line; raises ValueError, TypeError or KeyError on a bad one."""
        data = json.loads(text)
        return cls(**{**data, "tokens": Tokens(**data["tokens"])})

    def line(self) -> str:
        """The JSON line, keys in field order."""
        return json.dumps(asdict(self))


def _blocks(content: Any, kind: type) -> list[Any]:
    return [b for b in content if isinstance(b, kind)] if isinstance(content, list) else []


def _excess(now: Tokens, counted: Tokens) -> Tokens:
    return Tokens(*(max(0, a - b) for a, b in zip(_counts(now), _counts(counted), strict=True)))


def _counts(tokens: Tokens) -> tuple[int, int, int, int]:
    return (tokens.input, tokens.output, tokens.cache_read, tokens.cache_creation)


@dataclass(frozen=True)
class News:
    """What one answer adds: new tokens, its tool uses and the time (C3)."""

    extra: Tokens
    uses: list[ToolUseBlock]
    now: float


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
    platform: Platform = Platform.POSIX
    start: Mark | None = None
    end: Mark | None = None
    quiet_since: float = field(init=False)
    calls: tool_calls.Calls = field(init=False)
    rate: rates.Rate = field(init=False)

    def __post_init__(self) -> None:
        self.quiet_since = self.started_at
        self.rate = rates.Rate(self.started_at)
        self.start = self.start or Mark(self.started_at)
        self.calls = tool_calls.Calls(self.where(), self.platform)

    def where(self) -> tool_calls.Where:
        """Which step or PO turn this reading's spans belong to (TC5)."""
        who = self.who
        step = who.step or tool_calls.STEP_OF_ROLE.get(who.role)
        return tool_calls.Where(who.role, who.story, step, self.started_at)

    def close(self, mark: Mark) -> None:
        """End the reading at ``mark``; open calls end unfinished (TC3)."""
        self.end = mark
        self.calls.abandon(mark)

    def time_split(self) -> dict[str, Any]:
        """``opened_at``, the time split and the token rate (TC12, s118)."""
        split = self.calls.split(self.start or Mark(self.started_at), self.end or self.start)  # type: ignore[arg-type]
        return {"opened_at": self.started_at, **split.as_dict(), "rate": self.rate.series()}

    def wake(self, now: float) -> None:
        """Control is back with the model: the quiet clock restarts (H7)."""
        self.quiet_since = now

    def take(self, message: Any, now: float) -> Turn | None:
        """Fold in one message (T1-T6); a turn line when it started a turn or added news."""
        return self.take_at(message, Mark(now))

    def take_at(self, message: Any, mark: Mark) -> Turn | None:
        """``take`` with the full clock reading, which times the tool calls."""
        if isinstance(message, UserMessage):
            self._close_tools(message, mark.at)
            self.calls.finish(_blocks(message.content, ToolResultBlock), mark)
        elif isinstance(message, AssistantMessage):
            self.calls.start(_blocks(message.content, ToolUseBlock), mark)
            return self._answer(message, mark.at)
        return None

    def _close_tools(self, message: UserMessage, now: float) -> None:
        blocks = message.content if isinstance(message.content, list) else []
        for block in blocks:
            if isinstance(block, ToolResultBlock) and self.tools.pop(block.tool_use_id, None):
                self.wake(now)

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
        return self._line(message, News(extra, uses, now))

    def _line(self, message: AssistantMessage, news: News) -> Turn:
        extra, now = news.extra, news.now
        self.tokens += extra
        self.last_turn_at = now
        self.rate.add(now, extra.total())
        self.wake(now)
        cost = self._price(message.model, extra)
        self.cost_usd = None if cost is None or self.cost_usd is None else self.cost_usd + cost
        tools = [u.name for u in news.uses]
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
            "quiet_since": self.quiet_since,
            "tool": self.tool(),
            "tokens": asdict(self.tokens),
            "cost_usd": self.cost_usd,
            "rate": self.rate.series(),
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


@dataclass(frozen=True, eq=False)
class Meter:
    """A handle on one open reading in its pulse; what ``collect`` feeds."""

    pulse: Pulse
    reading: Reading

    def take(self, message: Any) -> None:
        """Feed one SDK message."""
        self.pulse.take(self, message)

    def interrupted(self, stop: Stop) -> Event:
        """The reading's ``interrupted`` step-end with this pulse's ``clocks()`` added (AW1)."""
        event = self.reading.interrupted(stop)
        event.data.update(self.time_split(), **self.pulse.clocks())
        return event

    def time_split(self) -> dict[str, Any]:
        """The reading's ``opened_at``, time split and token rate (s118)."""
        return self.reading.time_split()


def time_split(meter: Meter | None) -> dict[str, Any]:
    """``meter``'s split and rate for a step event; ``{}`` without a meter."""
    return {} if meter is None else meter.time_split()


SLEEP_GAP_BEATS = 2  # a beat gap over this many beats is sleep (AW2)
SLEEPS = "sleeps.jsonl"


@dataclass(frozen=True)
class Sleep:
    """One sleep the heartbeat counted (TL19): the beat gap and the seconds left out."""

    start: float
    end: float
    slept: float

    def line(self) -> str:
        """``{"from", "to", "slept"}`` as one JSON line, each rounded to 1 decimal."""
        keys = {"from": self.start, "to": self.end, "slept": self.slept}
        return json.dumps({k: round(v, 1) for k, v in keys.items()})


@dataclass(eq=False)
class Pulse:
    """The heartbeat writer and the stack of open readings (H1-H6)."""

    run_dir: Path
    beat_s: float = 20.0
    started_at: float = field(init=False)
    platform: Platform = field(init=False)
    slept_s: float = field(init=False, default=0.0)
    _last_beat: float = field(init=False)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)
    _open: list[Meter] = field(init=False, default_factory=list)
    _chore: dict[str, Any] | None = field(init=False, default=None)
    _stages: list[dict[str, Any]] = field(init=False, default_factory=list)
    _ended: bool = field(init=False, default=False)
    _reported: bool = field(init=False, default=False)
    _stop: threading.Event = field(init=False, default_factory=threading.Event)
    _thread: threading.Thread | None = field(init=False, default=None)
    _waiting: str | None = field(init=False, default=None)
    unattended: Path | None = None

    def __post_init__(self) -> None:
        self.started_at = self._last_beat = system.now()
        self.platform = platform_of(system.platform())

    def mark(self) -> Mark:
        """The clocks now, as a ``Mark``."""
        return Mark(system.now(), system.monotonic(), round(self.slept_s, 1))

    def open(self, who: Who) -> Meter:
        """Start measuring a query; the newest open meter is the one shown."""
        mark = self.mark()
        meter = Meter(self, Reading(who, mark.at, platform=self.platform, start=mark))
        with self._lock:
            self._open.append(meter)
        self.write()
        return meter

    def close(self, meter: Meter) -> None:
        """Stop measuring ``meter``, wherever it is in the stack."""
        mark = self.mark()
        with self._lock:
            meter.reading.close(mark)
            self._log_spans(meter.reading.calls.take_fresh())
            self._open = [m for m in self._open if m is not meter]
            self._wake_innermost()
        self.write()

    def _wake_innermost(self) -> None:
        if self._open:
            self._open[-1].reading.wake(system.now())

    def take(self, meter: Meter, message: Any) -> None:
        """Feed ``message`` to ``meter``; log a turn line and beat when there is news."""
        with self._lock:
            before = len(meter.reading.tools)
            turn = meter.reading.take_at(message, self.mark())
            self._log(turn)
            self._log_spans(meter.reading.calls.take_fresh())
            news = turn is not None or len(meter.reading.tools) < before
        if news:
            self.write()

    def _log(self, turn: Turn | None) -> None:
        if turn is None:
            return
        with suppress(OSError):  # a lost turn line must never stop the run
            system.append_text(self.run_dir / TURNS, turn.line() + "\n")

    def _log_spans(self, spans: list[tool_calls.ToolSpan]) -> None:
        if not spans:
            return
        with suppress(OSError):  # a lost span line must never stop the run
            system.append_text(
                self.run_dir / tool_calls.TOOLS, "".join(s.line() + "\n" for s in spans)
            )

    @contextmanager
    def doing(self, what: str) -> Iterator[None]:
        """Mark runner-side work in progress (H5); restores the previous chore on exit."""
        with self._lock:
            previous, self._chore = self._chore, {"what": what, "since": system.now()}
        self.write()
        try:
            yield
        finally:
            with self._lock:
                self._chore = previous
                self._wake_innermost()
            self.write()

    @contextmanager
    def showing(self, row: dict[str, Any]) -> Iterator[None]:
        """List an open stage row in the heartbeat for the block (HB1)."""
        with self._lock:
            self._stages.append(row)
        self.write()
        try:
            yield
        finally:
            with self._lock:
                self._stages = [r for r in self._stages if r is not row]
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
        """The thread body: beat every ``beat_s``; a failed beat never ends it (H7)."""
        while not system.wait_event(self._stop, self.beat_s):
            self._beat()

    def _beat(self) -> None:
        try:
            self._log_sleep(self._count_sleep(system.now()))
            self.write()
        except Exception as exc:
            self._report(exc)

    def _count_sleep(self, now: float) -> Sleep | None:
        """Add a beat gap over ``SLEEP_GAP_BEATS`` beats, less one beat, to ``slept_s`` (AW2)."""
        with self._lock:
            before, gap = self._last_beat, now - self._last_beat
            self._last_beat = now
            if gap <= SLEEP_GAP_BEATS * self.beat_s:
                return None
            self.slept_s += gap - self.beat_s
            return Sleep(before, now, gap - self.beat_s)

    def _log_sleep(self, sleep: Sleep | None) -> None:
        if sleep is None:
            return
        with suppress(OSError):  # a lost sleep line must never stop the run
            system.append_text(self.run_dir / SLEEPS, sleep.line() + "\n")

    def clocks(self) -> dict[str, float]:
        """``{"mono": …, "slept": …}`` for a step event (AW1)."""
        return {"mono": system.monotonic(), "slept": round(self.slept_s, 1)}

    def _report(self, exc: Exception) -> None:
        """Leave one traceback in crash.log for the first failed beat."""
        if self._reported:
            return
        self._reported = True
        with suppress(OSError):
            halt.log_traceback(self.run_dir, exc)

    def refresh(self) -> None:
        """Write the heartbeat again now (s118 R7)."""
        self.write()

    def set_waiting(self, reason: str | None) -> None:
        """I5: say what the idle scheduler waits for; ``None`` when it waits for nothing."""
        with self._lock:
            changed, self._waiting = self._waiting != reason, reason
        if changed:
            self.write()

    def write(self) -> None:
        """Write the heartbeat atomically; a failed write is retried by the next beat (H4)."""
        with self._lock:
            data = self.heartbeat()
            try:
                tmp = self.run_dir / (HEARTBEAT + ".tmp")
                system.write_text(tmp, json.dumps(data))
                system.replace(tmp, self.run_dir / HEARTBEAT)
            except OSError:
                pass  # the next beat retries; a heartbeat must never crash the runner
            self._write_unattended()

    def _write_unattended(self) -> None:
        """I5: the file the unattended tool watches: ``at``, ``progress`` and ``waiting``."""
        if self.unattended is None:
            return
        with suppress(OSError):
            events = self.run_dir / EVENTS
            size = system.stat(events).size if system.exists(events) else 0
            data = {"at": system.now(), "progress": size}
            extra = {"waiting": self._waiting} if self._waiting else {}
            system.write_text(self.unattended, json.dumps(data | extra))

    def _open_calls(self) -> list[dict]:
        """Every open call of every open meter, the outer meter first (N11)."""
        return [row for m in self._open for row in m.reading.calls.opened()]

    def heartbeat(self) -> dict[str, Any]:
        """The H1 dict as of now; call with the lock held."""
        live = not self._ended
        step = self._open[-1].reading.view() if live and self._open else None
        steps = [m.reading.view() for m in self._open] if live else []
        return {
            "version": HEARTBEAT_VERSION,
            "pid": system.pid(),
            "beat": str(Beat.BEATING if live else Beat.ENDED),
            "at": system.now(),
            "mono": system.monotonic(),
            "started_at": self.started_at,
            "slept": round(self.slept_s, 1),
            "chore": self._chore if live else None,
            "step": step,
            "calls": self._open_calls() if live else [],
            "stages": list(self._stages) if live else [],
            "steps": steps,
        }
