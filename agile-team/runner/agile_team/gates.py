"""Story pipeline state machine and the runner-checked gates.

Each story walks the enabled steps of ``config.PIPELINE_STEPS``. Two gates run
real commands (red tests after the Unit Tester; green tests plus coverage after
the Developer); the rest read the role's parsed handoff. Every bounce back adds
a round; at the cap the story waits for the Manager's ruling.
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import (
    acceptance,
    fingerprint,
    junit,
    loops,
    pending_tests,
    revert_log,
    stages,
    story_spec,
    suite_runs,
    system,
    test_reports,
)
from . import owners as owners_mod
from .commands import TIMED_OUT, CommandRunner
from .config import TEST_COMMANDS
from .holds import PoHold
from .loops import Author, Fault, Rule, Setback
from .owners import Fix, FixRecord, Item, Owners, Source, Split
from .pending_tests import PendingSet, RedAsk, RegistryError
from .results import Ran, result_tail
from .roles import Dispute, Handoff, TestClaim
from .salvage import Interruption
from .test_reports import TestRun

STEP_ROLES = {
    "design": "architect",
    "tests": "unit-tester",
    "implement": "developer",
    "quality": "quality-czar",
    "review": "code-reviewer",
    "design-review": "architect",
    "e2e": "integration-tester",
    "acceptance": "customer-proxy",
}
UNGATED_ROLES = frozenset({"manager"})
STORYLESS_ROLES = frozenset({"architect", "devops", "unit-tester", "manager"})
STOPPED_HANDOFFS = frozenset({"blocked", "failed"})
BASELINE = ".team/baseline.json"
LS_FILES_COMMAND = "git ls-files -- {path} {suffix}"
LS_ALL_COMMAND = "git ls-files"
ROUTED_COMMANDS = ("lint", "static")
ROUTED = "routed to {owners}; the story comes back to this step after their fix steps"
ALSO_ROUTED = "also routed to {owners}; their fix steps run first"
FIX_NEEDS_STORY = "a gate fix needs a story"
FIX_NONE = "story {id} has no gate fix queued"
FIX_ROLE = "story {id}'s next gate fix is for {role}"
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)%")

REWORK_UNCLAIMED = (
    "tests pass on code from an earlier pass; write a failing test, "
    'or hand off "tests": "changed" or "tests": "confirmed"'
)
REWORK_PASS = "tests pass on code from an earlier pass; tests {claim}"

UNTRACKED = (
    "dispute rejected: {file} (from {test}) is not a tracked file at the repo root, "
    "and no single tracked file ends with that path; hand off the dispute again "
    "with the test's path from the repo root"
)
UNCHANGED = (
    "the disputed test file {file} has not changed since the dispute was raised: "
    "{test} still matches its baseline {short} (whitespace and comment edits "
    "do not count); fix the test, or confirm it with changes_requested and "
    "next_role architect"
)
LEGACY_PASS = "dispute raised before content baselines; passed without a check"
PASS_TESTS_STEP = "story {id} is at step {step!r}; pass_tests only moves a story from tests"
PASS_TESTS_NOT_STUCK = (
    "story {id} is not stuck at tests (no open dispute, round cap, block or "
    "repeated setback); let the tests gate decide"
)
PASS_TESTS_RED = "the suite is red; pass_tests needs a green suite. {reason}"

TIMED_OUT_BOUNCE = "the command did not finish in time:\n{tail}"
REUSED = "{reason} (the stop hook's run on this tree)"
GREEN_TOO_EARLY = "tests pass before implementation; write a failing test"
REPORT_MISSING = (
    "the test command wrote no report in {folder}; "
    "check [toolchain.report] and the {{report}} placeholders:\n{tail}"
)
NOT_PENDING = (
    "these tests fail but are not new or changed in this step, "
    "so they are not pending: {ids}\n{tail}"
)
UNREPORTED_FAILURE = (
    "the test command failed (exit {code}) but its report names no failing test:\n{tail}"
)
PENDING_SET = "{count} pending test(s) for {story}"
PENDING_FAIL = "pending tests of {story} still fail: {ids}"
PENDING_LEFT = "{count} pending test(s) of {story} pass"
PENDING_GONE = "no longer in the suite, dropped from pending: {ids}"
REGISTRY_BAD = "{file} is not valid ({error}); only the runner writes it"
SKIPPED_NOTE = "skipped {counts}"


class StoryStatus(StrEnum):
    """Where a story stands, beyond its pipeline step."""

    ACTIVE = "active"
    NEEDS_MANAGER = "needs_manager"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


FINISHED = frozenset({StoryStatus.DONE, StoryStatus.CANCELLED})


class Verdict(StrEnum):
    """A gate's result.

    ``HOLD`` stays put without counting a round (a block). ``RETURN`` moves back
    without counting a round (the team, not the product, missed a step).
    ``ESCALATE`` stays put, counts no round and waits for the Manager's ruling.
    ``ROUTE`` stays at the step, counts no round, queues gate fix steps for the
    items' owners (s92).
    ``NEXT`` stays at the step, counts no round and hands nothing over; the step runs
    again for the next acceptance environment (s95).
    """

    PASS = "pass"
    BOUNCE = "bounce"
    HOLD = "hold"
    RETURN = "return"
    DISPUTE = "dispute"
    ESCALATE = "escalate"
    ROUTE = "route"
    NEXT = "next"


class DisputeStage(StrEnum):
    """How far a test dispute has got: raised by the developer, or upheld by the unit-tester."""

    RAISED = "raised"
    CONFIRMED = "confirmed"


ANCESTOR_COMMAND = "git merge-base --is-ancestor {sha} HEAD"
ADVANCE_LAST = "story {id} is at {step}, its last step; advance cannot mark it done"
EXCERPT_LINES = 40
TEST_GREEN = "the test command passes, so {test} is not failing"
TEST_NOT_IN_OUTPUT = "the test command fails, but its output never names {name}; its tail:\n{tail}"


@dataclass
class OpenDispute:
    """A developer's claim that a test contradicts the design.

    ``file`` is the resolved repo-relative test file, ``baseline`` its content
    fingerprint when raised.
    """

    test: str
    rule: str
    reason: str
    file: str = ""
    baseline: str = ""
    stage: DisputeStage = DisputeStage.RAISED
    output: str = ""

    def __post_init__(self) -> None:
        self.stage = DisputeStage(self.stage)


def test_file(test: str) -> str:
    """The file part of a test id, before the first ``::``."""
    return test.split("::")[0]


def load_dispute(**data: Any) -> OpenDispute:
    """Build a dispute from saved data, dropping s11's ``base`` key."""
    data.pop("base", None)
    return OpenDispute(**data)


