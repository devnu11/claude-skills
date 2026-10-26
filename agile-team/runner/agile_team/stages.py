"""The runner's own stages: a table of names, and the open-stage record (s99).

The caller of a stage names it; commands run inside only note themselves.
Pure: no import from other ``agile_team`` modules.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum

LABEL_MAX = 24  # A stage label's most characters (s127)
RUNNER_ROLE = "runner"
NOT_UP = 1
STAGE_NAME = re.compile(r"[a-z0-9-]+\.[a-z0-9_+-]+")
PO_NAMESPACE = "po"


class When(StrEnum):
    """When a stage runs, relative to the step or sprint it attaches to."""

    BEFORE = "before"
    AFTER = "after"
    DURING = "during"


class Attach(StrEnum):
    """What a stage attaches to."""

    STEP = "step"
    STORY = "story"
    BOUNDARY = "boundary"


class Name(StrEnum):
    """Every stage the runner runs."""

    ENV_PREPARE = "env.prepare"
    PRESENTATION_LAYOUT = "presentation.layout"
    QUALITY_LINT = "quality.lint"
    QUALITY_STATIC = "quality.static"
    QUALITY_COVERAGE = "quality.coverage"
    CHECKOUT_GUARD = "checkout.guard"
    CHECKOUT_VERIFY = "checkout.verify"
    GATE_TESTS_COVERAGE = "gate.tests+coverage"
    GATE_SUITE_RUNS = "gate.suite-runs"
    GATE_DISPUTE = "gate.dispute-output"
    GATE_ROUTE_LINT = "gate.route-lint"
    PRESENTATION_TRIAL = "presentation.trial"
    GATE_GREEN = "gate.green"
    BOUNDARY_SYNC = "boundary.sync"
    BOUNDARY_CHECK = "boundary.check"
    BOUNDARY_PUSH = "boundary.push"
    BOUNDARY_OPEN = "boundary.open"
    BOUNDARY_REPLAY = "boundary.replay"
    BOUNDARY_PUSH_REPLAYED = "boundary.push-replayed"
    BOUNDARY_CI_REPLAYED = "boundary.ci-replayed"
    STORY_LAND = "story.land"
    BOUNDARY_CI_WAIT = "boundary.ci-wait"
    RUN_TESTS = "runner-tool.run_tests"
    RUN_NEW_TESTS = "runner-tool.run_new_tests"
    STOP_HANDOFF = "stop.handoff"
    STOP_LINT = "stop.lint"
    STOP_SUITE = "stop.suite"
    STOP_PRESENTATION = "stop.presentation"
    STOP_REQUIREMENTS = "stop.requirements"


@dataclass(frozen=True)
class Stage:
    """One row: a stage's name, short label, description, when it runs and what it attaches to."""

    name: Name
    label: str
    description: str
    when: When
    attach: Attach

    def as_dict(self) -> dict[str, str]:
        """The row as the ``tools`` command prints it."""
        return {
            "name": str(self.name),
            "label": self.label,
            "description": self.description,
            "when": str(self.when),
            "attach": str(self.attach),
        }


B, A, D = When.BEFORE, When.AFTER, When.DURING
STEP, STORY, BOUND = Attach.STEP, Attach.STORY, Attach.BOUNDARY

