"""Tokens per minute over time, kept small enough to ride on an event (s118 R3)."""

from __future__ import annotations

from dataclasses import dataclass, field

RATE_POINTS = 24


def squeeze(values: list[float], cap: int) -> list[float]:
    """Return ``values`` unchanged within ``cap``, else ``cap`` chunk means."""
    n = len(values)
    if n <= cap:
        return values
    chunks = (values[i * n // cap : (i + 1) * n // cap] for i in range(cap))
    return [sum(chunk) / len(chunk) for chunk in chunks]


@dataclass
class Rate:
    """Tokens bucketed by the minute since ``start``."""

    start: float
    minutes: dict[int, int] = field(default_factory=dict)

    def add(self, at: float, tokens: int) -> None:
        """Count ``tokens`` in the minute of ``at`` (before ``start`` is minute 0)."""
        minute = max(0, int((at - self.start) // 60))
        self.minutes[minute] = self.minutes.get(minute, 0) + tokens

    def series(self) -> list[float]:
        """Tokens per minute from minute 0 to the last one, squeezed to RATE_POINTS."""
        if not self.minutes:
            return []
        every = [float(self.minutes.get(m, 0)) for m in range(max(self.minutes) + 1)]
        return [round(v, 1) for v in squeeze(every, RATE_POINTS)]