def pick_tracked(file: str, listing: str) -> str | None:
    """``file`` if listed, else the one listed path ending with ``/file``."""
    found = owners_mod.candidates(file, listing)
    return found[0] if len(found) == 1 else None


def read_repo_file(repo: Path, path: str) -> str | None:
    """The text of ``path`` under ``repo``, or None when it is not a file."""
    target = repo / path
    if not system.is_file(target):
        return None
    return system.read_bytes(target).decode("utf-8", errors="replace")


REDESIGN_MISSING = (
    'story {id} was reverted ({count}×); its design {file} needs a "## After revert {count}" '  # noqa: RUF001
    "section saying what changes this time"
)


def _unread(_path: str) -> str | None:
    return None


@dataclass
class PreviousStep:
    """The last gated step on a story: who ran, what they reported and how the gate ruled."""

    role: str
    status: str
    summary: str = ""
    verdict: str = ""
    reason: str = ""
    next_role: str | None = None


@dataclass
class StoryState:
    """One story's position in the pipeline."""

    id: str
    title: str
    step: str
    rounds: int = 0
    status: StoryStatus = StoryStatus.ACTIVE
    commit: str | None = None
    sprint: int | None = None
    developer: str | None = None
    po_developer: str | None = None
    hold: str | None = None
    po_hold: PoHold | None = None
    note: str = ""
    previous: PreviousStep | None = None
    dispute: OpenDispute | None = None
    disputes: int = 0
    implemented: int = 0
    code_commits: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    streak: list[Setback] = field(default_factory=list)
    repeated: str | None = None
    run: list[Setback] = field(default_factory=list)
    escalated_by: Rule | None = None
    interrupted: Interruption | None = None
    depends_on: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    fixes: list[Fix] = field(default_factory=list)
    fixed: list[FixRecord] = field(default_factory=list)
    tried: list[acceptance.Tried] = field(default_factory=list)
    reverted: list[revert_log.RevertEntry] = field(default_factory=list)
    revert_owed: list[str] = field(default_factory=list)


@dataclass
class Outcome:
    """Result of a gate and, for a bounce, the step to return to."""

    verdict: Verdict
    reason: str = ""
    bounce_to: str | None = None
    dispute: OpenDispute | None = None
    author: Author = Author.RUNNER
    rule: Rule = Rule.REPEAT
    ran: Ran | None = None
    extra_ran: tuple[Ran, ...] = ()
    fixes: list[Fix] = field(default_factory=list)
    output: str = field(default="", repr=False)
    tried: acceptance.Tried | None = None
    pending: PendingSet | None = None
    report: junit.Report | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Serving:
    """The story a run is made for and the HEAD its step started from (s125 P16)."""

    story: str = ""
    base: str = ""


def role_fits_step(role: str, step: str) -> bool:
    """Developer specializations (``developer-cli`` …) all fit the implement step."""
    expected = STEP_ROLES[step]
    return role == expected or (expected == "developer" and role.startswith("developer"))


def ruling_refusal(story: StoryState | None, what: str = "a ruling") -> str | None:
    """Why a Manager ruling (or fault, ``what``) cannot apply to ``story``, or ``None``."""
    if story is None:
        return f"{what} needs a story; run the manager on that story"
    if story.status in FINISHED:
        return f"story {story.id} is {story.status}; {what} cannot move it"
    return None


def setback_reason(story: StoryState) -> str:
    """The setback the Manager rules on: the repeated reason, else the last gate's reason."""
    if story.repeated:
        return story.repeated
    return story.previous.reason if story.previous else ""


CONTINUE_BLOCKED = (
    "story {id} is blocked (escalated to the human); continue_story would leave it "
    "stalled. Run the manager on {id} with a ruling or a fault to move it"
)


def continue_refusal(story: StoryState) -> str | None:
    """Why ``continue_story`` may not release ``story``, or ``None``."""
    if story.status is StoryStatus.BLOCKED:
        return CONTINUE_BLOCKED.format(id=story.id)
    return None


def dispatch_refusal(role: str, story: StoryState | None) -> str | None:
    """Why ``role`` may not run on ``story`` now, or ``None``."""
    if role in UNGATED_ROLES:
        return None
    if story is None:
        return None if role in STORYLESS_ROLES else f"{role} only runs on a story; open_story"
    return _story_checks(story) or _step_refusal(role, story)


def _story_checks(story: StoryState) -> str | None:
    return _repeat_refusal(story) or _status_refusal(story) or _backlog_refusal(story)


def fix_refusal(role: str, story: StoryState | None) -> str | None:
    """Why ``role`` may not run the story's next gate fix, or ``None``."""
    if story is None:
        return FIX_NEEDS_STORY
    if refusal := _story_checks(story):
        return refusal
    if not story.fixes:
        return FIX_NONE.format(id=story.id)
    head = story.fixes[0].role
    return None if role == head else FIX_ROLE.format(id=story.id, role=head)


REPEAT_REFUSAL = "story {id} repeated a setback ({key}); the manager rules on it first"


