"""Which Bash segments start a test run, and which roles may not start it (s69).

Pure and stdlib only. The guard feeds it the words of each Bash segment.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from pathlib import PurePosixPath

ASK_RUNNER = (
    "name the tests instead (`pytest -q tests/test_x.py::test_y`), or, as a developer, "
    "ask the runner with its `run_tests` tool (test ids) or its `run_new_tests` tool "
    "(the story's new tests)"
)
FULL_DENIED = (
    "the full suite is the runner's to run: it runs it at the gates and puts the "
    "output in your brief (## Runner results); " + ASK_RUNNER
)
COVERAGE_DENIED = (
    "coverage is the runner's to run: the implement gate runs it and your brief "
    "shows the result (## Runner results); " + ASK_RUNNER
)
READ_ONLY_DENIED = (
    "{role} reads tests and does not run them: the runner's results are in your "
    "brief (## Runner results)"
)


class Run(StrEnum):
    """What a Bash segment asks a test tool to do (s69)."""

    FULL = "full"
    COVERAGE = "coverage"
    TARGETED = "targeted"


EVERY_ROLE = "*"
TEST_TOOLS = frozenset({"pytest", "py.test"})
SHELLS = frozenset({"bash", "sh", "zsh"})
LAUNCHERS = frozenset(
    {
        "uv",
        "uvx",
        "poetry",
        "pipenv",
        "hatch",
        "pdm",
        "timeout",
        "gtimeout",
        "env",
        "nice",
        "time",
        "nohup",
        "coverage",
        *SHELLS,
        *TEST_TOOLS,
    }
)
VALUE_OPTIONS = frozenset(
    {
        "--ignore",
        "--ignore-glob",
        "--deselect",
        "-c",
        "--confcutdir",
        "--rootdir",
        "--basetemp",
        "-k",
        "-m",
        "-p",
        "-o",
    }
)
NODE_MARK = "::"
GLOB_CHARS = ("*", "?", "[")
PYTHON_PREFIX = "python"
SHELL_COMMAND_FLAG = "-c"
COVERAGE_FLAG = "--cov"


@dataclass(frozen=True)
class SuiteRule:
    """Who may not start one kind of test run, and the reason they are told (S7)."""

    run: Run
    denied: frozenset[str]
    reason: str
    allowed: frozenset[str] = frozenset()

    def applies(self, role: str) -> bool:
        """Whether this row denies ``role``."""
        named = EVERY_ROLE in self.denied or role in self.denied
        return named and role not in self.allowed


SUITE_RULES: tuple[SuiteRule, ...] = (
    SuiteRule(Run.FULL, frozenset({EVERY_ROLE}), FULL_DENIED, frozenset({"devops"})),
    SuiteRule(Run.COVERAGE, frozenset({EVERY_ROLE}), COVERAGE_DENIED, frozenset({"devops"})),
    SuiteRule(Run.TARGETED, frozenset({"code-reviewer", "quality-czar"}), READ_ONLY_DENIED),
)


def is_target(word: str) -> bool:
    """A test file or node id, the thing a targeted run names (S5)."""
    path = word.split(NODE_MARK, 1)[0]
    return (
        not word.startswith("-") and path.endswith(".py") and not any(c in path for c in GLOB_CHARS)
    )


def _name(word: str) -> str:
    return PurePosixPath(word).name


def _launcher(words: list[str]) -> bool:
    """Whether the segment's first word can start a test tool (S1)."""
    first = _name(words[0]) if words else ""
    return first in LAUNCHERS or first.startswith(PYTHON_PREFIX)


def _expanded(words: list[str]) -> list[str]:
    """``bash -c "a b"`` seen as ``bash -c a b`` (S2)."""
    if _name(words[0]) not in SHELLS or SHELL_COMMAND_FLAG not in words:
        return words
    at = words.index(SHELL_COMMAND_FLAG) + 1
    return [*words[:at], *" ".join(words[at : at + 1]).split(), *words[at + 1 :]]


def _tool_index(words: list[str]) -> int | None:
    return next((i for i, w in enumerate(words) if _name(w) in TEST_TOOLS), None)


def _is_coverage_run(words: list[str], tool: int | None) -> bool:
    runs = any(a == "coverage" and b == "run" for a, b in pairwise(words))
    flagged = tool is not None and any(w.startswith(COVERAGE_FLAG) for w in words)
    return runs or flagged


def _targets_after(words: list[str]) -> bool:
    """Whether a word is a target that is not the value of a value option (S4)."""
    before = ["", *words]
    return any(is_target(w) and p not in VALUE_OPTIONS for p, w in zip(before, words, strict=False))


def run_kind(words: list[str]) -> Run | None:
    """The kind of test run one Bash segment starts, or None (S1-S6)."""
    if not words or not _launcher(words):
        return None
    words = _expanded(words)
    tool = _tool_index(words)
    if _is_coverage_run(words, tool):
        return Run.COVERAGE
    if tool is None:
        return None
    return Run.TARGETED if _targets_after(words[tool + 1 :]) else Run.FULL


def suite_denial(role: str, words: list[str]) -> str | None:
    """The first SUITE_RULES reason for ``role`` and this segment, or None (S7)."""
    kind = run_kind(words)
    rule = next((r for r in SUITE_RULES if r.run is kind and r.applies(role)), None)
    return rule.reason.format(role=role) if rule else None
