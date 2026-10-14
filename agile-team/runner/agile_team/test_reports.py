"""Build test commands that write a JUnit report and skip pending ids, and read the report (s125).

``{report}`` or ``{report:<root>}`` in a ``test`` or ``coverage`` command stands for the
report option of the toolchain plus the skip options for the pending ids under ``<root>``.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from re import Match

from . import junit, pending_tests, stages, system, test_tally
from .commands import CommandRunner
from .config import PLACEHOLDER, ReportOptions
from .git_ops import Git
from .pending_tests import Changed, Registry

FOLDER = "reports"  # under the run directory
APPENDED = " {report}"


def _unchanged(_base: str) -> Changed:
    return {}


@dataclass(frozen=True)
class ChangedFor:
    """The step's changed lines since ``base`` (P10); ``{}`` for an empty base."""

    git: Git

    def __call__(self, base: str) -> Changed:
        if not base:
            return {}
        return pending_tests.changed_lines(self.git.diff_lines(base), self.git.untracked())


def changed_for(git: Git) -> ChangedFor:
    """A ``Reporting.changed`` reading ``git``."""
    return ChangedFor(git)


@dataclass(frozen=True)
class Reporting:
    """Where reports go and how to read the registry and the step's changes."""

    options: ReportOptions = field(default_factory=ReportOptions)
    folder: Path = Path()
    registry: Callable[[], Registry] = Registry
    changed: Callable[[str], Changed] = _unchanged


@dataclass(frozen=True)
class Ask:
    """What ``build`` needs: the reporting setup and the ids to skip per story."""

    reporting: Reporting
    skipped: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class Built:
    """A command ready to run: its report files and the ids it skips."""

    command: str
    files: tuple[tuple[str, Path], ...]
    skipped: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class TestRun:
    """A built run's exit code, text, report (None when none was written) and skipped ids."""

    __test__ = False  # not a pytest class

    code: int
    out: str
    report: junit.Report | None
    skipped: Mapping[str, tuple[str, ...]]
    own: tuple[str, ...] = ()


@dataclass(frozen=True)
class Under:
    """The ids of a skip list that sit under a root."""

    root: str
    ids: tuple[str, ...]


def _relative(root: str, id: str) -> str | None:
    if not root:
        return id
    prefix = root.rstrip("/") + "/"
    return id.removeprefix(prefix) if id.startswith(prefix) else None


def _skip_option(options: ReportOptions, id: str) -> str:
    template = options.deselect if "::" in id else options.ignore
    return template.replace("{id}", id) if template else ""


def skip_options(options: ReportOptions, under: Under) -> list[str]:
    """The skip options for the ids under ``under.root``, ids made root-relative (P5)."""
    ids = [_relative(under.root, i) for i in under.ids]
    return [o for i in ids if i is not None and (o := _skip_option(options, i))]


def skip_line(options: ReportOptions, under: Under) -> str:
    """The skip options joined for a shell or ``PYTEST_ADDOPTS`` (P19)."""
    return shlex.join(skip_options(options, under))


def _all_ids(skipped: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    return tuple(i for ids in skipped.values() for i in ids)


class _Filling:
    """Replaces each placeholder of one command, numbering the report files."""

    def __init__(self, ask: Ask) -> None:
        self.ask = ask
        self.files: list[tuple[str, Path]] = []

    def __call__(self, found: Match[str]) -> str:
        root = found["root"] or ""
        options = self.ask.reporting.options
        path = self.ask.reporting.folder / f"{len(self.files) + 1}.xml"
        self.files.append((root, path))
        option = options.option.replace("{file}", shlex.quote(str(path)))
        skips = skip_line(options, Under(root, _all_ids(self.ask.skipped)))
        return f"{option} {skips}".strip()


def build(template: str, ask: Ask) -> Built:
    """Fill every ``{report}`` of ``template``; append one when it has none (P2)."""
    text = template if PLACEHOLDER.search(template) else template + APPENDED
    filling = _Filling(ask)
    command = PLACEHOLDER.sub(filling, text)
    return Built(command, tuple(filling.files), ask.skipped)


def _parsed(root: str, path: Path) -> tuple[junit.Case, ...] | None:
    if not system.is_file(path):
        return None
    try:
        return junit.parse(system.read_text(path), root)
    except junit.ReportError:
        return None


def read(built: Built) -> junit.Report | None:
    """The cases of every report file that exists and parses; None when none does."""
    parsed = [_parsed(root, path) for root, path in built.files]
    found = [cases for cases in parsed if cases is not None]
    return junit.Report(tuple(c for cases in found for c in cases)) if found else None


def _emptied(built: Built) -> None:
    folder = built.files[0][1].parent
    if system.is_dir(folder):
        system.remove_tree(folder)
    system.make_dirs(folder)


def run(built: Built, runner: CommandRunner) -> TestRun:
    """Empty the report folder, tell the tally the pending count, run, read (P3, P18)."""
    _emptied(built)
    stages.hear(test_tally.pending_record(len(_all_ids(built.skipped))))
    code, out = runner(built.command)
    return TestRun(code, out, read(built), built.skipped)