def _repeat_refusal(story: StoryState) -> str | None:
    if story.repeated is None:
        return None
    return REPEAT_REFUSAL.format(id=story.id, key=loops.trail(story)[-1].key)


def _status_refusal(story: StoryState) -> str | None:
    reasons = {
        StoryStatus.DONE: "is done",
        StoryStatus.CANCELLED: "was cancelled by the human",
        StoryStatus.BLOCKED: "is blocked waiting on an escalation",
        StoryStatus.NEEDS_MANAGER: "hit the round cap; run the manager for a ruling first",
    }
    reason = reasons.get(story.status)
    return f"story {story.id} {reason}" if reason else None


def _backlog_refusal(story: StoryState) -> str | None:
    if story.sprint is not None:
        return None
    return f"story {story.id} is in the backlog; add it to a sprint"


def _step_refusal(role: str, story: StoryState) -> str | None:
    if role_fits_step(role, story.step):
        return None
    return f"story {story.id} is at step {story.step!r}, which needs {STEP_ROLES[story.step]}"


TESTS_FAIL = "tests fail:\n{tail}"
TEST_FAILURES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b[1-9]\d* (?:failed|errors?)\b"),  # pytest/cargo/jest summaries
    re.compile(r"^--- FAIL:", re.MULTILINE),  # go test
)


def tests_failed(output: str) -> bool:
    """Whether the output names a failing or erroring test (``TEST_FAILURES``)."""
    return any(p.search(output) for p in TEST_FAILURES)


def parse_coverage(output: str) -> float | None:
    """Total coverage from a coverage report: the ``TOTAL`` line, else the last ``N%``."""
    totals = [ln for ln in output.splitlines() if "TOTAL" in ln.upper()]
    for text in (*reversed(totals), output):
        found = _PERCENT.findall(text)
        if found:
            return float(found[-1])
    return None


def load_baseline(repo: Path) -> dict[str, float]:
    path = repo / BASELINE
    return json.loads(system.read_text(path)) if system.is_file(path) else {}


def _always_presented(_story: StoryState) -> str | None:
    return None


READY = "presentation ready"


def _always_live(_story: StoryState) -> Outcome:
    return Outcome(Verdict.PASS, READY)


def _no_design_file(_story: str) -> str:
    return ""


def _no_environments(_story: str) -> list[str]:
    return []


def _no_suite_runs(_story: str) -> suite_runs.Wanted:
    return suite_runs.Wanted()


def _clean_spec(_story: str) -> story_spec.Read:
    return story_spec.Read()


def _passed() -> Outcome:
    return Outcome(Verdict.PASS)


def _nothing_kept() -> Outcome | None:
    return None


