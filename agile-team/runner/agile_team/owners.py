"""Who owns a failing file (s92): pure tables and functions, no I/O.

A gate's output becomes *items* (a failing test, a lint finding). Each item is
placed in the repo and given to the pipeline role whose write globs match its
file. Items owned by another role become queued gate fix steps.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from . import paths


class Source(StrEnum):
    """Which gate command printed an item."""

    TEST = "test"
    LINT = "lint"


ITEM_LINES = 40

FINDINGS: dict[Source, tuple[re.Pattern[str], ...]] = {
    Source.TEST: (
        # pytest short summary (default -rfE): FAILED/ERROR path[::test] [- msg]
        re.compile(r"^(?:FAILED|ERROR) (?P<path>[^\s:]+\.\w+)(?:::\S+)?(?: - .*)?$", re.M),
        # jest: FAIL path
        re.compile(r"^\s*FAIL (?P<path>\S+\.\w+)\s*$", re.M),
    ),
    Source.LINT: (
        # ruff concise, flake8, mypy, eslint unix: path:line[:col]: message
        re.compile(r"^(?P<path>[^\s:]+\.\w+):\d+(?::\d+)?: (?!warn(?:ing)?\b).*$", re.M | re.I),
        # ruff full (default since 0.9): "CODE message" then " --> path:line:col"
        re.compile(r"^\S.*\n\s*--> (?P<path>[^\s:]+\.\w+):\d+:\d+\s*$", re.M),
        # ruff format --check
        re.compile(r"^Would reformat: (?P<path>\S+)\s*$", re.M),
    ),
}

FIXED_AT: dict[tuple[Source, str], str] = {(Source.TEST, "tests"): "implement"}

ASSERTION_MARKS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*assert\b"),
    re.compile(r"\bpytest\.raises\("),
    re.compile(r"\bexpect\("),
    re.compile(r"\bassert\w*!?\("),
)

FIX_NOTES: dict[tuple[bool, bool], str] = {
    (True, True): "changed what a test asserts because {asserts}",
    (True, False): "named {asserts}, but no assertion line changed",
    (False, True): "assertion lines changed, but no rule was named; check them",
    (False, False): "no assertion change",
}


@dataclass(frozen=True)
class Finding:
    """One match in a command's output: printed path and its matched lines."""

    path: str
    lines: tuple[str, ...]
    source: Source


@dataclass
class Item:
    """One failing item placed in the repo."""

    path: str
    source: Source
    files: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    @property
    def shown(self) -> str:
        """The one tracked file when known, else the printed path."""
        return self.files[0] if len(self.files) == 1 else self.path


@dataclass
class Fix:
    """One queued gate fix step."""

    role: str
    items: list[Item]
    rule: str = ""
    why: str = ""


@dataclass
class FixRecord:
    """One settled fix step, kept for the reviewer."""

    role: str
    files: list[str]
    commit: str | None
    asserts: str = ""
    changed: bool = False


@dataclass(frozen=True)
class Writer:
    """One row of the owners table."""

    step: str
    role: str
    write: tuple[str, ...]


@dataclass
class Split:
    """Items kept by the step's own role, and the fixes for other roles."""

    own: list[Item]
    fixes: list[Fix]

    @property
    def tested(self) -> bool:
        """True when any item, own or routed, is a test."""
        items = [*self.own, *(i for f in self.fixes for i in f.items)]
        return any(i.source == Source.TEST for i in items)


