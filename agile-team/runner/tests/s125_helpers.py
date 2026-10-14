"""Helpers for the s125 tests: hand-made xunit1 reports and a runner that writes them."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from agile_team import system
from agile_team.config import ReportOptions

FOLDER = Path("/fake/run/reports")
ROOT = "agile-team/runner"
OPTIONS = ReportOptions(
    "--junitxml={file} -o junit_family=xunit1", "--deselect={id}", "--ignore={id}"
)
JUNITXML = re.compile(r"--junitxml=(\S+)")

NEW_FAIL = f"{ROOT}/tests/test_new.py::test_fresh"
NEW_PASS = f"{ROOT}/tests/test_new.py::test_fine"
OLD_PASS = f"{ROOT}/tests/test_old.py::test_stable"
OLD_FAIL = f"{ROOT}/tests/test_old.py::test_broken"


def case(file: str, classname: str, name: str, line: int | None, child: str = "") -> str:
    """One xunit1 ``<testcase>``; ``child`` is e.g. ``<failure message="boom"/>``."""
    at = "" if line is None else f' line="{line}"'
    return f'<testcase classname="{classname}" name="{name}" file="{file}"{at}>{child}</testcase>'


def report(*cases: str) -> str:
    """A whole xunit1 report holding ``cases``."""
    return f'<testsuites><testsuite name="pytest">{"".join(cases)}</testsuite></testsuites>'


FAIL = '<failure message="boom&#10;second line">trace</failure>'


class Writer:
    """A command runner: for every ``--junitxml=<path>`` it writes the next scripted report."""

    def __init__(self, reports: list[str | None], code: int = 0, out: str = "") -> None:
        self.reports = list(reports)
        self.code, self.out = code, out
        self.calls: list[str] = []

    def __call__(self, command: str) -> tuple[int, str]:
        self.calls.append(command)
        for path in JUNITXML.findall(command):
            text = self.reports.pop(0) if self.reports else None
            if text is not None:
                system.write_text(Path(path.strip("'\"")), text)
        return self.code, self.out


def writer(*reports: str | None, code: int = 0) -> Callable[[str], tuple[int, str]]:
    """A ``Writer`` for ``reports``."""
    return Writer(list(reports), code)