@dataclass
class Checks:
    """Command-backed gates for one repo."""

    commands: dict[str, str]
    threshold: float
    run: CommandRunner
    baseline_coverage: float | None = None
    presentation: Callable[[StoryState], str | None] = _always_presented
    liveness: Callable[[StoryState], Outcome] = _always_live
    read: Callable[[str], str | None] = _unread
    stages: stages.Opener = stages.unlogged
    suite_runs: Callable[[str], suite_runs.Wanted] = _no_suite_runs
    story_spec: Callable[[str], story_spec.Read] = _clean_spec
    environments: Callable[[str], list[str]] = _no_environments
    reuse: Callable[[], Outcome | None] = _nothing_kept
    design_file: Callable[[str], str] = _no_design_file
    reporting: test_reports.Reporting = field(default_factory=test_reports.Reporting)
    serving: Serving = Serving()

    def redesigned(self, story: StoryState) -> Outcome:
        """Pass when the design of a reverted story has its After revert section (R9)."""
        file, count = self.design_file(story.id), len(story.reverted)
        if revert_log.after_heading(self.read(file) or "", count):
            return Outcome(Verdict.PASS)
        reason = REDESIGN_MISSING.format(id=story.id, count=count, file=file)
        return Outcome(Verdict.BOUNCE, reason, "design", author=Author.ROLE)

    def presented(self, story: StoryState) -> Outcome:
        """Bounce on missing files; otherwise the liveness check decides."""
        with self.stages(stages.Name.PRESENTATION_TRIAL):
            reason = self.presentation(story)
            if reason is None:
                return self.liveness(story)
            return Outcome(Verdict.BOUNCE, reason)

    def tracked(self, file: str) -> str | None:
        """The one tracked repo-relative path for a test file id, if any."""
        suffix = shlex.quote("*/" + file)
        code, out = self.run(LS_FILES_COMMAND.format(path=shlex.quote(file), suffix=suffix))
        return pick_tracked(file, out) if code == 0 else None

    def landed(self, sha: str) -> bool:
        """Whether the commit is an ancestor of HEAD."""
        return self.run(ANCESTOR_COMMAND.format(sha=shlex.quote(sha)))[0] == 0

    def code_in(self, story: StoryState) -> bool:
        """The story's code is in: implement passed, or a developer commit is in the branch."""
        return story.implemented > 0 or any(map(self.landed, story.code_commits))

    def code_facts(self, story: StoryState) -> dict[str, Any]:
        """What the Manager is told about the story's code."""
        shas = [s for s in story.code_commits if self.landed(s)]
        code_in = story.implemented > 0 or shas != []
        return {"implemented": story.implemented, "code_commits": shas, "code_in": code_in}

    def test_output(self, test: str) -> str:
        """The test command's output as shown to the dispute's readers."""
        with self.stages(stages.Name.GATE_DISPUTE):
            run = self._test_run("test")
        if run.code == 0:
            return TEST_GREEN.format(test=test)
        name = test_name(test)
        found = excerpt(run.out, name)
        return found or TEST_NOT_IN_OUTPUT.format(name=name, tail=tail(run.out))

    def content_hash(self, path: str) -> str | None:
        """The fingerprint of the working-tree file, or None when unreadable."""
        text = self.read(path)
        return None if text is None else fingerprint.of(path, text)

    def dispute_settled(self, dispute: OpenDispute) -> Outcome:
        """Pass when confirmed, legacy, or the test file's content changed since the raise."""
        if dispute.stage is DisputeStage.CONFIRMED:
            return Outcome(Verdict.PASS, "dispute confirmed")
        if not dispute.baseline:
            return Outcome(Verdict.PASS, LEGACY_PASS)
        if self.content_hash(dispute.file) != dispute.baseline:
            return Outcome(Verdict.PASS, "disputed test changed")
        return Outcome(Verdict.BOUNCE, _unchanged(dispute), "tests")

    def required_coverage(self) -> float:
        """Threshold, or the recorded baseline when old debt keeps the total below it."""
        if self.baseline_coverage is None:
            return self.threshold
        return min(self.threshold, self.baseline_coverage)

    def ran(self, name: str) -> Ran:
        """Run toolchain command ``name``; keep its exit code and output tail (Q1, Q2)."""
        with self.stages(stages.QUALITY[name]):
            if name in TEST_COMMANDS:
                run = self._test_run(name)
                return _ran(name, run.code, run.out)
            return _ran(name, *self.run(self.commands[name]))

    def _test_run(self, name: str) -> TestRun:
        """Run the ``test`` or ``coverage`` command; with reporting on, skip others' pending ids."""
        if not self.reporting.options.on:
            code, out = self.run(self.commands[name])
            return TestRun(code, out, None, {})
        registry = self.reporting.registry()
        ask = test_reports.Ask(self.reporting, registry.others(self.serving.story))
        built = test_reports.build(self.commands[name], ask)
        return replace(test_reports.run(built, self.run), own=registry.of(self.serving.story))

    def listing(self) -> str:
        """Every tracked path, or ``""`` when git fails."""
        code, out = self.run(LS_ALL_COMMAND)
        return out if code == 0 else ""

    def lint_outputs(self) -> list[str]:
        """Output of each configured lint/static command that failed (not timed out)."""
        configured = [self.commands[n] for n in ROUTED_COMMANDS if n in self.commands]
        with self.stages(stages.Name.GATE_ROUTE_LINT):
            ran = [self.run(command) for command in configured]
        return [out for code, out in ran if code not in (0, TIMED_OUT)]

    def tests_red(self) -> Outcome:
        """The tests gate: the new tests must fail."""
        with self.stages(stages.Name.GATE_TESTS_RED):
            return self._red()

    def _red(self) -> Outcome:
        run = self._test_run("test")
        return self._finished(self._red_outcome(run), run, "test")

    def _finished(self, outcome: Outcome, run: TestRun, name: str) -> Outcome:
        """``outcome`` with the run it was judged on, its report and the skipped-ids note."""
        noted = _noted(outcome, run)
        return replace(noted, ran=_ran(name, run.code, run.out), report=run.report)

    def _red_outcome(self, run: TestRun) -> Outcome:
        if timeout := timed_out(run.code, run.out):
            return timeout
        if self.reporting.options.on:
            return self._reported_red(run)
        return _red_by_exit(run.code)

    def _reported_red(self, run: TestRun) -> Outcome:
        """The red run judged from its report: new failing ids become pending (P8)."""
        if run.report is None:
            folder = self.reporting.folder
            reason = REPORT_MISSING.format(folder=folder, tail=tail(run.out))
            return Outcome(Verdict.BOUNCE, reason, "tests")
        ask = RedAsk(self.reporting.changed(self.serving.base), run.own)
        split = pending_tests.split_red(run.report, ask)
        if split.real:
            ids = ", ".join(sorted(split.real))
            return Outcome(Verdict.BOUNCE, NOT_PENDING.format(ids=ids, tail=tail(run.out)), "tests")
        return self._pending_or_green(run, split.pending)

    def _pending_or_green(self, run: TestRun, pending: tuple[str, ...]) -> Outcome:
        story = self.serving.story
        if pending:
            reason = PENDING_SET.format(count=len(pending), story=story)
            return Outcome(Verdict.PASS, reason, pending=PendingSet(story, tuple(sorted(pending))))
        if run.code != 0:
            reason = UNREPORTED_FAILURE.format(code=run.code, tail=tail(run.out))
            return Outcome(Verdict.BOUNCE, reason, "tests")
        return Outcome(Verdict.BOUNCE, GREEN_TOO_EARLY)

    def tests_reworked(self, claim: TestClaim | None) -> Outcome:
        """Red passes; green passes only with a tests claim (code from an earlier pass)."""
        with self.stages(stages.Name.GATE_TESTS_REWORK):
            red = self._red()
        if not red.reason.startswith(GREEN_TOO_EARLY):
            return red
        if claim is None:
            return _with_ran(Outcome(Verdict.BOUNCE, REWORK_UNCLAIMED), red.ran)
        passed = Outcome(Verdict.PASS, REWORK_PASS.format(claim=claim))
        cleared = replace(passed, pending=PendingSet(self.serving.story, ()), report=red.report)
        return _with_ran(cleared, red.ran)

    def green(self) -> Outcome:
        """Pass when the test command exits 0, else bounce with its output tail."""
        with self.stages(stages.Name.GATE_GREEN):
            run = self._test_run("test")
        if timeout := timed_out(run.code, run.out):
            return timeout
        if run.code != 0:
            return _noted(Outcome(Verdict.BOUNCE, TESTS_FAIL.format(tail=tail(run.out))), run)
        return _noted(Outcome(Verdict.PASS), run)

    def tests_green_and_covered(self) -> Outcome:
        """One coverage run proves green and gives the total (s68 C1-C5)."""
        kept = self.reuse()
        if kept is not None:
            return kept
        with self.stages(stages.Name.GATE_TESTS_COVERAGE):
            run = self._test_run("coverage")
        covered = self._finished(self._covered_outcome(run.code, run.out), run, "coverage")
        covered = covered if run.code == TIMED_OUT else replace(covered, output=run.out)
        return self._leaving(covered, run)

    def _leaving(self, outcome: Outcome, run: TestRun) -> Outcome:
        """The story's own pending ids must all pass for the gate to pass (P12)."""
        if not run.own or not self.reporting.options.on:
            return outcome
        if run.report is None:
            return _report_missing(outcome, self.reporting.folder, run)
        left = pending_tests.leaving(run.report, run.own)
        if left.failing:
            return self._still_failing(outcome, left)
        return self._cleared(outcome, run.own, left)

    def _still_failing(self, outcome: Outcome, left: pending_tests.Leaving) -> Outcome:
        text = PENDING_FAIL.format(story=self.serving.story, ids=", ".join(sorted(left.failing)))
        bounced = outcome.verdict is not Verdict.PASS
        reason = f"{outcome.reason}\n{text}" if bounced else text
        return replace(outcome, verdict=Verdict.BOUNCE, reason=reason, pending=None)

    def _cleared(
        self, outcome: Outcome, own: tuple[str, ...], left: pending_tests.Leaving
    ) -> Outcome:
        if outcome.verdict is not Verdict.PASS:
            return outcome
        story = self.serving.story
        notes = [PENDING_LEFT.format(count=len(own) - len(left.missing), story=story)]
        if left.missing:
            notes.append(PENDING_GONE.format(ids=", ".join(sorted(left.missing))))
        reason = "; ".join(filter(None, [outcome.reason, *notes]))
        return replace(outcome, reason=reason, pending=PendingSet(story, ()))

    def _covered_outcome(self, code: int, out: str) -> Outcome:
        if timeout := timed_out(code, out):
            return timeout
        if code == 0:
            return self._coverage_outcome(parse_coverage(out))
        return self._failed_run(out)

    def _failed_run(self, out: str) -> Outcome:
        """Bounce a non-zero run: shortfall text if only the total fell short, else tests fail."""
        pct = parse_coverage(out)
        short = pct is not None and pct < self.required_coverage()
        if short and not tests_failed(out):
            return self._coverage_outcome(pct)
        return Outcome(Verdict.BOUNCE, TESTS_FAIL.format(tail=tail(out)))

    def _coverage_outcome(self, pct: float | None) -> Outcome:
        if pct is None:
            return Outcome(Verdict.BOUNCE, "could not read a coverage total")
        if pct < self.required_coverage():
            return Outcome(Verdict.BOUNCE, f"coverage {pct}% is below {self.required_coverage()}%")
        return Outcome(Verdict.PASS, f"coverage {pct}%")

    def after_suite_runs(self, story: str, first: Outcome) -> Outcome:
        """Run the test command the story's ``suite_runs`` times after a passing gate."""
        if first.verdict is not Verdict.PASS:
            return first
        wanted = self.suite_runs(story)
        if wanted.refusal:
            return Outcome(Verdict.HOLD, wanted.refusal, ran=first.ran)
        if not wanted.count:
            return first
        with self.stages(stages.Name.GATE_SUITE_RUNS):
            return _suite_outcome(first, self._run_suite(wanted.count))

    def _run_suite(self, total: int) -> list[suite_runs.SuiteRun]:
        """Run the test command up to ``total`` times, stopping after a failure."""
        runs: list[suite_runs.SuiteRun] = []
        for n in range(1, total + 1):
            start = system.monotonic()
            run = self._test_run("test")
            took = system.monotonic() - start
            runs.append(suite_runs.SuiteRun(n, total, run.code, took, run.out))
            if run.code != 0:
                break
        return runs


