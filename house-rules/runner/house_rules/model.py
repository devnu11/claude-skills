"""The data every check produces: levels, limits, findings and suppressions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Level(StrEnum):
    """How much a finding matters: a warning never fails a check."""

    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class Limits:
    """Two thresholds: a value above ``warn`` warns, above ``fail`` fails."""

    warn: int
    fail: int

    def classify(self, value: int) -> Level | None:
        """The level ``value`` reaches, or ``None`` when it is within both limits."""
        if value > self.fail:
            return Level.FAIL
        return Level.WARN if value > self.warn else None


@dataclass(frozen=True)
class Finding:
    """One rule broken by one symbol of one file."""

    rule: str
    level: Level
    path: str
    line: int
    symbol: str
    value: int
    limit: int
    message: str

    @property
    def key(self) -> str:
        """The baseline key: stable across line moves, new on a rename."""
        return f"{self.path}::{self.symbol}::{self.rule}"


@dataclass(frozen=True)
class Suppression:
    """A comment that allows rules on one line, with the reason given."""

    path: str
    line: int
    rules: frozenset[str]
    reason: str
