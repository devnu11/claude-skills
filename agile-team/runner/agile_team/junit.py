"""Read a pytest xunit1 JUnit report into test cases (s125 P6).

The reports are the runner's own pytest output, so the stdlib parser is enough.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import StrEnum


class Result(StrEnum):
    """What one test did."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Case:
    """One ``<testcase>``: its repo-relative id, file, 1-based line and result."""

    id: str
    file: str
    line: int | None
    result: Result
    message: str = ""
    detail: str = ""


class ReportError(Exception):
    """Raised when a report is not valid XML."""


FAILING_TAGS = ("failure", "error")
ERROR_LINES = 5
ERROR_MARK = "E "


def _marked_lines(lines: list[str]) -> list[str]:
    return [x[len(ERROR_MARK) :].lstrip() for x in lines if x.startswith(ERROR_MARK)]


def error_lines(failure: ET.Element) -> str:
    """The first error lines of a ``<failure>``/``<error>`` element (G4)."""
    lines = (failure.text or "").splitlines()
    picked = _marked_lines(lines) or [x for x in lines if x.strip()]
    picked = picked or [failure.get("message", "")]
    return "\n".join(picked[:ERROR_LINES])


def _prefixed(root: str, path: str) -> str:
    return f"{root}/{path}" if root else path


def _module(file: str) -> str:
    return file.removesuffix(".py").replace("/", ".")


def _class_part(classname: str, file: str) -> str:
    rest = classname.removeprefix(_module(file)).strip(".")
    return rest.replace(".", "::") + "::" if rest else ""


def node_id(case: ET.Element, root: str) -> str:
    """The repo-relative pytest node id of a ``<testcase>``; a file id when it has no class."""
    file = case.get("file", "")
    classname = case.get("classname", "")
    if not classname:
        return _prefixed(root, file)
    return _prefixed(root, f"{file}::{_class_part(classname, file)}{case.get('name', '')}")


def _result(case: ET.Element) -> tuple[Result, str, str]:
    for tag in FAILING_TAGS:
        if (child := case.find(tag)) is not None:
            return Result.FAILED, child.get("message", "").split("\n")[0], error_lines(child)
    if case.find("skipped") is not None:
        return Result.SKIPPED, "", ""
    return Result.PASSED, "", ""


def _line(case: ET.Element) -> int | None:
    raw = case.get("line")
    return None if raw is None or not case.get("classname") else int(raw) + 1


def _case(element: ET.Element, root: str) -> Case:
    result, message, detail = _result(element)
    file = _prefixed(root, element.get("file", ""))
    return Case(node_id(element, root), file, _line(element), result, message, detail)


def parse(text: str, root: str) -> tuple[Case, ...]:
    """Every ``<testcase>`` of one xunit1 report, ids prefixed with ``root``."""
    try:
        tree = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ReportError(str(exc)) from exc
    return tuple(_case(e, root) for e in tree.iter("testcase"))


@dataclass(frozen=True)
class Report:
    """The cases of all the report files of one run."""

    cases: tuple[Case, ...] = ()

    def failed(self) -> tuple[Case, ...]:
        """The cases that failed or errored."""
        return tuple(c for c in self.cases if c.result is Result.FAILED)

    def failures(self) -> dict[str, str]:
        """Failing or erroring case id -> its detail (or message), in report order (G5)."""
        return {c.id: c.detail or c.message for c in self.failed()}

    def _of(self, id: str) -> list[Case]:
        if "::" in id:
            return [c for c in self.cases if c.id == id]
        return [c for c in self.cases if c.file == id]

    def holds(self, id: str) -> bool:
        """Whether the report has the test, or any test of the file for a file id."""
        return bool(self._of(id))

    def passed(self, id: str) -> bool:
        """Whether the report holds ``id`` and every case of it passed."""
        found = self._of(id)
        return bool(found) and all(c.result is Result.PASSED for c in found)
