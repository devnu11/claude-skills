"""Runner health for the live meter (s44): the RULES table over the heartbeat and run status."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from . import live, system
from . import state as state_mod
from .config import Config, HealthLimits
from .state import RunStatus

SECONDS_PER_MIN = 60
MINUTES_PER_HOUR = 60
SECONDS_SHOWN_UNDER = 90
MINUTES_SHOWN_UNDER = 90


class Level(StrEnum):
    """How worried the dashboard is."""

    IDLE = "idle"
    GREEN = "green"
    AMBER = "amber"
    RED = "red"


RANK: dict[Level, int] = {level: i for i, level in enumerate(Level)}


class Runner(StrEnum):
    """Whether the process named in the heartbeat exists."""

    UP = "up"
    GONE = "gone"


HALTED = frozenset(
    {RunStatus.BLOCKED, RunStatus.FAILED, RunStatus.STOPPED, RunStatus.CHECKOUT_CHANGED}
)


def age(seconds: float) -> str:
    """``8 s``, ``11 min`` or ``1 h 30 min`` (R12)."""
    if seconds < SECONDS_SHOWN_UNDER:
        return f"{int(seconds)} s"
    minutes = int(seconds // SECONDS_PER_MIN)
    if minutes < MINUTES_SHOWN_UNDER:
        return f"{minutes} min"
    return f"{minutes // MINUTES_PER_HOUR} h {minutes % MINUTES_PER_HOUR} min"


def model_note(step: dict[str, Any] | None) -> str | None:
    """Say so when the answering model is not the configured one (R14)."""
    configured, answering = (step or {}).get("configured_model"), (step or {}).get("model")
    if not configured or not answering:
        return None
    if live.family(configured) == live.family(answering):
        return None
    return f"configured {live.family(configured)}, answering {live.family(answering)}"


@dataclass(frozen=True)
class Clock:
    """The reader's wall and monotonic time; ``mono`` is ``None`` when unknown (s78)."""

    wall: float
    mono: float | None = None

    @classmethod
    def read(cls) -> Clock:
        """Both clocks now, through the system seam."""
        return cls(system.now(), system.monotonic())


@dataclass(frozen=True)
class Vitals:
    """Everything the rules look at (R0)."""

    now: float
    status: RunStatus
    reason: str | None
    beat: dict[str, Any] | None
    runner: Runner
    limits: HealthLimits
    halt_kind: str | None = None
    mono: float | None = None

    @classmethod
    def read(cls, config: Config, clock: Clock) -> Vitals:
        """Read the run's state and heartbeat from disk."""
        state = state_mod.load(config.run_dir)
        status = state_mod.shown_status(config.run_dir, state)
        beat = live.read_heartbeat(config.run_dir)
        return cls(
            clock.wall,
            status,
            state.status_reason,
            beat,
            _runner(beat),
            config.health,
            state.halt_kind,
            clock.mono,
        )

    @property
    def resting(self) -> bool:
        """A graceful stop: the human asked for it (R15)."""
        return self.status is RunStatus.STOPPED and self.halt_kind is None

    @property
    def beating(self) -> bool:
        return (
            self.beat is not None
            and self.beat.get("beat") == live.Beat.BEATING
            and not self.resting
        )

    @property
    def pid(self) -> int | None:
        return (self.beat or {}).get("pid")

    @property
    def beat_age(self) -> float:
        return self.now - (self.beat or {}).get("at", self.now)

    @property
    def slept(self) -> float | None:
        """Wall seconds since the last beat that monotonic time did not see (R16)."""
        mono = (self.beat or {}).get("mono")
        if self.mono is None or isinstance(mono, bool) or not isinstance(mono, int | float):
            return None
        return self.beat_age - (self.mono - mono)

    def slept_over(self, limit: float) -> bool:
        """Whether the machine slept for more than ``limit`` seconds."""
        slept = self.slept
        return slept is not None and slept > limit

    @property
    def stale(self) -> bool:
        """Beating, but the last beat is older than ``stale_s``."""
        return self.beating and self.beat_age > self.limits.stale_s

    @property
    def busy(self) -> bool:
        """Work was declared: a tool is open or a chore is set."""
        return self.tool is not None or self.chore is not None

    @property
    def excused(self) -> bool:
        """A late beat that work and an awake machine explain (R17)."""
        awake = self.slept is not None and not self.slept_over(self.limits.stale_s)
        return self.busy and awake and self.beat_age <= self.limits.red_quiet_s

    @property
    def step(self) -> dict[str, Any] | None:
        return (self.beat or {}).get("step") if self.beating else None

    @property
    def chore(self) -> dict[str, Any] | None:
        return (self.beat or {}).get("chore") if self.beating else None

    @property
    def tool(self) -> dict[str, Any] | None:
        return (self.step or {}).get("tool")

    @property
    def last_turn_at(self) -> float | None:
        return (self.step or {}).get("last_turn_at")

    @property
    def quiet_for(self) -> float | None:
        """Seconds since the step's last turn (or start); ``None`` with no step or a chore."""
        if self.step is None or self.chore is not None:
            return None
        step = self.step
        return self.now - step.get("quiet_since", self.last_turn_at or step["started_at"])

    @property
    def halted(self) -> bool:
        return self.status in HALTED and not self.resting

    def quiet_over(self, limit: float) -> bool:
        """Whether the step has been quiet for more than ``limit`` seconds."""
        quiet = self.quiet_for
        return quiet is not None and quiet > limit

    def turns_arriving(self) -> bool:
        """Whether a step's last turn is within ``stale_s``."""
        last = self.last_turn_at
        return last is not None and self.now - last <= self.limits.stale_s


