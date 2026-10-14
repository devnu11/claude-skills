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
    GATE_TESTS_RED = "gate.tests-red"
    GATE_TESTS_REWORK = "gate.tests-rework"
    GATE_TESTS_COVERAGE = "gate.tests+coverage"
    GATE_SUITE_RUNS = "gate.suite-runs"
    GATE_DISPUTE = "gate.dispute-output"
    GATE_ROUTE_LINT = "gate.route-lint"
    PRESENTATION_TRIAL = "presentation.trial"
    GATE_GREEN = "gate.green"
    BOUNDARY_SYNC = "boundary.sync"
    BOUNDARY_CHECK = "boundary.check"
    BOUNDARY_REVIEW = "boundary.review"
    BOUNDARY_PUSH = "boundary.push"
    BOUNDARY_REBASE = "boundary.rebase"
    BOUNDARY_RESTACK = "boundary.restack"
    BOUNDARY_CI_WAIT = "boundary.ci-wait"
    RUN_TESTS = "runner-tool.run_tests"
    RUN_NEW_TESTS = "runner-tool.run_new_tests"


@dataclass(frozen=True)
class Stage:
    """One row: a stage's name, description, when it runs and what it attaches to."""

    name: Name
    description: str
    when: When
    attach: Attach

    def as_dict(self) -> dict[str, str]:
        """The row as the ``tools`` command prints it."""
        return {
            "name": str(self.name),
            "description": self.description,
            "when": str(self.when),
            "attach": str(self.attach),
        }


B, A, D = When.BEFORE, When.AFTER, When.DURING
STEP, STORY, BOUND = Attach.STEP, Attach.STORY, Attach.BOUNDARY

_ROWS: tuple[tuple[Name, When, Attach, str], ...] = (
    (
        Name.ENV_PREPARE, B, STEP,
        "Prepare the acceptance environment for the Customer Proxy: "
        "sandbox, prepare command or service start",
    ),
    (
        Name.PRESENTATION_LAYOUT, B, STEP,
        "Lay out the story's presentation and its git workspace before the integration tester",
    ),
    (Name.QUALITY_LINT, B, STEP, "Run the lint command before the quality step"),
    (Name.QUALITY_STATIC, B, STEP, "Run the static-analysis command before the quality step"),
    (Name.QUALITY_COVERAGE, B, STEP, "Run the coverage command before the quality step"),
    (Name.CHECKOUT_GUARD, B, STEP, "Check the branch and HEAD are the team's before the next step"),
    (Name.CHECKOUT_VERIFY, A, STEP, "Check the branch and HEAD did not move during the step"),
    (Name.GATE_TESTS_RED, A, STEP, "The tests gate: the new tests must fail before implementation"),
    (
        Name.GATE_TESTS_REWORK, A, STEP,
        "The tests gate on a reworked story: red, or green with a tests claim",
    ),
    (
        Name.GATE_TESTS_COVERAGE, A, STEP,
        "The implement gate: one coverage run proves green and the total",
    ),
    (
        Name.GATE_SUITE_RUNS, A, STEP,
        "Run the test command a story's suite_runs times in a row after its suite step's gate",
    ),
    (Name.GATE_DISPUTE, A, STEP, "Run the test command to show a disputed test's output"),
    (
        Name.GATE_ROUTE_LINT, A, STEP,
        "Run lint and static to route a failed gate's items to their owners",
    ),
    (
        Name.PRESENTATION_TRIAL, A, STEP,
        "The e2e gate: the presentation is complete and its service starts and answers",
    ),
    (
        Name.GATE_GREEN, A, STORY,
        "Prove the suite green before the PO passes a story stuck at tests",
    ),
    (
        Name.BOUNDARY_SYNC, B, BOUND,
        "Fetch the target and record the team branch; at a sprint end, add the sprint to the review stack",  # noqa: E501
    ),
    (Name.BOUNDARY_CHECK, A, BOUND, "Run the full checks on the team branch"),
    (Name.BOUNDARY_REVIEW, A, BOUND, "Build and check the per-sprint review branches"),
    (
        Name.BOUNDARY_PUSH, A, BOUND,
        "Push the review branches and open or update their pull requests",
    ),
    (
        Name.BOUNDARY_REBASE, A, BOUND,
        "Rebase the team branch onto the target (sprint end only)",
    ),
    (
        Name.BOUNDARY_RESTACK, A, BOUND,
        "Bring every review PR up to date, bottom up: rebase, same tree, push, retarget",
    ),
    (
        Name.BOUNDARY_CI_WAIT, A, BOUND,
        "Wait for the pull requests' CI checks and read failing logs",
    ),
    (Name.RUN_TESTS, D, STEP, "Run the tests a developer named"),
    (Name.RUN_NEW_TESTS, D, STEP, "Run the story's new test files for a developer"),
)  # fmt: skip

STAGES: dict[Name, Stage] = {
    name: Stage(name, text, when, attach) for name, when, attach, text in _ROWS
}
NAMESPACES: frozenset[str] = frozenset(n.split(".")[0] for n in Name) | {PO_NAMESPACE}
QUALITY: dict[str, Name] = {
    "lint": Name.QUALITY_LINT,
    "static": Name.QUALITY_STATIC,
    "coverage": Name.QUALITY_COVERAGE,
}
BOUNDARY: dict[str, Name] = {
    "sync": Name.BOUNDARY_SYNC,
    "check": Name.BOUNDARY_CHECK,
    "review": Name.BOUNDARY_REVIEW,
    "push": Name.BOUNDARY_PUSH,
    "rebase": Name.BOUNDARY_REBASE,
    "restack": Name.BOUNDARY_RESTACK,
    "ci": Name.BOUNDARY_CI_WAIT,
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


@dataclass
class Run:
    """One open stage: its row, place, and the command kept for the event."""

    stage: Stage
    place: Place
    detail: str = ""
    code: int | None = None
    raised: str | None = None
    listeners: list[Callable[[str], None]] = field(default_factory=list)

    def hear(self, line: str) -> None:
        """Tell every listener one line of the stage's command output."""
        for listener in self.listeners:
            listener(line)

    def note(self, command: str, code: int) -> None:
        """Keep the first failing command, else the latest one."""
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
        run.raised = type(exc).__name__
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
