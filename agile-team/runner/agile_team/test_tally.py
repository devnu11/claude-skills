"""Live pass/warn/fail counts read from pytest's progress lines (s118 R5)."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

OUTCOMES = {
    ".": "passed",
    "F": "failed",
    "E": "failed",
    "s": "warned",
    "x": "warned",
    "X": "warned",
}
TOTALS = (
    re.compile(r"\bcollected (\d+) items?\b"),
    re.compile(r"\b\d+ workers? \[(\d+) items?\]"),
)
PROGRESS = re.compile(r"^(?:\S+ )?([.FEsxX]+)\s*\[\s*(\d{1,3})%\]\s*$")
MAX_POINTS = 120


@dataclass(frozen=True)
class Tally:
    """The counts so far, the percentage points seen and where the first failure came."""

    passed: int = 0
    warned: int = 0
    failed: int = 0
    total: int | None = None
    pct: int = 0
    points: tuple[int, ...] = ()
    fail_at: int | None = None

    def ran(self) -> int:
        """Tests reported so far."""
        return self.passed + self.warned + self.failed

    def counted(self) -> bool:
        """True once any test has reported."""
        return self.ran() > 0

    def as_dict(self) -> dict[str, Any]:
        """The heartbeat form; the total is estimated from the percentage when unknown."""
        return {
            "passed": self.passed,
            "warned": self.warned,
            "failed": self.failed,
            "total": self._total(),
            "points": list(self.points),
            "fail_at": self.fail_at,
        }

    def _total(self) -> int | None:
        if self.total is not None:
            return self.total
        return round(self.ran() * 100 / self.pct) if self.pct > 0 else None


EMPTY = Tally()


def _total_of(line: str) -> int | None:
    found = (m for m in (p.search(line) for p in TOTALS) if m)
    match = next(found, None)
    return int(match.group(1)) if match else None


def _points(tally: Tally, pct: int) -> tuple[int, ...]:
    held = tally.points if len(tally.points) < MAX_POINTS else tally.points[:-1]
    return (*held, pct)


def _progress(tally: Tally, chars: str, pct: int) -> Tally:
    counts = {"passed": 0, "warned": 0, "failed": 0}
    for char in chars:
        counts[OUTCOMES[char]] += 1
    first_fail = tally.fail_at is None and counts["failed"] > 0
    points = _points(tally, pct)
    return replace(
        tally,
        passed=tally.passed + counts["passed"],
        warned=tally.warned + counts["warned"],
        failed=tally.failed + counts["failed"],
        pct=pct,
        points=points,
        fail_at=len(points) - 1 if first_fail else tally.fail_at,
    )


def read(tally: Tally, line: str) -> Tally:
    """Fold one output line into ``tally``; any other line changes nothing."""
    total = _total_of(line)
    if total is not None:
        return replace(tally, total=total)
    match = PROGRESS.match(line.strip())
    return _progress(tally, match.group(1), int(match.group(2))) if match else tally