@dataclass(frozen=True)
class Owners:
    """The owners table for one story at one step."""

    writers: tuple[Writer, ...]
    step: str
    touched: frozenset[str] = frozenset()

    @property
    def own(self) -> Writer | None:
        """The writer for the gated step."""
        return next((w for w in self.writers if w.step == self.step), None)

    def writer_of(self, file: str) -> Writer | None:
        """The step's own writer if it matches the file, else the first that does."""
        ordered = sorted(self.writers, key=lambda w: w != self.own)
        return next((w for w in ordered if paths.matches(file, list(w.write))), None)

    def owner_of(self, files: list[str]) -> Writer | None:
        """The one writer shared by every file, else ``None``."""
        owners = {self.writer_of(f) for f in files}
        return owners.pop() if len(owners) == 1 else None

    def fixer(self, item: Item) -> Writer | None:
        """The other role who must fix the item, or ``None`` when it is the step's own."""
        owner = self.owner_of(item.files)
        if owner is None or owner.step == self.step:
            return None
        return None if FIXED_AT.get((item.source, owner.step)) == self.step else owner

    def counts(self, item: Item) -> bool:
        """Tests always count; lint only in files the story touched."""
        return item.source == Source.TEST or any(f in self.touched for f in item.files)


def findings(output: str, source: Source) -> list[Finding]:
    """Every ``FINDINGS[source]`` match in ``output``."""
    found = (m for rx in FINDINGS[source] for m in rx.finditer(output))
    return [Finding(m["path"], tuple(m.group(0).splitlines()), source) for m in found]


def candidates(path: str, listing: str) -> list[str]:
    """``[path]`` if tracked, else every tracked path ending in ``/path``."""
    tracked = listing.splitlines()
    return [path] if path in tracked else [t for t in tracked if t.endswith("/" + path)]


def placed(found: list[Finding], listing: str) -> list[Item]:
    """Group findings by (path, source) in first-seen order and place them."""
    items: dict[tuple[str, Source], Item] = {}
    for f in found:
        item = items.setdefault(
            (f.path, f.source), Item(f.path, f.source, candidates(f.path, listing))
        )
        item.lines.extend(f.lines)
    for item in items.values():
        item.lines = item.lines[:ITEM_LINES]
    return list(items.values())


def split(items: list[Item], owners: Owners) -> Split:
    """Own items (lint dropped) and one fix per other role, in writer order."""
    kept = [i for i in items if owners.counts(i)]
    by_writer: dict[Writer, list[Item]] = {}
    own: list[Item] = []
    for item in kept:
        writer = owners.fixer(item)
        if writer is not None:
            by_writer.setdefault(writer, []).append(item)
        elif item.source == Source.TEST:
            own.append(item)
    order = sorted(by_writer, key=owners.writers.index)
    return Split(own, [Fix(w.role, by_writer[w]) for w in order])


def fix_lines(fix: Fix) -> list[str]:
    """The brief lines for one fix: its items, then the cited rule."""
    lines = ["Items:"]
    for item in fix.items:
        lines.append(f"- {item.shown} ({item.source})")
        lines.extend(f"    {line}" for line in item.lines)
    if fix.rule:
        why = f": {fix.why}" if fix.why else ""
        lines.append(f"Design rule the failing step cited: {fix.rule}{why}")
    return lines


def _marked(diff: str, sign: str) -> list[str]:
    lines = (
        ln[1:] for ln in diff.splitlines() if ln.startswith(sign) and not ln.startswith(sign * 3)
    )
    return [ln for ln in lines if any(rx.search(ln) for rx in ASSERTION_MARKS)]


def _assertions(diff: str, sign: str) -> Counter[str]:
    return Counter("".join(ln.split()) for ln in _marked(diff, sign))


def asserts_changed(diff: str) -> bool:
    """True when removed and added assertion lines differ, ignoring whitespace."""
    return _assertions(diff, "-") != _assertions(diff, "+")


def fix_note(record: FixRecord) -> str:
    """The reviewer's note for one settled fix."""
    return FIX_NOTES[(bool(record.asserts), record.changed)].format(asserts=record.asserts)


def load_fix(data: dict[str, Any]) -> Fix:
    """Rebuild a ``Fix`` from ``state.json``."""
    items = [Item(**{**d, "source": Source(d["source"])}) for d in data["items"]]
    return Fix(data["role"], items, data.get("rule", ""), data.get("why", ""))
