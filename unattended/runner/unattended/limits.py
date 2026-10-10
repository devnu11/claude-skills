"""Usage limits: how a run ended, when the limit resets, and the bounds that end a job.

The limit patterns and the reset parser are copied from agile-team's ``halt.py``
and the dogfood ``reset_epoch.py``, not imported: skills stay standalone.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

GRACE = timedelta(minutes=3)
DEFAULT_FALLBACK = 5 * 3600.0
DEFAULT_MAX_RESUMES = 10
BACKOFF_START = 60.0
BACKOFF_CAP = 30 * 60.0
REASON_LIMIT = 200


class OutcomeKind(StrEnum):
    """How one run of a job ended."""

    DONE = "done"
    LIMIT = "limit"
    RATE_LIMITED = "rate-limited"
    BUDGET = "budget"
    OFFLINE = "offline"
    FAILED = "failed"


@dataclass(frozen=True)
class Metrics:
    """What one run cost; command jobs report nothing."""

    cost: float = 0.0
    turns: int = 0
    tokens: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Outcome:
    """One run's result: its kind, a short reason and what it cost."""

    kind: OutcomeKind
    reason: str = ""
    metrics: Metrics = field(default_factory=Metrics)


Patterns = tuple[tuple[re.Pattern[str], str], ...]


def _pattern(regex: str) -> re.Pattern[str]:
    return re.compile(regex, re.IGNORECASE)


LIMIT_PATTERNS: Patterns = (
    (_pattern(r"hit your (?P<kind>[\w ]+?) limit\W+resets (?P<reset>[^\n;]*[^\s;])"),
     "{kind} limit, resets {reset}"),
    (_pattern(r"hit your (?P<kind>[\w ]+?) limit"), "{kind} limit"),
    (_pattern(r"(?P<kind>usage) limit reached"), "{kind} limit reached"),
)  # fmt: skip
RESET_NOTE: Patterns = (
    (_pattern(r"resets (?P<reset>[^\n;]*[^\s;])"), "usage limit, resets {reset}"),
)
RATE_PATTERNS: Patterns = (
    (_pattern(r"(?:API Error|HTTP|status)\W*(?P<code>429|529)\b"), "rate limited (HTTP {code})"),
    (_pattern(r"rate.?limit"), "rate limited"),
    (_pattern(r"overloaded"), "API overloaded"),
)
NETWORK_PATTERNS: Patterns = (
    (_pattern(r"can.t reach the API server"), "API server unreachable"),
    (_pattern(r"\b(?P<code>ENOTFOUND|EAI_AGAIN|ECONNREFUSED|ECONNRESET|ETIMEDOUT|ENETUNREACH)\b"),
     "network error ({code})"),
    (_pattern(r"connection error"), "connection error"),
)  # fmt: skip
CLASSES: tuple[tuple[OutcomeKind, Patterns], ...] = (
    (OutcomeKind.LIMIT, LIMIT_PATTERNS),
    (OutcomeKind.RATE_LIMITED, RATE_PATTERNS),
    (OutcomeKind.OFFLINE, NETWORK_PATTERNS),
)
EXIT_SUFFIX = re.compile(r"\s*\(exit code: -?\d+\)\s*$", re.MULTILINE)


def strip_exit_suffix(text: str) -> str:
    """``text`` without the SDK's ``(exit code: N)`` line endings."""
    return EXIT_SUFFIX.sub("", text)


def find_reason(patterns: Patterns, text: str) -> str | None:
    """The first pattern's template, filled from its last match in ``text``."""
    for pattern, template in patterns:
        matches = list(pattern.finditer(text))
        if matches:
            return template.format(**matches[-1].groupdict()).strip()
    return None


def classify(text: str) -> Outcome:
    """The outcome ``text`` names (limit, rate limit or offline), else ``FAILED``."""
    for kind, patterns in CLASSES:
        reason = find_reason(patterns, text)
        if reason:
            return Outcome(kind, reason)
    lines = text.strip().splitlines()
    return Outcome(OutcomeKind.FAILED, lines[0][:REASON_LIMIT] if lines else "failed")


# ----- reset times -------------------------------------------------------------

RESET_TIME = _pattern(
    r"resets\s+(?:(?P<month>[a-z]{3})[a-z]*\.?\s+(?P<day>\d{1,2}),?\s+(?:at\s+)?)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d\d))?\s*(?P<half>[ap]m)"
    r"(?:\s*\((?P<zone>[\w/+-]+)\))?"
)
MONTH_NAMES = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
MONTHS = {name: number for number, name in enumerate(MONTH_NAMES, 1)}


def local(epoch: float) -> datetime:
    """``epoch`` as an aware datetime in the local zone."""
    return datetime.fromtimestamp(epoch).astimezone()


def reset_at(text: str, now: datetime) -> datetime | None:
    """The next reset time stated in ``text`` after ``now``, or None when there is none."""
    matches = list(RESET_TIME.finditer(text))
    if not matches:
        return None
    match = matches[-1]
    here = now.astimezone(_zone(match["zone"], now.tzinfo))
    at = _candidate(match, here)
    return at if at is None or at > here else _roll(at, match)


def _zone(name: str | None, default: tzinfo | None) -> tzinfo | None:
    try:
        return ZoneInfo(name) if name else default
    except (ZoneInfoNotFoundError, ValueError):
        return default