def _runner(beat: dict[str, Any] | None) -> Runner:
    pid = (beat or {}).get("pid")
    if not isinstance(pid, int) or state_mod.pid_alive(pid):
        return Runner.UP
    return Runner.GONE


@dataclass(frozen=True)
class Rule:
    """A level, when it applies, and what to say."""

    level: Level
    test: Callable[[Vitals], bool]
    words: Callable[[Vitals], str]


def _status_words(v: Vitals) -> str:
    return v.reason or str(v.status)


def _not_running(v: Vitals) -> str:
    return f"the runner is not running (pid {v.pid})" if v.pid else "the runner is not running"


def _quiet_words(v: Vitals) -> str:
    return f"no turn for {age(v.quiet_for or 0)}"


def _tool_words(v: Vitals) -> str:
    return f"{_quiet_words(v)} while {(v.tool or {}).get('name')} runs"


def _chore_words(v: Vitals) -> str:
    chore = v.chore or {}
    return f"runner: {chore.get('what')} for {age(v.now - chore.get('since', v.now))}"


def _sleep_words(v: Vitals) -> str:
    return f"the machine slept for {age(v.slept or 0)}"


def _doing(v: Vitals) -> str:
    return _chore_words(v) if v.chore else f"{(v.tool or {}).get('name')} runs"


def _late_words(v: Vitals) -> str:
    return f"heartbeat {age(v.beat_age)} old while {_doing(v)}"


RULES: tuple[Rule, ...] = (
    Rule(Level.RED, lambda v: v.halted, lambda v: f"halted: {_status_words(v)}"),
    Rule(
        Level.RED,
        lambda v: v.halted and v.turns_arriving(),
        lambda v: f"turns arriving while the run is {v.status}",
    ),
    Rule(
        Level.RED,
        lambda v: v.status is RunStatus.INTERRUPTED or (v.beating and v.runner is Runner.GONE),
        _not_running,
    ),
    Rule(
        Level.RED,
        lambda v: v.quiet_over(v.limits.red_quiet_s),
        _quiet_words,
    ),
    Rule(Level.RED, lambda v: v.beating and v.slept_over(v.limits.stale_s), _sleep_words),
    Rule(
        Level.RED,
        lambda v: v.stale and not v.excused and not v.slept_over(v.limits.stale_s),
        lambda v: f"heartbeat {age(v.beat_age)} old",
    ),
    Rule(Level.AMBER, lambda v: v.stale and v.excused, _late_words),
    Rule(Level.AMBER, lambda v: bool(v.tool) and v.quiet_over(v.limits.amber_tool_s), _tool_words),
    Rule(
        Level.AMBER,
        lambda v: not v.tool and v.quiet_over(v.limits.amber_quiet_s),
        _quiet_words,
    ),
    Rule(Level.GREEN, lambda v: v.chore is not None, _chore_words),
    Rule(Level.GREEN, lambda v: v.step is not None and v.chore is None, lambda v: "turns arriving"),
    Rule(Level.IDLE, lambda v: True, _status_words),
)


@dataclass(frozen=True)
class Health:
    """The verdict: a level, its reason in words and a model note."""

    level: Level
    reason: str
    model_note: str | None = None

    def key(self) -> str:
        """``level|reason``, to tell when the verdict changed."""
        return f"{self.level}|{self.reason}"


def judge(vitals: Vitals) -> Health:
    """The worst level among the rules that apply, with the words of those at that level (R1)."""
    hits = [rule for rule in RULES if rule.test(vitals)]
    worst = max((rule.level for rule in hits), key=RANK.__getitem__)
    words = ", ".join(rule.words(vitals) for rule in hits if rule.level is worst)
    return Health(worst, words, model_note(vitals.step))


def check_steps(vitals: Vitals) -> Health:
    """I5: judge each open step of the heartbeat's ``steps`` and report the worst verdict."""
    beat = vitals.beat or {}
    steps = [s for s in beat.get("steps") or [] if isinstance(s, dict)]
    views = [replace(vitals, beat={**beat, "step": s}) for s in steps] or [vitals]
    return max((judge(v) for v in views), key=lambda h: RANK[h.level])


def current(config: Config) -> Health:
    """The verdict for the run as it is now."""
    return check_steps(Vitals.read(config, Clock.read()))
