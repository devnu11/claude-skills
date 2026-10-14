"""The pending-tests registry and the pure rules that read it (s125).

A story's new failing tests are pending from its tests gate until its implement
gate passes them. Only the runner writes ``.team/pending-tests.json``.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import junit, system

REGISTRY = ".team/pending-tests.json"
WHOLE = range(1, sys.maxsize)
Changed = Mapping[str, tuple[range, ...]]
NEW_FILE = re.compile(r"^\+\+\+ b/(?P<path>.+)$")
HUNK = re.compile(r"^@@ -\S+ \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")
NOT_AN_OBJECT = "{file} must hold an object of story ids to lists of test ids"


class RegistryError(Exception):
    """Raised when the registry file is not a valid ``{story: [test id, ...]}``."""


@dataclass(frozen=True)
class PendingSet:
    """A story's new pending ids; ``()`` removes the story's entry."""

    story: str
    ids: tuple[str, ...]


@dataclass(frozen=True)
class Registry:
    """Pending test ids per story."""

    entries: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def of(self, story: str) -> tuple[str, ...]:
        """The story's pending ids."""
        return self.entries.get(story, ())

    def others(self, story: str) -> dict[str, tuple[str, ...]]:
        """Every other story's ids; story ``""`` gives all of them."""
        return {s: ids for s, ids in self.entries.items() if s != story}

    def with_ids(self, change: PendingSet) -> Registry:
        """A copy with the story's entry set, or dropped when ``change.ids`` is empty."""
        kept = {s: ids for s, ids in self.entries.items() if s != change.story}
        return Registry({**kept, change.story: change.ids} if change.ids else kept)

    def text(self) -> str:
        """The file text: sorted keys and ids, indented, ending in a newline."""
        data = {story: sorted(self.entries[story]) for story in sorted(self.entries)}
        return json.dumps(data, indent=2) + "\n"


def _valid(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    return all(isinstance(v, list) and all(isinstance(i, str) for i in v) for v in data.values())


def parse(text: str) -> Registry:
    """The registry in ``text``; ``RegistryError`` unless it is ``{str: [str, ...]}``."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RegistryError(str(exc)) from exc
    if not _valid(data):
        raise RegistryError(NOT_AN_OBJECT.format(file=REGISTRY))
    return Registry({story: tuple(ids) for story, ids in data.items()})


def read(repo: Path) -> Registry:
    """The repo's registry; empty when the file does not exist."""
    path = repo / REGISTRY
    return parse(system.read_text(path)) if system.is_file(path) else Registry()


def write(repo: Path, registry: Registry) -> None:
    """Write the registry file."""
    path = repo / REGISTRY
    system.make_dirs(path.parent)
    system.write_text(path, registry.text())


def _hunk_range(match: re.Match[str]) -> range:
    start, count = int(match["start"]), int(match["count"] or 1)
    return range(start, start + (count or 2))  # a pure deletion marks the line after it


def changed_lines(diff: str, untracked: Sequence[str]) -> Changed:
    """The new-side line ranges of each file in a ``git diff -U0``; untracked files count whole."""
    found: dict[str, list[range]] = {}
    path = ""
    for line in diff.splitlines():
        if named := NEW_FILE.match(line):
            path = named["path"]
        elif (hunk := HUNK.match(line)) and path:
            found.setdefault(path, []).append(_hunk_range(hunk))
    return {**{p: tuple(r) for p, r in found.items()}, **{p: (WHOLE,) for p in untracked}}


@dataclass(frozen=True)
class Touch:
    """What ``touched`` needs: the whole report and the step's changed lines."""

    report: junit.Report
    changed: Changed


def _next_line(case: junit.Case, report: junit.Report) -> int:
    lines = [c.line for c in report.cases if c.file == case.file and c.line is not None]
    return min((n for n in lines if n > (case.line or 0)), default=sys.maxsize)


def _overlaps(extent: range, ranges: tuple[range, ...]) -> bool:
    return any(r.start < extent.stop and extent.start < r.stop for r in ranges)


def touched(case: junit.Case, ctx: Touch) -> bool:
    """Whether the step changed the lines of the case, or its file for a file id."""
    ranges = ctx.changed.get(case.file, ())
    if case.line is None:
        return bool(ranges)
    return _overlaps(range(case.line, _next_line(case, ctx.report)), ranges)


@dataclass(frozen=True)
class RedAsk:
    """What ``split_red`` needs: the step's changed lines and the story's own ids."""

    changed: Changed
    own: tuple[str, ...]


@dataclass(frozen=True)
class RedSplit:
    """Failed ids split into pending ones and real failures."""

    pending: tuple[str, ...]
    real: tuple[str, ...]


def split_red(report: junit.Report, ctx: RedAsk) -> RedSplit:
    """Failed ids touched by the step, or already the story's own, are pending."""
    touch = Touch(report, ctx.changed)
    failed = report.failed()
    pending = tuple(c.id for c in failed if c.id in ctx.own or touched(c, touch))
    return RedSplit(pending, tuple(c.id for c in failed if c.id not in pending))


@dataclass(frozen=True)
class Leaving:
    """The story's own ids that did not pass, and those the report does not hold."""

    failing: tuple[str, ...]
    missing: tuple[str, ...]


def leaving(report: junit.Report, own: tuple[str, ...]) -> Leaving:
    """Which own ids still fail and which are gone from the suite."""
    failing = tuple(i for i in own if report.holds(i) and not report.passed(i))
    return Leaving(failing, tuple(i for i in own if not report.holds(i)))


def counts_text(skipped: Mapping[str, tuple[str, ...]], report: junit.Report) -> str:
    """``pending (s1): 3, ...``: skipped ids the report does not hold, per story."""
    counts = {s: sum(1 for i in ids if not report.holds(i)) for s, ids in sorted(skipped.items())}
    return ", ".join(f"pending ({s}): {n}" for s, n in counts.items() if n)