_ROWS: tuple[tuple[Name, When, Attach, str, str], ...] = (
    (
        Name.ENV_PREPARE, B, STEP, "env prepare",
        "Prepare the acceptance environment for the Customer Proxy: "
        "sandbox, prepare command or service start",
    ),
    (
        Name.PRESENTATION_LAYOUT, B, STEP, "presentation layout",
        "Lay out the story's presentation and its git workspace before the integration tester",
    ),
    (Name.QUALITY_LINT, B, STEP, "ruff check", "Lint the whole repo before the quality step"),
    (Name.QUALITY_STATIC, B, STEP, "ruff format", "Static analysis of the whole repo before the quality step"),  # noqa: E501
    (Name.QUALITY_COVERAGE, B, STEP, "coverage report", "The full suite with coverage, for the quality step's report"),  # noqa: E501
    (Name.CHECKOUT_GUARD, B, STEP, "checkout guard", "Check the branch and HEAD are the team's before the next step"),  # noqa: E501
    (Name.CHECKOUT_VERIFY, A, STEP, "checkout verify", "Check the branch and HEAD did not move during the step"),  # noqa: E501
    (
        Name.GATE_TESTS_COVERAGE, A, STEP, "pytest + coverage",
        "Implement gate: the full suite with coverage, once; every test must pass and coverage must meet the threshold",  # noqa: E501,
    ),
    (
        Name.GATE_SUITE_RUNS, A, STEP, "pytest: repeat runs",
        "The full suite again, the story's suite_runs times in a row, after its suite step's gate passes",  # noqa: E501
    ),
    (Name.GATE_DISPUTE, A, STEP, "pytest: disputed test", "The full suite, to show a disputed test's output"),  # noqa: E501
    (
        Name.GATE_ROUTE_LINT, A, STEP, "ruff check + format",
        "Lint and static analysis of the whole repo, to route a failed gate's items to their owners",  # noqa: E501
    ),
    (
        Name.PRESENTATION_TRIAL, A, STEP, "presentation trial",
        "The e2e gate: the presentation is complete and its service starts and answers",
    ),
    (
        Name.GATE_GREEN, A, STORY, "pytest: must pass",
        "The full suite must pass before the PO passes a story stuck at tests",
    ),
    (
        Name.BOUNDARY_SYNC, B, BOUND, "boundary sync",
        "Fetch the target and record the team branch; at a sprint start, rebase it onto the target; at a sprint end, record the sprint's own branch",  # noqa: E501
    ),
    (Name.BOUNDARY_CHECK, A, BOUND, "boundary check", "Lint, static analysis, the full suite with coverage, once, and each environment's e2e, on the team branch; at a sprint start a failure is recorded as known failures and holds nothing"),  # noqa: E501
    (
        Name.BOUNDARY_PUSH, A, BOUND, "push as built + PR",
        "Push the team branch as it is to the sprint's branch and open or reuse its pull request onto the target",  # noqa: E501
    ),
    (
        Name.BOUNDARY_CI_WAIT, A, BOUND, "CI wait",
        "Wait for the as-built push's CI and read failing logs; green is the gate for the rebase",
    ),
    (
        Name.BOUNDARY_OPEN, B, BOUND, "open sprint branch",
        "At a sprint start, create the sprint's remote branch at the start head and open its entry",
    ),
    (
        Name.BOUNDARY_REPLAY, A, BOUND, "replay onto target",
        "Replay the team branch onto the target story by story, only after green CI (sprint end only)",  # noqa: E501
    ),
    (
        Name.BOUNDARY_PUSH_REPLAYED, A, BOUND, "push replayed",
        "Push the replayed team branch to the next replay branch and open a ready PR from it",
    ),
    (
        Name.BOUNDARY_CI_REPLAYED, A, BOUND, "CI wait (replayed)",
        "Wait for the replayed branch's CI and record it; a red result is reported, never held",
    ),
    (
        Name.STORY_LAND, D, STORY, "land",
        "Land a story: merge it into the sprint branch, run the full checks and the landing CI",
    ),
    (Name.RUN_TESTS, D, STEP, "pytest: named tests", "Only the tests a developer named, run for that developer"),  # noqa: E501
    (Name.RUN_NEW_TESTS, D, STEP, "pytest: new test files", "Only the story's new test files, run for a developer"),  # noqa: E501
    (Name.STOP_HANDOFF, A, STEP, "stop: handoff parses", "Stop check: the step's handoff block parses"),  # noqa: E501
    (Name.STOP_LINT, A, STEP, "stop: lint fix + check", "Stop check: fix the step's changed files with the toolchain's fixers, then lint them"),  # noqa: E501
    (Name.STOP_SUITE, A, STEP, "stop: suite + coverage", "Stop check: the implement gate's suite and coverage, before the developer may stop"),  # noqa: E501
    (Name.STOP_PRESENTATION, A, STEP, "stop: presentation", "Stop check: the story's presentation is complete, before the integration-tester may stop"),  # noqa: E501
    (Name.STOP_REQUIREMENTS, A, STEP, "stop: requirements", "Stop check: every changed or retired requirement has a reason in the handoff, before the architect may stop"),  # noqa: E501
)  # fmt: skip

