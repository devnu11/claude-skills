"""The one place tests read the real clock (s129, ADR-0066).

e2e tests that talk to a real process use these; unit tests use the fake clock.
`about` compares durations with a tolerance; `page_clock` freezes the page's clock.
"""

from __future__ import annotations

import time

import pytest

DURATION_TOLERANCE_S = 0.01


def real_now() -> float:
    """Wall-clock seconds, for files a real process compares with its own clock."""
    return time.time()


def real_monotonic() -> float:
    """Monotonic seconds, for a real heartbeat's `mono` field."""
    return time.monotonic()


class Deadline:
    """A real-time limit for an e2e wait, on the monotonic clock."""

    def __init__(self, seconds: float) -> None:
        self._end = real_monotonic() + seconds

    def left(self) -> float:
        """Seconds until the end, never below 0.0."""
        return max(0.0, self._end - real_monotonic())

    def passed(self) -> bool:
        """True once the end has been reached."""
        return self.left() == 0.0


def about(seconds: float) -> object:
    """Match a duration within DURATION_TOLERANCE_S: `assert x == about(480)`."""
    return pytest.approx(seconds, abs=DURATION_TOLERANCE_S)


def page_clock(now: float) -> str:
    """JavaScript that freezes the page's `Date.now` at `now` seconds."""
    return f"Date.now = () => {now * 1000!r};\n"