def _candidate(match: re.Match[str], here: datetime) -> datetime | None:
    """The stated time on the stated date, or today when no date is given."""
    month = MONTHS.get((match["month"] or "").lower())
    if match["month"] and month is None:
        return None
    try:
        return _time_on(match, here.replace(month=month, day=int(match["day"])) if month else here)
    except ValueError:
        return None


def _roll(at: datetime, match: re.Match[str]) -> datetime:
    """The next occurrence: tomorrow for a bare time, next year for a dated one."""
    return at.replace(year=at.year + 1) if match["month"] else at + timedelta(days=1)


@dataclass(frozen=True)
class Waits:
    """How long to wait after a limit when its reset time cannot be read."""

    fallback: float = DEFAULT_FALLBACK

    def after_limit(self, reason: str, now: float) -> float:
        """Epoch seconds to wake: the stated reset plus ``GRACE``, else the fallback."""
        at = reset_at(reason, local(now))
        return (at + GRACE).timestamp() if at else now + self.fallback


def backoff(retries: int) -> float:
    """Seconds to wait before rate-limit retry ``retries`` (0-based): 1, 2, 4… min, cap 30."""
    return min(BACKOFF_START * 2**retries, BACKOFF_CAP)


# ----- deadlines ---------------------------------------------------------------

DURATION = re.compile(r"(?:\s*\d+(?:\.\d+)?\s*[smhd])+\s*", re.IGNORECASE)
DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)\s*([smhd])", re.IGNORECASE)
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
CLOCK_TIME = _pattern(r"(?:(?P<day>today|tomorrow)\s+)?(?P<hour>\d{1,2})(?::(?P<minute>\d\d))?"
                      r"\s*(?P<half>[ap]m)?")  # fmt: skip
DAY_OFFSETS = {"today": 0, "tomorrow": 1}


def parse_duration(text: str) -> float:
    """Seconds in a duration such as ``24h``, ``90m`` or ``1h30m``."""
    if not DURATION.fullmatch(text):
        raise ValueError(f"cannot read duration {text!r} (try 24h, 90m or 1h30m)")
    return sum(float(n) * UNIT_SECONDS[u.lower()] for n, u in DURATION_PART.findall(text))


def parse_until(text: str, now: datetime) -> datetime:
    """A deadline from ISO (``2026-10-10T09:00``), ``21:00``, ``9pm`` or ``tomorrow 9am``."""
    try:
        at = datetime.fromisoformat(text)
    except ValueError:
        return _clock_time(text, now)
    return at if at.tzinfo else at.replace(tzinfo=now.tzinfo)


def _clock_time(text: str, now: datetime) -> datetime:
    match = CLOCK_TIME.fullmatch(text.strip())
    try:
        at = _time_on(match, now) if match else None
    except ValueError:
        at = None
    if at is None:
        raise ValueError(f"cannot read time {text!r} (try 21:00, 9pm, tomorrow 9am or ISO)")
    if match["day"]:
        return at + timedelta(days=DAY_OFFSETS[match["day"].lower()])
    return at if at > now else at + timedelta(days=1)


def _time_on(match: re.Match[str], day: datetime) -> datetime:
    """``day`` at the matched hour and minute; ValueError when they are out of range."""
    return day.replace(hour=_hour(match), minute=int(match["minute"] or 0), second=0, microsecond=0)


def _hour(match: re.Match[str]) -> int:
    """The 24-hour hour; ``12am`` is midnight and no am/pm means a 24-hour clock."""
    hour = int(match["hour"])
    return {"am": hour % 12, "pm": hour % 12 + 12}.get((match["half"] or "").lower(), hour)


# ----- bounds ------------------------------------------------------------------


@dataclass(frozen=True)
class Progress:
    """Where a job stands when deciding whether to wait and resume."""

    resumes: int
    cost: float
    next_wake: float


@dataclass
class Bounds:
    """The limits that end a job: deadline (epoch seconds), resumes and total cost."""

    deadline: float | None = None
    max_resumes: int = DEFAULT_MAX_RESUMES
    max_cost: float | None = None

    def budget_left(self, spent: float) -> float | None:
        """USD the next run may spend, or None without a cost cap."""
        return None if self.max_cost is None else max(self.max_cost - spent, 0.0)

    def stop_reason(self, progress: Progress) -> str | None:
        """Why the job must not resume, or None when it may."""
        return next((r for check in CHECKS if (r := check(self, progress))), None)


def _deadline(bounds: Bounds, progress: Progress) -> str | None:
    if bounds.deadline is None or progress.next_wake < bounds.deadline:
        return None
    wake, end = (local(t).strftime("%Y-%m-%d %H:%M") for t in (progress.next_wake, bounds.deadline))
    return f"deadline {end} comes before the next wake at {wake}"


def _resumes(bounds: Bounds, progress: Progress) -> str | None:
    if progress.resumes < bounds.max_resumes:
        return None
    return f"used all {bounds.max_resumes} resumes"


def _cost(bounds: Bounds, progress: Progress) -> str | None:
    if bounds.max_cost is None or progress.cost < bounds.max_cost:
        return None
    return f"cost ${progress.cost:.2f} reached the ${bounds.max_cost:.2f} cap"


CHECKS: tuple[Callable[[Bounds, Progress], str | None], ...] = (_deadline, _resumes, _cost)