def _suite_outcome(first: Outcome, runs: list[suite_runs.SuiteRun]) -> Outcome:
    """The gate's outcome after the suite runs (SR3, SR4)."""
    last = runs[-1]
    ran = Ran(suite_runs.SUITE_RUNS, last.code, suite_runs.report(runs))
    extra = (*first.extra_ran, ran)
    if last.code == 0:
        text = suite_runs.passed_text(runs)
        reason = f"{first.reason}; {text}" if first.reason else text
        return replace(first, reason=reason, extra_ran=extra)
    bounce = timed_out(last.code, last.out) or Outcome(
        Verdict.BOUNCE,
        suite_runs.SUITE_FAILED.format(n=last.n, total=last.total, tail=tail(last.out)),
        output=last.out,
    )
    return replace(bounce, ran=first.ran, extra_ran=extra)


def _red_by_exit(code: int) -> Outcome:
    """The red run judged by its exit code alone (reporting off)."""
    if code != 0:
        return Outcome(Verdict.PASS)
    return Outcome(Verdict.BOUNCE, GREEN_TOO_EARLY)


def _report_missing(outcome: Outcome, folder: Path, run: TestRun) -> Outcome:
    """A passing run that wrote no report bounces; a failing one keeps its own reason."""
    if outcome.verdict is not Verdict.PASS:
        return outcome
    reason = REPORT_MISSING.format(folder=folder, tail=tail(run.out))
    return replace(outcome, verdict=Verdict.BOUNCE, reason=reason, pending=None)


def _noted(outcome: Outcome, run: TestRun) -> Outcome:
    """Add the count of pending ids the run skipped to the reason (P17)."""
    counts = pending_tests.counts_text(run.skipped, run.report or junit.Report())
    if not counts:
        return outcome
    reason = "; ".join(filter(None, [outcome.reason, SKIPPED_NOTE.format(counts=counts)]))
    return replace(outcome, reason=reason)


def _ran(name: str, code: int, out: str) -> Ran:
    return Ran(name, code, result_tail(out))


def _with_ran(outcome: Outcome, ran: Ran | None) -> Outcome:
    """``outcome`` carrying the run it was judged on (B1)."""
    return replace(outcome, ran=ran)