STAGES: dict[Name, Stage] = {
    name: Stage(name, label, text, when, attach) for name, when, attach, label, text in _ROWS
}
LABELS: frozenset[str] = frozenset(s.label for s in STAGES.values())
NAMESPACES: frozenset[str] = frozenset(n.split(".")[0] for n in Name) | {PO_NAMESPACE}
QUALITY: dict[str, Name] = {
    "lint": Name.QUALITY_LINT,
    "static": Name.QUALITY_STATIC,
    "coverage": Name.QUALITY_COVERAGE,
}
BOUNDARY: dict[str, Name] = {
    "sync": Name.BOUNDARY_SYNC,
    "check": Name.BOUNDARY_CHECK,
    "push": Name.BOUNDARY_PUSH,
    "ci": Name.BOUNDARY_CI_WAIT,
    "open": Name.BOUNDARY_OPEN,
    "replay": Name.BOUNDARY_REPLAY,
    "push-replayed": Name.BOUNDARY_PUSH_REPLAYED,
    "ci-replayed": Name.BOUNDARY_CI_REPLAYED,
}
RUNNER_TOOL: dict[str, Name] = {
    "run_tests": Name.RUN_TESTS,
    "run_new_tests": Name.RUN_NEW_TESTS,
}


def reserved(name: str) -> bool:
    """True when ``name`` is a built-in stage or sits in a built-in namespace."""
    return name in STAGES or name.split(".")[0] in NAMESPACES


@dataclass(frozen=True)
class Place:
    """The story and step a stage run attaches to; both None outside a step."""

    story: str | None = None
    step: str | None = None


NOWHERE = Place()


@dataclass(frozen=True)
class Invocation:
    """One command line a stage ran and its exit code (s175)."""

    command: str
    code: int


class CommandFailed(Exception):
    """An error raised because one command failed; ``invocation`` names it (s175 E1)."""

    def __init__(self, message: str, invocation: Invocation | None = None) -> None:
        super().__init__(message)
        self.invocation = invocation


def get_error_line(exc: BaseException) -> str:
    """The first non-blank line of ``str(exc)``, stripped; "" when there is none."""
    lines = [line.strip() for line in str(exc).splitlines()]
    return next((line for line in lines if line), "")


@dataclass(frozen=True)
class Attempt:
    """Which Stop-hook attempt a stage ran in: ``n`` of at most ``of``."""

    n: int
    of: int

    def as_dict(self) -> dict[str, int]:
        """The attempt as event data."""
        return {"n": self.n, "of": self.of}


@dataclass
class Run:
    """One open stage: its row, place, and the command kept for the event."""

    stage: Stage
    place: Place
    detail: str = ""
    code: int | None = None
    raised: str | None = None
    error: str | None = None
    attempt: Attempt | None = None
    listeners: list[Callable[[str], None]] = field(default_factory=list)

    def hear(self, line: str) -> None:
        """Tell every listener one line of the stage's command output."""
        for listener in self.listeners:
            listener(line)

    def record_raise(self, exc: BaseException) -> None:
        """Keep the class, the first line and the raising call of ``exc`` (s175 E2)."""
        self.raised = type(exc).__name__
        self.error = get_error_line(exc)
        call = exc.invocation if isinstance(exc, CommandFailed) else None
        self.detail, self.code = (call.command, call.code) if call else ("", None)

    def note(self, command: str, code: int) -> None:
        """Keep the first failing command, else the latest one."""
        self.last = (command, code)
        if self.code:
            return
        self.detail, self.code = command, code


Opener = Callable[[Name], AbstractContextManager[Run]]

_OPEN: ContextVar[Run | None] = ContextVar("open_stage", default=None)


@contextmanager
def entered(run: Run) -> Iterator[Run]:
    """Make ``run`` the innermost open stage; record a raised exception's class and re-raise."""
    token = _OPEN.set(run)
    try:
        yield run
    except BaseException as exc:
        run.record_raise(exc)
        raise
    finally:
        _OPEN.reset(token)


def current() -> Run | None:
    """The innermost open stage run, or None."""
    return _OPEN.get()


def opened(name: Name, place: Place) -> AbstractContextManager[Run]:
    """Open ``name`` (KeyError if unlisted) at ``place``."""
    return entered(Run(STAGES[name], place))


def unlogged(name: Name) -> AbstractContextManager[Run]:
    """Open ``name`` nowhere in particular; the default opener."""
    return opened(name, NOWHERE)


def note(command: str, code: int) -> None:
    """Add a command to the innermost open stage; nothing when none is open."""
    run = _OPEN.get()
    if run:
        run.note(command, code)
