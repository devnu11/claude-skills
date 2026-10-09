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
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .roles import Dispute, Handoff

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
HEAD_COMMAND = "git rev-parse HEAD"
DIFF_COMMAND = "git diff --quiet {base} HEAD -- {path}"
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)%")

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
    """

    PASS = "pass"
    BOUNCE = "bounce"
    HOLD = "hold"
    RETURN = "return"
    DISPUTE = "dispute"


class DisputeStage(StrEnum):
    """How far a test dispute has got: raised by the developer, or upheld by the unit-tester."""

    RAISED = "raised"
    CONFIRMED = "confirmed"


@dataclass
class OpenDispute:
    """A developer's claim that a test contradicts the design; ``base`` is HEAD when raised."""

    test: str
    rule: str
    reason: str
    base: str
    stage: DisputeStage = DisputeStage.RAISED

    def __post_init__(self) -> None:
        self.stage = DisputeStage(self.stage)

    @property
    def file(self) -> str:
        """The disputed test's file, the part of the id before ``::``."""
        return self.test.split("::")[0]


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


@dataclass
class Outcome:
    """Result of a gate and, for a bounce, the step to return to."""

    verdict: Verdict
    reason: str = ""
    bounce_to: str | None = None
    dispute: OpenDispute | None = None


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
    return _status_refusal(story) or _backlog_refusal(story) or _step_refusal(role, story)


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


@dataclass
class Checks:
    """Command-backed gates for one repo."""

    commands: dict[str, str]
    threshold: float
    run: CommandRunner
    baseline_coverage: float | None = None
    presentation: Callable[[StoryState], str | None] = _always_presented

    def presented(self, story: StoryState) -> Outcome:
        """Pass when the story's presentation is complete, else bounce with why not."""
        reason = self.presentation(story)
        if reason is None:
            return Outcome(Verdict.PASS, "presentation ready")
        return Outcome(Verdict.BOUNCE, reason)

    def head(self) -> str:
        """The current commit."""
        return self.run(HEAD_COMMAND)[1].strip()

    def dispute_settled(self, dispute: OpenDispute) -> Outcome:
        """Pass when the dispute is confirmed or its test file changed since it was raised."""
        if dispute.stage is DisputeStage.CONFIRMED:
            return Outcome(Verdict.PASS, "dispute confirmed")
        diff = DIFF_COMMAND.format(base=dispute.base, path=shlex.quote(dispute.file))
        if self.run(diff)[0] == 1:
            return Outcome(Verdict.PASS, "disputed test changed")
        return Outcome(Verdict.BOUNCE, _unchanged(dispute))

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

    def tests_green_and_covered(self) -> Outcome:
        code, out = self.run(self.commands["test"])
        if code != 0:
            return Outcome(Verdict.BOUNCE, f"tests fail:\n{_tail(out)}")
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

    def first(self) -> str:
        return self.steps[0]

    def step_for_role(self, role: str | None) -> str | None:
        """The first enabled step ``role`` owns."""
        return next((s for s in self.steps if role and role_fits_step(role, s)), None)

    def evaluate(self, story: StoryState, handoff: Handoff) -> Outcome:
        """Gate result for the step a role just finished on ``story``."""
        if handoff.status in STOPPED_HANDOFFS:
            return Outcome(Verdict.HOLD, f"role reported {handoff.status}: {handoff.summary}")
        if self._raises_dispute(story, handoff):
            return self._raise(handoff)
        gate = self._gate_for(story, handoff)
        return _retry_here(gate(), story.step) if gate else self._handoff_outcome(handoff)

    def _gate_for(self, story: StoryState, handoff: Handoff) -> Callable[[], Outcome] | None:
        if story.step == "tests" and story.dispute:
            return self._dispute_gate(story, handoff)
        return self._command_gate(story.step) or self._done_gate(story, handoff)

    def _raises_dispute(self, story: StoryState, handoff: Handoff) -> bool:
        return bool(handoff.dispute) and story.step == "implement" and "tests" in self.steps

    def _raise(self, handoff: Handoff) -> Outcome:
        d = handoff.dispute
        reason = f"{d.test} contradicts {d.rule}: {d.reason}"
        return Outcome(Verdict.DISPUTE, reason, "tests", self._open(d))

    def _open(self, d: Dispute) -> OpenDispute:
        return OpenDispute(d.test, d.rule, d.reason, self.checks.head())

    def _dispute_gate(self, story: StoryState, handoff: Handoff) -> Callable[[], Outcome] | None:
        """With a dispute open, a ``done`` at tests is settled by the dispute, not red tests."""
        if handoff.status != "done":
            return None
        return lambda: self.checks.dispute_settled(story.dispute)

    def _handoff_outcome(self, handoff: Handoff) -> Outcome:
        """Pass on ``done``; otherwise bounce to the step of the role it names."""
        if handoff.status == "done":
            return Outcome(Verdict.PASS)
        target = self.step_for_role(handoff.next_role) or "implement"
        return Outcome(Verdict.BOUNCE, handoff.summary or "changes requested", target)

    def _command_gate(self, step: str) -> Callable[[], Outcome] | None:
        gates = {"tests": self.checks.tests_red, "implement": self.checks.tests_green_and_covered}
        return gates.get(step)

    def _done_gate(self, story: StoryState, handoff: Handoff) -> Callable[[], Outcome] | None:
        """The e2e presentation check, which applies only to a ``done`` handoff."""
        applies = story.step == "e2e" and handoff.status == "done" and "acceptance" in self.steps
        return (lambda: self.checks.presented(story)) if applies else None

    def unpresented(self, story: StoryState) -> Outcome | None:
        """A return to e2e when the Proxy would start without a presentation."""
        if "e2e" not in self.steps:
            return None
        reason = self.checks.presentation(story)
        if reason is None:
            return None
        return Outcome(Verdict.RETURN, f"{reason}; run the integration-tester on it", "e2e")

    def advance(self, story: StoryState, outcome: Outcome) -> None:
        """Move ``story`` forward on a pass, back (counting a round) on a bounce."""
        moves = {
            Verdict.PASS: lambda: self._forward(story),
            Verdict.BOUNCE: lambda: self._bounce(story, outcome.bounce_to),
            Verdict.RETURN: lambda: self._return(story, outcome.bounce_to),
            Verdict.DISPUTE: lambda: self._dispute(story, outcome),
        }
        if outcome.verdict in moves:
            moves[outcome.verdict]()
        if story.step == "implement":
            story.dispute = None

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
        story.rounds, story.disputes, story.dispute = 0, 0, None
        escalated = ruling == "escalate"
        story.status = StoryStatus.BLOCKED if escalated else StoryStatus.ACTIVE


def _unchanged(dispute: OpenDispute) -> str:
    return (
        f"the disputed test file {dispute.file} has not changed; fix {dispute.test}, "
        "or confirm it with changes_requested and next_role architect"
    )


def _retry_here(outcome: Outcome, step: str) -> Outcome:
    if outcome.verdict is Verdict.BOUNCE:
        outcome.bounce_to = step
    return outcome


def _tail(text: str) -> str:
    return "\n".join(text.splitlines()[-30:])
