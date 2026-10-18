"""Build test commands that write a JUnit report, and read the report (s125).

``{report}`` or ``{report:<root>}`` in a ``test`` or ``coverage`` command stands for the
report option of the toolchain.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from re import Match

from . import junit, system
from .commands import CommandRunner
from .config import PLACEHOLDER, ReportOptions

FOLDER = "reports"  # under the run directory
LANDING_FOLDER = "reports-landing"  # N11b: siblings, so one user never empties another's
STORY_FOLDER = "reports-story"  # one folder per story gate inside
APPENDED = " {report}"


@dataclass(frozen=True)
class Reporting:
    """Where reports go: the toolchain's report option and the folder under the run directory."""

    options: ReportOptions = field(default_factory=ReportOptions)
    folder: Path = Path()


@dataclass(frozen=True)
class Built:
    """A command ready to run and its report files."""

    command: str
    files: tuple[tuple[str, Path], ...]


@dataclass(frozen=True)
class TestRun:
    """A built run's exit code, text and report (None when none was written)."""

    __test__ = False  # not a pytest class

    code: int
    out: str
    report: junit.Report | None


class _Filling:
    """Replaces each placeholder of one command, numbering the report files."""

    def __init__(self, reporting: Reporting) -> None:
        self.reporting = reporting
        self.files: list[tuple[str, Path]] = []

    def __call__(self, found: Match[str]) -> str:
        root = found["root"] or ""
        path = self.reporting.folder / f"{len(self.files) + 1}.xml"
        self.files.append((root, path))
        return self.reporting.options.option.replace("{file}", shlex.quote(str(path)))


def build(template: str, reporting: Reporting) -> Built:
    """Fill every ``{report}`` of ``template``; append one when it has none (P2)."""
    text = template if PLACEHOLDER.search(template) else template + APPENDED
    filling = _Filling(reporting)
    command = PLACEHOLDER.sub(filling, text)
    return Built(command, tuple(filling.files))


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
    """Empty the report folder, run, read."""
    _emptied(built)
    code, out = runner(built.command)
    return TestRun(code, out, read(built))
