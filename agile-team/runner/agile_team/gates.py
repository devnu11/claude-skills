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
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import fingerprint, loops
from .loops import Author, Fault, Rule, Setback
from .roles import Dispute, Handoff, TestClaim
from .salvage import Interruption

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
UNGATED_ROLES = frozenset({"manager", "scribe"})
STORYLESS_ROLES = frozenset({"architect", "devops", "unit-tester", "manager", "scribe"})
STOPPED_HANDOFFS = frozenset({"blocked", "failed"})
BASELINE = ".team/baseline.json"
LS_FILES_COMMAND = "git ls-files -- {path} {suffix}"
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
    "the disputed test {test} is unchanged: {file} still matches its baseline "
    "{short} from when the dispute was raised (whitespace and comment edits do "
    "not count); fix the test, or confirm it with changes_requested and "
    "next_role architect"
)
LEGACY_PASS = "dispute raised before content baselines; passed without a check"
PASS_TESTS_STEP = "story {id} is at step {step!r}; pass_tests only moves a story from tests"
PASS_TESTS_NOT_STUCK = (
    "story {id} is not stuck at tests (no open dispute, round cap, block or "
    "repeated setback); let the tests gate decide"
)
PASS_TESTS_RED = "the suite is red; pass_tests needs a green suite. {reason}"

CommandRunner = Callable[[str], tuple[int, str]]


class StoryStatus(StrEnum):
    """Where a story stands, beyond its pipeline step."""

    ACTIVE = "active"
    NEEDS_MANAGER = "needs_manager"
    BLOCKED = "blocked"
    DONE = "done"


class Verdict(StrEnum):
    """A gate's result.

    ``HOLD`` stays put without counting a round (a block). ``RETURN`` moves back
    without counting a round (the team, not the product, missed a step).
    ``ESCALATE`` stays put, counts no round and waits for the Manager's ruling.
    """

    PASS = "pass"
    BOUNCE = "bounce"
    HOLD = "hold"
    RETURN = "return"
    DISPUTE = "dispute"
    ESCALATE = "escalate"


class DisputeStage(StrEnum):
    """How far a test dispute has got: raised by the developer, or upheld by the unit-tester."""

    RAISED = "raised"
    CONFIRMED = "confirmed"


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
    lines = listing.splitlines()
    if file in lines:
        return file
    ends = [x for x in lines if x.endswith("/" + file)]
    return ends[0] if len(ends) == 1 else None


def read_repo_file(repo: Path, path: str) -> str | None:
    """The text of ``path`` under ``repo``, or None when it is not a file."""
    target = repo / path
    if not target.is_file():
        return None
    return target.read_text(encoding="utf-8", errors="replace")


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
    delivery: str | None = None
    sprint: int | None = None
    developer: str | None = None
    po_developer: str | None = None
    hold: str | None = None
    note: str = ""
    previous: PreviousStep | None = None
    dispute: OpenDispute | None = None
    disputes: int = 0
    implemented: int = 0
    streak: list[Setback] = field(default_factory=list)
    repeated: str | None = None
    run: list[Setback] = field(default_factory=list)
    escalated_by: Rule | None = None
    interrupted: Interruption | None = None


@dataclass
class Outcome:
    """Result of a gate and, for a bounce, the step to return to."""

    verdict: Verdict
    reason: str = ""
    bounce_to: str | None = None
    dispute: OpenDispute | None = None
    author: Author = Author.RUNNER
    rule: Rule = Rule.REPEAT


def role_fits_step(role: str, step: str) -> bool:
    """Developer specializations (``developer-cli`` …) all fit the implement step."""
    expected = STEP_ROLES[step]
    return role == expected or (expected == "developer" and role.startswith("developer"))


def ruling_refusal(story: StoryState | None) -> str | None:
    """Why a Manager ruling cannot apply to ``story``, or ``None``."""
    if story is None:
        return "a ruling needs a story; run the manager on that story"
    if story.status is StoryStatus.DONE:
        return f"story {story.id} is done; a ruling cannot move it"
    return None


def dispatch_refusal(role: str, story: StoryState | None) -> str | None:
    """Why ``role`` may not run on ``story`` now, or ``None``."""
    if role in UNGATED_ROLES:
        return None
    if story is None:
        return None if role in STORYLESS_ROLES else f"{role} only runs on a story; open_story"
    return (
        _repeat_refusal(story)
        or _status_refusal(story)
        or _backlog_refusal(story)
        or _step_refusal(role, story)
    )


REPEAT_REFUSAL = "story {id} repeated a setback ({key}); the manager rules on it first"


def _repeat_refusal(story: StoryState) -> str | None:
    if story.repeated is None:
        return None
    return REPEAT_REFUSAL.format(id=story.id, key=loops.trail(story)[-1].key)