@dataclass
class Pipeline:
    """The enabled steps, the round cap and the command gates for one run."""

    steps: list[str]
    cap: int
    checks: Checks
    repeat: int = 2
    backstop: int = 4

    def first(self) -> str:
        return self.steps[0]

    def step_for_role(self, role: str | None) -> str | None:
        """The first enabled step ``role`` owns."""
        return next((s for s in self.steps if role and role_fits_step(role, s)), None)

    def serving(self, serving: Serving) -> Pipeline:
        """A copy whose command gates run for ``serving`` (P16)."""
        return replace(self, checks=replace(self.checks, serving=serving))

    def evaluate(self, story: StoryState, handoff: Handoff) -> Outcome:
        """Gate result for the step a role just finished on ``story``."""
        try:
            return self._evaluate(story, handoff)
        except RegistryError as error:
            reason = REGISTRY_BAD.format(file=pending_tests.REGISTRY, error=error)
            return Outcome(Verdict.HOLD, reason)

    def _evaluate(self, story: StoryState, handoff: Handoff) -> Outcome:
        if handoff.status in STOPPED_HANDOFFS:
            reason = f"role reported {handoff.status}: {handoff.summary}"
            return Outcome(Verdict.HOLD, reason, author=Author.ROLE)
        if self._raises_dispute(story, handoff):
            return self._raise(handoff)
        gate = self._gate_for(story, handoff)
        return _retry_here(gate(), story.step) if gate else self._verdict(story, handoff)

    def _gate_for(self, story: StoryState, handoff: Handoff) -> Callable[[], Outcome] | None:
        gate = self.step_gate(story, handoff)
        return self._suite_gate(story, gate) if self._suite_due(story, handoff) else gate

    def _suite_due(self, story: StoryState, handoff: Handoff) -> bool:
        return handoff.status == "done" and story.step == suite_runs.suite_step(self.steps)

    def _suite_gate(
        self, story: StoryState, gate: Callable[[], Outcome] | None
    ) -> Callable[[], Outcome]:
        return lambda: self.checks.after_suite_runs(story.id, (gate or _passed)())

    def step_gate(self, story: StoryState, handoff: Handoff) -> Callable[[], Outcome] | None:
        """The gate a `done` at the story's step runs, or None."""
        if story.step == "tests" and story.dispute:
            return self._dispute_gate(story, handoff)
        if self.reworked(story):
            return self._rework_gate(handoff)
        return (
            self._command_gate(story.step)
            or self._done_gate(story, handoff)
            or self._redesign_gate(story, handoff)
        )

    def reworked(self, story: StoryState) -> bool:
        """A story back at tests with its code already in and no dispute open."""
        return story.step == "tests" and story.dispute is None and self.checks.code_in(story)

    def _raises_dispute(self, story: StoryState, handoff: Handoff) -> bool:
        return bool(handoff.dispute) and story.step == "implement" and "tests" in self.steps

    def _raise(self, handoff: Handoff) -> Outcome:
        d = handoff.dispute
        opened = self._open(d)
        if opened is None:
            reason = UNTRACKED.format(file=test_file(d.test), test=d.test)
            return Outcome(Verdict.BOUNCE, reason, "implement", author=Author.ROLE)
        reason = f"{d.test} contradicts {d.rule}: {d.reason}"
        return Outcome(Verdict.DISPUTE, reason, "tests", opened, Author.ROLE)

    def _open(self, d: Dispute) -> OpenDispute | None:
        path = self.checks.tracked(test_file(d.test))
        baseline = self.checks.content_hash(path) if path else None
        if not baseline:
            return None
        output = self.checks.test_output(d.test)
        return OpenDispute(d.test, d.rule, d.reason, path, baseline, output=output)

    def _dispute_gate(self, story: StoryState, handoff: Handoff) -> Callable[[], Outcome] | None:
        """With a dispute open, a ``done`` at tests is settled by the dispute, not red tests."""
        if handoff.status != "done":
            return None
        return lambda: self.checks.dispute_settled(story.dispute)

    def _rework_gate(self, handoff: Handoff) -> Callable[[], Outcome] | None:
        """On a reworked story a ``done`` at tests may be green if the tester says why."""
        if handoff.status != "done":
            return None
        return lambda: self.checks.tests_reworked(handoff.tests)

    def _verdict(self, story: StoryState, handoff: Handoff) -> Outcome:
        if story.step == "acceptance" and self.checks.environments(story.id):
            return self._tried(story, handoff)
        return self._handoff_outcome(handoff)

    def _tried(self, story: StoryState, handoff: Handoff) -> Outcome:
        """One Proxy step's verdict for the due environment (s95)."""
        round_ = acceptance.Round(tuple(self.checks.environments(story.id)), tuple(story.tried))
        environment = round_.due() or ""
        text = self.checks.read(acceptance.report_file(story.id))
        if not acceptance.has_section(text, environment):
            reason = acceptance.NO_SECTION.format(
                file=acceptance.report_file(story.id), environment=environment
            )
            return Outcome(Verdict.BOUNCE, reason, "acceptance", author=Author.ROLE)
        new = acceptance.tried_of(environment, handoff)
        round_ = round_.with_try(new)
        story.tried = list(round_.tried)
        return self._round_outcome(round_, new)

    def _round_outcome(self, round_: acceptance.Round, new: acceptance.Tried) -> Outcome:
        outcomes = {
            acceptance.Decision.NEXT: lambda: Outcome(
                Verdict.NEXT, round_.next_text(new), author=Author.ROLE
            ),
            acceptance.Decision.PASS: lambda: Outcome(Verdict.PASS, round_.passed_text()),
            acceptance.Decision.FAIL: lambda: Outcome(
                Verdict.BOUNCE,
                round_.failed_text(),
                self._earliest(round_.failures()),
                author=Author.ROLE,
            ),
        }
        return replace(outcomes[round_.decision()](), tried=new)

    def _earliest(self, tries: list[acceptance.Tried]) -> str:
        targets = [self.step_for_role(t.next_role) or "implement" for t in tries]
        return min(targets, key=self.steps.index)

    def _handoff_outcome(self, handoff: Handoff) -> Outcome:
        """Pass on ``done``; otherwise bounce to the step of the role it names."""
        if handoff.status == "done":
            return Outcome(Verdict.PASS)
        target = self.step_for_role(handoff.next_role) or "implement"
        reason = handoff.summary or "changes requested"
        return Outcome(Verdict.BOUNCE, reason, target, author=Author.ROLE)

    def _command_gate(self, step: str) -> Callable[[], Outcome] | None:
        gates = {"tests": self.checks.tests_red, "implement": self.checks.tests_green_and_covered}
        return gates.get(step)

    def _done_gate(self, story: StoryState, handoff: Handoff) -> Callable[[], Outcome] | None:
        """The e2e presentation check, which applies only to a ``done`` handoff."""
        applies = story.step == "e2e" and handoff.status == "done" and "acceptance" in self.steps
        return (lambda: self.checks.presented(story)) if applies else None

    def _redesign_gate(self, story: StoryState, handoff: Handoff) -> Callable[[], Outcome] | None:
        """The After revert check for a ``done`` design of a reverted story."""
        applies = story.step == "design" and handoff.status == "done" and story.reverted
        return (lambda: self.checks.redesigned(story)) if applies else None

    def unpresented(self, story: StoryState) -> Outcome | None:
        """A return to e2e when the Proxy would start without a presentation."""
        reason = self.checks.presentation(story)
        return self.return_to_e2e(reason) if reason else None

    def unready(self, story: StoryState) -> Outcome | None:
        """A hold when the story file has problems (s94 SF7), else ``None``."""
        refusal = self.checks.story_spec(story.id).refusal()
        if refusal is None:
            return None
        return Outcome(Verdict.HOLD, story_spec.STORY_FILE_HOLD.format(refusal=refusal))

    def return_to_e2e(self, reason: str) -> Outcome | None:
        """A no-round return to e2e, or ``None`` when the pipeline has no e2e step."""
        if "e2e" not in self.steps:
            return None
        return Outcome(Verdict.RETURN, f"{reason}; run the integration-tester on it", "e2e")

    def route(self, outcome: Outcome, owners: Owners) -> Outcome:
        """Queue gate fixes for items in files other roles own (R1, s92)."""
        if outcome.verdict is Verdict.DISPUTE:
            return self._route_dispute(outcome, owners)
        return self._route_items(outcome, owners) if _routable(outcome) else outcome

    def _route_items(self, outcome: Outcome, owners: Owners) -> Outcome:
        found = [*test_findings(outcome), *self._lint_findings()]
        items = owners_mod.placed(found, self.checks.listing())
        return _routed(outcome, owners_mod.split(items, owners))

    def _lint_findings(self) -> list[owners_mod.Finding]:
        outputs = self.checks.lint_outputs()
        return [f for out in outputs for f in owners_mod.findings(out, Source.LINT)]

    def _route_dispute(self, outcome: Outcome, owners: Owners) -> Outcome:
        d = outcome.dispute
        item = Item(d.test, Source.TEST, [d.file], d.output.splitlines()[: owners_mod.ITEM_LINES])
        writer = owners.fixer(item)
        if writer is None:
            return outcome
        fix = Fix(writer.role, [item], d.rule, d.reason)
        return Outcome(Verdict.ROUTE, outcome.reason, author=Author.ROLE, fixes=[fix])

    def advance(self, story: StoryState, outcome: Outcome) -> None:
        """Move ``story`` forward on a pass, back (counting a round) on a bounce."""
        moves = {
            Verdict.PASS: lambda: self._forward(story),
            Verdict.BOUNCE: lambda: self._bounce(story, outcome.bounce_to),
            Verdict.RETURN: lambda: self._return(story, outcome.bounce_to),
            Verdict.DISPUTE: lambda: self._dispute(story, outcome),
            Verdict.ESCALATE: lambda: self._escalate(story, outcome),
        }
        if outcome.verdict in moves:
            moves[outcome.verdict]()
        if story.step == "implement":
            story.dispute = None
        story.fixes = list(outcome.fixes)

    def screen(self, story: StoryState, setback: Setback) -> Outcome | None:
        """An escalation when ``setback`` repeats the last one or ends a back-and-forth."""
        return self._repeat(story, setback) or self._backstop(story, setback)

    def _repeat(self, story: StoryState, setback: Setback) -> Outcome | None:
        if loops.repeats(story.streak, setback) + 1 < self.repeat:
            return None
        return Outcome(Verdict.ESCALATE, setback.reason, setback.step, author=setback.author)

    def _backstop(self, story: StoryState, setback: Setback) -> Outcome | None:
        if loops.bounces(story.run, setback) + 1 < self.backstop:
            return None
        reason = loops.backstop_reason([*story.run, setback])
        return Outcome(Verdict.ESCALATE, reason, setback.step, None, setback.author, Rule.BACKSTOP)

    def _escalate(self, story: StoryState, outcome: Outcome) -> None:
        story.status = StoryStatus.NEEDS_MANAGER
        story.repeated = outcome.reason
        story.escalated_by = outcome.rule

    def fault_kind(self, fault: str) -> Fault:
        """Where the Manager put the blame: the runner, a pipeline role or any other role."""
        if fault == "runner":
            return Fault.RUNNER
        return Fault.PIPELINE if self.step_for_role(fault) else Fault.OFF_PIPELINE

    def apply_fault(self, story: StoryState, fault: str) -> None:
        """Send the story to the role at fault (or block it for the runner) and clear its loop."""
        story.step = self.step_for_role(fault) or story.step
        story.status = FAULT_STATUS[self.fault_kind(fault)]
        story.hold = None
        self._clear(story)

    def pass_tests_refusal(self, story: StoryState) -> str | None:
        """Why the PO may not pass ``story`` from tests by hand, or None."""
        if story.step != "tests":
            return PASS_TESTS_STEP.format(id=story.id, step=story.step)
        if not _stuck(story):
            return PASS_TESTS_NOT_STUCK.format(id=story.id)
        green = self.checks.green()
        if green.verdict is not Verdict.PASS:
            return PASS_TESTS_RED.format(reason=green.reason)
        return None

    def pass_tests(self, story: StoryState) -> None:
        """Move a stuck story on from tests, clearing its loop state."""
        story.status = StoryStatus.ACTIVE
        self._clear(story)
        self._forward(story)

    def _clear(self, story: StoryState) -> None:
        story.rounds, story.disputes, story.dispute = 0, 0, None
        story.streak, story.run = [], []
        story.repeated, story.escalated_by = None, None
        story.fixes = []

    def _dispute(self, story: StoryState, outcome: Outcome) -> None:
        story.dispute = outcome.dispute
        story.disputes += 1
        if story.disputes <= self.cap:
            story.step = "tests"
        else:
            self._bounce(story, "tests")

    def _return(self, story: StoryState, target: str | None) -> None:
        story.step = target or story.step

    def _forward(self, story: StoryState) -> None:
        i = self.steps.index(story.step)
        story.implemented += story.step == "implement"
        if i + 1 == len(self.steps):
            story.status = StoryStatus.DONE
        else:
            story.step = self.steps[i + 1]
        if story.step == "acceptance":
            story.tried = []

    def _bounce(self, story: StoryState, target: str | None) -> None:
        if story.dispute and story.step == "tests" and target != "tests":
            story.dispute.stage = DisputeStage.CONFIRMED
        story.step = target or story.step
        story.rounds += 1
        if story.rounds >= self.cap:
            story.status = StoryStatus.NEEDS_MANAGER

    def apply_ruling(self, story: StoryState, ruling: str) -> None:
        """Apply the Manager's ruling to a story and reset its round count."""
        self._clear(story)
        escalated = ruling == "escalate"
        story.status = StoryStatus.BLOCKED if escalated else StoryStatus.ACTIVE
        self._move_for(story, ruling)

    def _move_for(self, story: StoryState, ruling: str) -> None:
        design = "design" if "design" in self.steps else self.first()
        moves = {
            "rescope": lambda: setattr(story, "step", self.first()),
            "revise_design": lambda: setattr(story, "step", design),
            "advance": lambda: self._forward(story),
        }
        moves.get(ruling, lambda: None)()

    def ruling_move_refusal(self, story: StoryState, ruling: str) -> str | None:
        """Why the ruling's move cannot be made, or ``None``."""
        if ruling == "advance" and story.step == self.steps[-1]:
            return ADVANCE_LAST.format(id=story.id, step=story.step)
        return None


