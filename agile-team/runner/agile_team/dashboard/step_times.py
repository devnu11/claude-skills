"""Awake time of agent steps, paired from the event log (s96, s97)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from typing import Any

from ..events import EventKind
from ..salvage import Cause

Key = tuple[str | None, str | None]


class Clock(StrEnum):
    """Which clock timed a step (AW7)."""

    AWAKE = "awake"
    WALL = "wall"


class Platform(StrEnum):
    """Which awake-time rule applies (AW4)."""

    POSIX = "posix"
    WINDOWS = "windows"


PLATFORMS: dict[str, Platform] = {"win32": Platform.WINDOWS}


def platform_of(name: str) -> Platform:
    """``PLATFORMS[name]``, else POSIX (AW4)."""
    return PLATFORMS.get(name, Platform.POSIX)


def number(value: Any) -> float | None:
    """``value`` as a clock reading, or None when missing, a bool or not a number (AW3)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value


@dataclass(frozen=True)
class Mark:
    """One clock reading: wall ``at``, monotonic ``mono``, the heartbeat's ``slept`` counter."""

    at: float
    mono: float | None = None
    slept: float | None = None

    @classmethod
    def of(cls, event: dict) -> Mark:
        """The reading an event carries (``at``, ``data.mono``, ``data.slept``)."""
        data = event.get("data") or {}
        return cls(event["at"], number(data.get("mono")), number(data.get("slept")))


EPOCH = Mark(0.0)  # a module constant, not a call in a default (ruff B008/RUF009)


def gap(first: float | None, last: float | None) -> float | None:
    """``last - first``, or None when either is missing or the counter went back."""
    if first is None or last is None or last < first:
        return None
    return last - first


def mono_awake(start: Mark, end: Mark) -> float | None:
    """AW5: the monotonic span (the clock pauses in sleep on macOS and Linux)."""
    return gap(start.mono, end.mono)


def slept_awake(start: Mark, end: Mark) -> float | None:
    """AW6: the wall span less the sleep the heartbeat counted (Windows)."""
    slept = gap(start.slept, end.slept)
    return None if slept is None else (end.at - start.at) - slept


AWAKE: dict[Platform, Callable[[Mark, Mark], float | None]] = {
    Platform.POSIX: mono_awake,
    Platform.WINDOWS: slept_awake,
}


@dataclass(frozen=True)
class Timing:
    """A step's ``seconds``, ``clock`` and ``slept``; all None for an untimed step."""

    seconds: float | None = None
    clock: Clock | None = None
    slept: float | None = None


UNTIMED = Timing()


def wall_timing(wall: float) -> Timing:
    """The fallback: wall seconds, ``clock`` WALL, nothing left out (AW7)."""
    return Timing(round(max(0, wall), 1), Clock.WALL, 0.0)


def awake_timing(wall: float, awake: float) -> Timing:
    """Awake seconds, ``clock`` AWAKE, ``slept = wall - awake`` (AW7)."""
    return Timing(round(max(0, awake), 1), Clock.AWAKE, round(max(0, wall - awake), 1))


@dataclass(frozen=True)
class Stopwatch:
    """The reader's platform and its reading now; the default times every step by wall clock."""

    platform: Platform = Platform.POSIX
    now: Mark = EPOCH

    def between(self, start: Mark, end: Mark) -> Timing:
        """AW7 over the platform's ``AWAKE`` rule."""
        wall = end.at - start.at
        awake = AWAKE[self.platform](start, end)
        return wall_timing(wall) if awake is None else awake_timing(wall, awake)

    def so_far(self, start: Mark) -> Timing:
        """AW9: ``between(start, self.now)``."""
        return self.between(start, self.now)


def killed(end: dict) -> bool:
    """Whether recovery closed the step (``data.cause == "killed"``, ST4)."""
    return (end.get("data") or {}).get("cause") == Cause.KILLED


@dataclass(frozen=True)
class Span:
    """One agent step: start time, and end, status and awake time once it ends."""

    role: str
    story: str | None
    at: float
    sprint: int | None = None
    ended_at: float | None = None
    status: str | None = None
    model: str | None = None
    seconds: float | None = None
    clock: str | None = None
    slept: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """The snapshot's object for this step."""
        return asdict(self)


@dataclass
class Pairing:
    """One walk over the log: the steps found, the open ones by key, the running sprint."""

    watch: Stopwatch = field(default_factory=Stopwatch)
    found: list[Span | None] = field(default_factory=list)
    open: dict[Key, int] = field(default_factory=dict)
    starts: dict[int, Mark] = field(default_factory=dict)
    sprint: int | None = None

    def start(self, event: dict) -> None:
        """ST1/ST2: open the key, dropping an earlier open start of the same key."""
        key = (event.get("role"), event.get("story"))
        if key in self.open:
            self.found[self.open[key]] = None
        self.open[key] = len(self.found)
        self.starts[len(self.found)] = Mark.of(event)
        self.found.append(Span(key[0], key[1], event["at"], self.sprint))  # type: ignore[arg-type]

    def end(self, event: dict) -> None:
        """ST1/ST3/ST4: close the key's open step; ignore an end with none open."""
        index = self.open.pop((event.get("role"), event.get("story")), None)
        if index is not None:
            self.found[index] = self._closed(index, event)

    def _closed(self, index: int, end: dict) -> Span:
        """ended_at, status and model from ``end``, timed by ``_timing`` (AW7, AW8)."""
        data = end.get("data") or {}
        timing = self._timing(index, end)
        return replace(
            self.found[index],  # type: ignore[type-var]
            ended_at=end["at"],
            status=data.get("status"),
            model=data.get("model"),
            seconds=timing.seconds,
            clock=timing.clock,
            slept=timing.slept,
        )

    def _timing(self, index: int, end: dict) -> Timing:
        """UNTIMED for a killed end, else ``watch.between`` its start and end."""
        if killed(end):
            return UNTIMED
        return self.watch.between(self.starts[index], Mark.of(end))

    def _running(self, index: int) -> Span:
        """An open step with ``clock`` and ``slept`` so far; ``seconds`` stays None (AW9)."""
        timing = self.watch.so_far(self.starts[index])
        return replace(self.found[index], clock=timing.clock, slept=timing.slept)  # type: ignore[type-var]

    def result(self) -> list[Span]:
        """Every step in start order, open ones through ``_running``."""
        running = set(self.open.values())
        return [
            self._running(i) if i in running else s
            for i, s in enumerate(self.found)
            if s is not None
        ]

    def sprint_start(self, event: dict) -> None:
        """ST6: remember ``data.sprint``."""
        self.sprint = (event.get("data") or {}).get("sprint")


FEEDS: dict[str, Callable[[Pairing, dict], None]] = {
    EventKind.STEP_START: Pairing.start,
    EventKind.STEP_END: Pairing.end,
    EventKind.SPRINT_START: Pairing.sprint_start,
}

WALL_CLOCK = Stopwatch()  # times every step without `mono` by wall clock; the s96 default


def spans(events: list[dict], watch: Stopwatch = WALL_CLOCK) -> list[Span]:
    """Every agent step in start order; open ones are running (ST1 to ST6, AW7 to AW9)."""
    pairing = Pairing(watch)
    for event in events:
        feed = FEEDS.get(event.get("kind"))  # type: ignore[arg-type]
        if feed:
            feed(pairing, event)
    return pairing.result()