def _status_refusal(story: StoryState) -> str | None:
    reasons = {
        StoryStatus.DONE: "is done",
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
    return json.loads(path.read_text()) if path.is_file() else {}


def _always_presented(_story: StoryState) -> str | None:
    return None


READY = "presentation ready"


def _always_live(_story: StoryState) -> Outcome:
    return Outcome(Verdict.PASS, READY)


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

    def presented(self, story: StoryState) -> Outcome:
        """Bounce on missing files; otherwise the liveness check decides."""
        reason = self.presentation(story)
        if reason is None:
            return self.liveness(story)
        return Outcome(Verdict.BOUNCE, reason)

    def tracked(self, file: str) -> str | None:
        """The one tracked repo-relative path for a test file id, if any."""
        suffix = shlex.quote("*/" + file)
        code, out = self.run(LS_FILES_COMMAND.format(path=shlex.quote(file), suffix=suffix))
        return pick_tracked(file, out) if code == 0 else None

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

    def tests_red(self) -> Outcome:
        code, _ = self.run(self.commands["test"])
        if code != 0:
            return Outcome(Verdict.PASS)
        return Outcome(Verdict.BOUNCE, "tests pass before implementation; write a failing test")

    def tests_reworked(self, claim: TestClaim | None) -> Outcome:
        """Red passes; green passes only with a tests claim (code from an earlier pass)."""
        red = self.tests_red()
        if red.verdict is Verdict.PASS:
            return red
        if claim is None:
            return Outcome(Verdict.BOUNCE, REWORK_UNCLAIMED)
        return Outcome(Verdict.PASS, REWORK_PASS.format(claim=claim))

    def green(self) -> Outcome:
        """Pass when the test command exits 0, else bounce with its output tail."""
        code, out = self.run(self.commands["test"])
        if code != 0:
            return Outcome(Verdict.BOUNCE, f"tests fail:\n{tail(out)}")
        return Outcome(Verdict.PASS)

    def tests_green_and_covered(self) -> Outcome:
        green = self.green()
        if green.verdict is not Verdict.PASS:
            return green
        return self._coverage_outcome(parse_coverage(self.run(self.commands["coverage"])[1]))

    def _coverage_outcome(self, pct: float | None) -> Outcome:
        if pct is None:
            return Outcome(Verdict.BOUNCE, "could not read a coverage total")
        if pct < self.required_coverage():
            return Outcome(Verdict.BOUNCE, f"coverage {pct}% is below {self.required_coverage()}%")
        return Outcome(Verdict.PASS, f"coverage {pct}%")


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

    def evaluate(self, story: StoryState, handoff: Handoff) -> Outcome:
        """Gate result for the step a role just finished on ``story``."""
        if handoff.status in STOPPED_HANDOFFS:
            reason = f"role reported {handoff.status}: {handoff.summary}"
            return Outcome(Verdict.HOLD, reason, author=Author.ROLE)
        if self._raises_dispute(story, handoff):
            return self._raise(handoff)
        gate = self._gate_for(story, handoff)
        return _retry_here(gate(), story.step) if gate else self._handoff_outcome(handoff)

    def _gate_for(self, story: StoryState, handoff: Handoff) -> Callable[[], Outcome] | None:
        if story.step == "tests" and story.dispute:
            return self._dispute_gate(story, handoff)
        if story.step == "tests" and story.implemented:
            return self._rework_gate(handoff)
        return self._command_gate(story.step) or self._done_gate(story, handoff)

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
        return OpenDispute(d.test, d.rule, d.reason, path, baseline) if baseline else None

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

    def unpresented(self, story: StoryState) -> Outcome | None:
        """A return to e2e when the Proxy would start without a presentation."""
        reason = self.checks.presentation(story)
        return self.return_to_e2e(reason) if reason else None

    def return_to_e2e(self, reason: str) -> Outcome | None:
        """A no-round return to e2e, or ``None`` when the pipeline has no e2e step."""
        if "e2e" not in self.steps:
            return None
        return Outcome(Verdict.RETURN, f"{reason}; run the integration-tester on it", "e2e")

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

    def _bounce(self, story: StoryState, target: str | None) -> None:
        if story.dispute and story.step == "tests" and target != "tests":
            story.dispute.stage = DisputeStage.CONFIRMED
        story.step = target or story.step
        story.rounds += 1
        if story.rounds >= self.cap:
            story.status = StoryStatus.NEEDS_MANAGER

    def apply_ruling(self, story: StoryState, ruling: str) -> None:
        """Apply the Manager's ruling to a capped story and reset its round count."""
        design = "design" if "design" in self.steps else self.first()
        targets = {"rescope": self.first(), "revise_design": design}
        story.step = targets.get(ruling, story.step)
        self._clear(story)
        escalated = ruling == "escalate"
        story.status = StoryStatus.BLOCKED if escalated else StoryStatus.ACTIVE


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


def _retry_here(outcome: Outcome, step: str) -> Outcome:
    if outcome.verdict is Verdict.BOUNCE:
        outcome.bounce_to = step
    return outcome


def tail(text: str) -> str:
    return "\n".join(text.splitlines()[-30:])