FAULT_STATUS = {
    Fault.RUNNER: StoryStatus.BLOCKED,
    Fault.PIPELINE: StoryStatus.ACTIVE,
    Fault.OFF_PIPELINE: StoryStatus.ACTIVE,
}


def _unchanged(dispute: OpenDispute) -> str:
    short = dispute.baseline[:12]
    return UNCHANGED.format(test=dispute.test, file=dispute.file, short=short)


STUCK_STATUSES = frozenset({StoryStatus.NEEDS_MANAGER, StoryStatus.BLOCKED})


def _stuck(story: StoryState) -> bool:
    return bool(story.dispute or story.status in STUCK_STATUSES or story.repeated)


def _owners_text(fixes: list[Fix]) -> str:
    return "; ".join(f"{f.role} ({', '.join(i.shown for i in f.items)})" for f in fixes)


def _routed(base: Outcome, split: Split) -> Outcome:
    """``base`` with the split's fixes: ROUTE, or BOUNCE for own failing tests (R9, R10)."""
    if not split.fixes:
        return base
    text = _owners_text(split.fixes)
    own_tests = any(i.source is Source.TEST for i in split.own)
    if base.verdict is Verdict.BOUNCE and (own_tests or not split.tested):
        reason = f"{base.reason}\n{ALSO_ROUTED.format(owners=text)}"
        return replace(base, reason=reason, fixes=split.fixes)
    return replace(
        base, verdict=Verdict.ROUTE, reason=ROUTED.format(owners=text), fixes=split.fixes
    )


