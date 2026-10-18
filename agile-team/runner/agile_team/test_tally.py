"""Live test counts folded from the pytest tally plugin's records (s118 R5)."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any

COUNTS = ("passed", "warned", "skipped", "failed")


@dataclass(frozen=True)
class Tally:
    """One pytest session's counts, the percentage points seen and where the first failure came."""

    session: str = ""
    passed: int = 0
    warned: int = 0
    skipped: int = 0
    failed: int = 0
    total: int | None = None
    points: tuple[int, ...] = ()
    fail_at: int | None = None

    def ran(self) -> int:
        """Tests reported so far (each is in exactly one count)."""
        return self.passed + self.warned + self.skipped + self.failed

    def counted(self) -> bool:
        """True once any test has reported."""
        return self.ran() > 0

    def pct(self) -> int | None:
        """Reports received over the collected total, in whole percent; None without a total."""
        if self.total is None or self.total <= 0:
            return None
        return min(100, round(100 * self.ran() / self.total))

    def as_dict(self) -> dict[str, Any]:
        """The heartbeat form."""
        return {
            "passed": self.passed,
            "warned": self.warned,
            "skipped": self.skipped,
            "failed": self.failed,
            "total": self.total,
            "points": list(self.points),
            "fail_at": self.fail_at,
        }


EMPTY = Tally()


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_total(value: object) -> bool:
    return value is None or (_is_count(value) and value > 0)


def _is_record(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    session = data.get("session")
    counts = all(_is_count(data.get(key)) for key in COUNTS)
    return isinstance(session, str) and bool(session) and counts and _is_total(data.get("total"))


def record_of(text: str) -> dict[str, Any] | None:
    """The JSON object in ``text`` when it is a plugin record, else None."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if _is_record(data) else None


def _with_point(tally: Tally) -> Tally:
    pct = tally.pct()
    if pct is None or (tally.points and tally.points[-1] == pct):
        return tally
    return replace(tally, points=(*tally.points, pct))


def _with_fail_at(tally: Tally) -> Tally:
    if tally.fail_at is not None or tally.failed == 0 or not tally.points:
        return tally
    return replace(tally, fail_at=len(tally.points) - 1)


def read(tally: Tally, text: str) -> Tally:
    """Fold one record into ``tally``; anything else changes nothing."""
    record = record_of(text)
    if record is None:
        return tally
    fresh = Tally(session=record["session"])
    base = tally if record["session"] == tally.session else fresh
    counts = {key: record[key] for key in (*COUNTS, "total")}
    return _with_fail_at(_with_point(replace(base, **counts)))
