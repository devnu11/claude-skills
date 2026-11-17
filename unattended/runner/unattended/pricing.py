"""Price a run's tokens while it runs, from the published API rates.

The SDK reports ``total_cost_usd`` only in the result message that ends a run.
Each assistant message carries ``usage`` (tokens by kind) and ``model``, so a
run's spend so far can be *estimated* from them. Rates are USD per million
tokens from https://platform.claude.com/docs/en/about-claude/pricing (read
2026-11-17); a model not in the table gives no estimate rather than a wrong one.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

MILLION = 1_000_000
# Claude Code model ids: ``claude-opus-5-5``, ``claude-opus-4-5-20251101``; the table
# key drops the ``claude-`` prefix and any date suffix.
MODEL_KEY = re.compile(r"^(?:claude-)?(?P<key>[a-z]+(?:-\d+)+?)(?:-\d{8})?$")


@dataclass(frozen=True)
class Rate:
    """USD per million tokens of each kind."""

    input: float
    output: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float


# Haiku 5.5 is priced for prompts up to 100k tokens; longer prompts cost 5x.
RATES: dict[str, Rate] = {
    "fable-5-2": Rate(8, 40, 10, 16, 0.20),
    "mythos-5-2": Rate(8, 40, 10, 16, 0.20),
    "fable-5-1": Rate(10, 50, 12.5, 20, 0.25),
    "mythos-5-1": Rate(10, 50, 12.5, 20, 0.25),
    "fable-5": Rate(10, 50, 12.5, 20, 1),
    "mythos-5": Rate(10, 50, 12.5, 20, 1),
    "opus-5-5": Rate(4, 20, 5, 8, 0.20),
    "opus-5": Rate(5, 25, 6.25, 10, 0.50),
    "opus-4-8": Rate(5, 25, 6.25, 10, 0.50),
    "opus-4-7": Rate(5, 25, 6.25, 10, 0.50),
    "opus-4-6": Rate(5, 25, 6.25, 10, 0.50),
    "opus-4-5": Rate(5, 25, 6.25, 10, 0.50),
    "opus-4-1": Rate(15, 75, 18.75, 30, 1.50),
    "opus-4": Rate(15, 75, 18.75, 30, 1.50),
    "sonnet-5-5": Rate(2, 10, 2.5, 4, 0.10),
    "sonnet-5": Rate(2, 10, 2.5, 4, 0.20),
    "sonnet-4-6": Rate(3, 15, 3.75, 6, 0.30),
    "sonnet-4-5": Rate(3, 15, 3.75, 6, 0.30),
    "sonnet-4": Rate(3, 15, 3.75, 6, 0.30),
    "haiku-5-5": Rate(0.10, 0.50, 0.125, 0.20, 0.01),
    "haiku-4-5": Rate(1, 5, 1.25, 2, 0.10),
}


@dataclass(frozen=True)
class Usage:
    """Tokens of each kind, summed over messages."""

    input: int = 0
    output: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    cache_read: int = 0

    @classmethod
    def from_sdk(cls, usage: dict[str, Any]) -> Usage:
        """The SDK's ``usage`` dict; its ``cache_creation`` split, when given, wins."""
        writes = _split_cache_writes(usage)
        return cls(
            input=usage.get("input_tokens", 0),
            output=usage.get("output_tokens", 0),
            cache_write_5m=writes[0],
            cache_write_1h=writes[1],
            cache_read=usage.get("cache_read_input_tokens", 0),
        )

    def __add__(self, other: Usage) -> Usage:
        mine, theirs = asdict(self), asdict(other)
        return Usage(**{key: mine[key] + theirs[key] for key in mine})

    def compute_cost(self, rate: Rate) -> float:
        """USD at ``rate``."""
        tokens, prices = asdict(self), asdict(rate)
        return sum(tokens[key] * prices[key] for key in tokens) / MILLION


def _split_cache_writes(usage: dict[str, Any]) -> tuple[int, int]:
    """(5-minute, 1-hour) cache write tokens; an unsplit total counts as 5-minute."""
    split = usage.get("cache_creation") or {}
    if split:
        return split.get("ephemeral_5m_input_tokens", 0), split.get("ephemeral_1h_input_tokens", 0)
    return usage.get("cache_creation_input_tokens", 0), 0


def find_rate(model: str) -> Rate | None:
    """The published rate of ``model``, or None when it is not in the table."""
    match = MODEL_KEY.match(model)
    return RATES.get(match["key"]) if match else None


@dataclass(frozen=True)
class Estimate:
    """What a set of per-model usages would cost: priced where a rate is known."""

    usd: float | None
    unpriced: list[str]

    @classmethod
    def compute(cls, by_model: dict[str, Usage]) -> Estimate:
        """None for ``usd`` when any model has no rate; the sum of the rest otherwise."""
        unpriced = sorted(model for model in by_model if find_rate(model) is None)
        if unpriced:
            return cls(None, unpriced)
        return cls(sum(_measure_cost(model, usage) for model, usage in by_model.items()), [])


def _measure_cost(model: str, usage: Usage) -> float:
    """USD of ``usage`` on ``model``, whose rate is known."""
    rate = find_rate(model)
    assert rate is not None  # callers check first
    return usage.compute_cost(rate)