def _retry_here(outcome: Outcome, step: str) -> Outcome:
    if outcome.verdict is Verdict.BOUNCE:
        outcome.bounce_to = step
    return outcome


def _routable(outcome: Outcome) -> bool:
    """Whether the outcome's test failures are worth routing to their owners."""
    return bool(outcome.output) or (
        outcome.report is not None and outcome.verdict is Verdict.BOUNCE
    )


def test_findings(outcome: Outcome) -> list[owners_mod.Finding]:
    """Failing tests: from the report when the run wrote one, else from the text output."""
    if outcome.report is None:
        return owners_mod.findings(outcome.output, Source.TEST)
    return [
        owners_mod.Finding(c.file, (f"FAILED {c.id} - {c.message}",), Source.TEST)
        for c in outcome.report.failed()
    ]


def test_name(test: str) -> str:
    """The part of a test id after the last ``::``."""
    return test.rsplit("::", 1)[-1]


def excerpt(output: str, name: str) -> str | None:
    """Output from the first line naming the test, plus later lines that name it."""
    lines = output.splitlines()
    first = next((i for i, line in enumerate(lines) if name in line), None)
    if first is None:
        return None
    head = lines[first : first + EXCERPT_LINES]
    later = [x for x in lines[first + EXCERPT_LINES :] if name in x]
    return "\n".join(head + later)


def tail(text: str) -> str:
    return "\n".join(text.splitlines()[-30:])


def timed_out(code: int, output: str) -> Outcome | None:
    """Bounce with the output tail when the command was killed at its limit."""
    if code != TIMED_OUT:
        return None
    return Outcome(Verdict.BOUNCE, TIMED_OUT_BOUNCE.format(tail=tail(output)))
