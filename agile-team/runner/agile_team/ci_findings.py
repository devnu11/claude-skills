"""The lines of a failed CI step's log that name what failed (s172), as a table of tiers."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Finder:
    """One kind of finding line: the pattern that spots it and how it is shown."""

    pattern: re.Pattern[str]
    shown: str = "{line}"  # str.format over the match's named groups, {line}, {previous}


@dataclass(frozen=True)
class Tier:
    """Finders that belong together; the first tier with a hit is the one shown."""

    name: str
    finders: tuple[Finder, ...]


TEST_TIER = Tier(
    "tests",
    (
        Finder(re.compile(r"\bFAILED\s+\S")),
        Finder(re.compile(r"\bERROR\s+\S+::")),
        Finder(re.compile(r"--- FAIL: ")),
        Finder(re.compile(r"(?<!Found )\b[1-9]\d* (?:failed|errors?)\b")),
    ),
)
LINT_TIER = Tier(
    "findings",
    (
        Finder(
            re.compile(
                r"^::error file=(?P<file>[^,]+),line=(?P<line_no>\d+)[^:]*::(?P<message>.+)$"
            ),
            "{file}:{line_no}: {message}",
        ),
        Finder(
            re.compile(r"^##\[error\](?!Process completed with exit code)(?P<message>.+)$"),
            "{message}",
        ),
        Finder(re.compile(r"^-->\s*(?P<at>\S+?:\d+(?::\d+)?)$"), "{at}: {previous}"),
        Finder(re.compile(r"^[^\s:]+:\d+(?::\d+)?: (?!warn)\S")),
        Finder(re.compile(r"^Would reformat: \S")),
    ),
)
TIERS: tuple[Tier, ...] = (TEST_TIER, LINT_TIER)


def render_hit(tier: Tier, pair: tuple[str, str]) -> str | None:
    """``pair`` is ``(previous, line)``: the line as the tier's first matching finder shows it."""
    previous, line = pair
    for finder in tier.finders:
        found = finder.pattern.search(line)
        if found:
            return finder.shown.format(**found.groupdict(), line=line, previous=previous)
    return None


def find_tier_lines(tier: Tier, lines: list[str]) -> list[str]:
    """Every line the tier shows, in log order (``previous`` of the first line is "")."""
    shown = (render_hit(tier, pair) for pair in zip(["", *lines], lines, strict=False))
    return [text for text in shown if text is not None]


def pick_lines(lines: list[str]) -> list[str]:
    """The shown lines of the first tier with a hit; ``[]`` when no tier hits."""
    hits = (find_tier_lines(tier, lines) for tier in TIERS)
    return next((found for found in hits if found), [])
