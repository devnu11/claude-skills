"""Tokens per minute over time, kept small enough to ride on an event (s118 R3)."""

from __future__ import annotations

from dataclasses import dataclass, field

RATE_POINTS = 24
WINDOW_S = 10
PER_MINUTE = 60 // WINDOW_S  # a window's tokens times this is tokens per minute


def squeeze(values: list[float], cap: int) -> list[float]:
    """Return ``values`` unchanged within ``cap``, else ``cap`` chunk means."""
    n = len(values)
    if n <= cap:
        return values
    chunks = (values[i * n // cap : (i + 1) * n // cap] for i in range(cap))
    return [sum(chunk) / len(chunk) for chunk in chunks]


@dataclass
class Rate:
    """Tokens bucketed by 10-second window since ``start``, read as tokens per minute (s127 RT1)."""

    start: float
    windows: dict[int, int] = field(default_factory=dict)

    def add(self, at: float, tokens: int) -> None:
        """Count ``tokens`` in the window of ``at`` (before ``start`` is window 0)."""
        window = max(0, int((at - self.start) // WINDOW_S))
        self.windows[window] = self.windows.get(window, 0) + tokens

    def series(self) -> list[float]:
        """Tokens per minute for each window from 0 to the last, squeezed to RATE_POINTS."""
        if not self.windows:
            return []
        every = [float(PER_MINUTE * self.windows.get(w, 0)) for w in range(max(self.windows) + 1)]
        return [round(v, 1) for v in squeeze(every, RATE_POINTS)]
