"""Who owns a failing file: the pure table behind gate fix steps (s92).

A gate's output becomes *items* (a failing test, a lint finding). Each item's
file is matched against the write globs of the pipeline roles; items owned by
another role become ``Fix`` steps for that role. No I/O and no import of
``gates``.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from . import paths


class Source(StrEnum):
    """Which gate output an item came from."""

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
        re.compile(r"^(?P<path>[^\s:]+\.\w+):\d+(?::\d+)?: .*$", re.M),
        # ruff full (default since 0.9): "CODE message" then " --> path:line:col"
        re.compile(r"^\S.*\n\s*--> (?P<path>[^\s:]+\.\w+):\d+:\d+\s*$", re.M),
        # ruff format --check
        re.compile(r"^Would reformat: (?P<path>\S+)\s*$", re.M),
    ),
}

FIXED_AT: dict[tuple[Source, str], str] = {(Source.TEST, "tests"): "implement"}

ASSERTION_MARKS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*assert\b"),  # Python
    re.compile(r"\bpytest\.raises\("),
    re.compile(r"\bexpect\("),  # jest
    re.compile(r"\bassert\w*!?\("),  # Rust assert!/assert_eq!, Go/JUnit assertX(
)

FIX_NOTES: dict[tuple[bool, bool], str] = {  # (rule named, assertion lines changed)
    (True, True): "changed what a test asserts because {asserts}",
    (True, False): "named {asserts}, but no assertion line changed",
    (False, True): "assertion lines changed, but no rule was named; check them",
    (False, False): "no assertion change",
}
RULE_LINE = "Design rule the failing step cited: {rule}"


@dataclass(frozen=True)
class Finding:
    """One match in a gate's output: the printed path and its matched lines."""

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
        """The one tracked file, else the printed path."""
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
    """One settled fix step, for the reviewer."""

    role: str
    files: list[str]
    commit: str | None
    asserts: str = ""
    changed: bool = False


@dataclass(frozen=True)
class Writer:
    """One row of the owners table: a step, its role and the role's write globs."""

    step: str
    role: str
    write: tuple[str, ...]


@dataclass(frozen=True)
class Owners:
    """The owners table for one story at one step."""

    writers: tuple[Writer, ...]
    step: str
    touched: frozenset[str] = frozenset()

    @property
    def own(self) -> Writer | None:
        """The writer of the gated step."""
        return next((w for w in self.writers if w.step == self.step), None)

    def writer_of(self, file: str) -> Writer | None:
        """The step's own writer if its globs match, else the first writer that matches."""
        ordered = [w for w in (self.own, *self.writers) if w is not None]
        return next((w for w in ordered if paths.matches(file, list(w.write))), None)

    def owner_of(self, files: list[str]) -> Writer | None:
        """The one writer shared by all ``files``, else ``None``."""
        found = {self.writer_of(f) for f in files}
        return found.pop() if len(found) == 1 else None

    def fixer(self, item: Item) -> Writer | None:
        """The foreign writer who must fix ``item``; ``None`` when it stays with the step."""
        owner = self.owner_of(item.files)
        if owner is None or owner.step == self.step:
            return None
        return None if FIXED_AT.get((item.source, owner.step)) == self.step else owner

    def counts(self, item: Item) -> bool:
        """Tests always count; lint only in files the story touched (R7)."""
        return item.source is Source.TEST or any(f in self.touched for f in item.files)


@dataclass
class Split:
    """Items the step keeps and the fix steps for the rest."""

    own: list[Item]
    fixes: list[Fix]

    @property
    def tested(self) -> bool:
        """Whether any test item is in ``own`` or in a fix."""
        every = [*self.own, *(i for fix in self.fixes for i in fix.items)]
        return any(i.source is Source.TEST for i in every)


def findings(output: str, source: Source) -> list[Finding]:
    """Every ``FINDINGS[source]`` match in ``output``."""
    return [
        Finding(m["path"], tuple(m.group(0).strip().splitlines()), source)
        for pattern in FINDINGS[source]
        for m in pattern.finditer(output)
    ]


def candidates(path: str, listing: str) -> list[str]:
    """``[path]`` if listed, else every listed path ending ``/path``."""
    lines = listing.splitlines()
    if path in lines:
        return [path]
    return [x for x in lines if x.endswith("/" + path)]


def placed(found: list[Finding], listing: str) -> list[Item]:
    """Group findings by (path, source) in first-seen order and place them in the repo."""
    grouped: dict[tuple[str, Source], list[str]] = {}
    for f in found:
        grouped.setdefault((f.path, f.source), []).extend(f.lines)
    return [
        Item(path, source, candidates(path, listing), lines[:ITEM_LINES])
        for (path, source), lines in grouped.items()
    ]


def split(items: list[Item], owners: Owners) -> Split:
    """Own items (lint dropped) and one ``Fix`` per foreign role, in writer order."""
    counted = [i for i in items if owners.counts(i)]
    by_writer: dict[Writer, list[Item]] = {}
    own: list[Item] = []
    for i in counted:
        writer = owners.fixer(i)
        (own if writer is None else by_writer.setdefault(writer, [])).append(i)
    order = sorted(by_writer, key=owners.writers.index)
    return Split(
        [i for i in own if i.source is Source.TEST], [Fix(w.role, by_writer[w]) for w in order]
    )


def fix_lines(fix: Fix) -> list[str]:
    """The brief lines for one fix: its items, then the cited design rule."""
    lines = ["Items:"]
    for i in fix.items:
        lines += [f"- {i.shown} ({i.source})", *(f"    {x}" for x in i.lines)]
    return lines + _rule_lines(fix)


def _rule_lines(fix: Fix) -> list[str]:
    if not fix.rule:
        return []
    return [RULE_LINE.format(rule=fix.rule) + (f": {fix.why}" if fix.why else "")]


def _assertions(diff: str, mark: str, header: str) -> Counter[str]:
    lines = [x[1:] for x in diff.splitlines() if x.startswith(mark) and not x.startswith(header)]
    kept = (re.sub(r"\s+", "", x) for x in lines if any(p.search(x) for p in ASSERTION_MARKS))
    return Counter(kept)


def asserts_changed(diff: str) -> bool:
    """Whether the diff removes and adds different assertion lines (whitespace ignored)."""
    return _assertions(diff, "-", "---") != _assertions(diff, "+", "+++")


def fix_note(record: FixRecord) -> str:
    """One phrase on whether a fix changed assertions and named a rule."""
    return FIX_NOTES[(bool(record.asserts), record.changed)].format(asserts=record.asserts)


def load_fix(data: dict[str, Any]) -> Fix:
    """Rebuild a fix from ``state.json``."""
    items = [Item(**{**i, "source": Source(i["source"])}) for i in data["items"]]
    return Fix(**{**data, "items": items})
