"""Story pipeline state machine and the runner-checked gates.

Each story walks the enabled steps of ``config.PIPELINE_STEPS``. Two gates run
real commands (red tests after the Unit Tester; green tests plus coverage after
the Developer); the rest read the role's parsed handoff. Every bounce back adds
a round; at the cap the story is frozen until the Manager rules.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .roles import Handoff

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
BASELINE = ".team/baseline.json"
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)%")

CommandRunner = Callable[[str], tuple[int, str]]


@dataclass
class StoryState:
    """Where one story is in the pipeline."""

    id: str
    title: str
    step: str
    rounds: int = 0
    needs_manager: bool = False
    blocked: bool = False
    done: bool = False
    commit: str | None = None
    delivery: str | None = None


@dataclass
class Outcome:
    """Result of a gate. ``counts`` is False for a block, which is not a bounce."""

    passed: bool
    reason: str = ""
    bounce_to: str | None = None
    counts: bool = True


def role_fits_step(role: str, step: str) -> bool:
    """Developer specializations (``developer-cli`` …) all fit the implement step."""
    expected = STEP_ROLES[step]
    return role == expected or (expected == "developer" and role.startswith("developer"))


def step_for_role(role: str | None, steps: list[str]) -> str | None:
    """The first enabled step ``role`` owns."""
    if not role:
        return None
    return next((s for s in steps if role_fits_step(role, s)), None)


def dispatch_refusal(story: StoryState | None, role: str, blocked: set[str]) -> str | None:
    """Why ``role`` may not run on ``story`` now, or ``None``."""
    if role in UNGATED_ROLES:
        return None
    if story is None:
        if role in STORYLESS_ROLES:
            return None
        return f"{role} only runs on a story; open one with open_story"
    return _story_refusal(story, role, blocked)


def _story_refusal(story: StoryState, role: str, blocked: set[str]) -> str | None:
    if story.done:
        return f"story {story.id} is done"
    if story.blocked or story.id in blocked:
        return f"story {story.id} is blocked waiting on an answer or escalation"
    if story.needs_manager:
        return f"story {story.id} hit the round cap; run the manager for a ruling first"
    if not role_fits_step(role, story.step):
        return f"story {story.id} is at step {story.step!r}, which needs {STEP_ROLES[story.step]}"
    return None


def next_step(steps: list[str], current: str) -> str | None:
    i = steps.index(current)
    return steps[i + 1] if i + 1 < len(steps) else None


def advance(story: StoryState, outcome: Outcome, steps: list[str], cap: int) -> None:
    """Move ``story`` forward on a pass, back (counting a round) on a fail."""
    if outcome.passed:
        following = next_step(steps, story.step)
        story.done = following is None
        story.step = following or story.step
        return
    story.step = outcome.bounce_to or story.step
    if outcome.counts:
        story.rounds += 1
        story.needs_manager = story.rounds >= cap


def apply_ruling(story: StoryState, ruling: str, steps: list[str]) -> None:
    """Apply the Manager's ruling to a capped story and reset its round count."""
    story.needs_manager = False
    story.rounds = 0
    if ruling == "rescope":
        story.step = steps[0]
    elif ruling == "revise_design":
        story.step = "design" if "design" in steps else steps[0]
    elif ruling == "escalate":
        story.blocked = True


def parse_coverage(output: str) -> float | None:
    """Total coverage from a coverage report: the ``TOTAL`` line, else the last ``N%``."""
    lines = [ln for ln in output.splitlines() if "TOTAL" in ln.upper()]
    for text in (*reversed(lines), output):
        found = _PERCENT.findall(text)
        if found:
            return float(found[-1])
    return None


def load_baseline(repo: Path) -> dict[str, float]:
    path = repo / BASELINE
    return json.loads(path.read_text()) if path.is_file() else {}


@dataclass
class Checks:
    """Command-backed gates for one repo."""

    commands: dict[str, str]
    threshold: float
    run: CommandRunner
    baseline_coverage: float | None = None

    def required_coverage(self) -> float:
        """Threshold, or the recorded baseline when old debt keeps the total below it."""
        if self.baseline_coverage is None:
            return self.threshold
        return min(self.threshold, self.baseline_coverage)

    def tests_red(self) -> Outcome:
        code, _ = self.run(self.commands["test"])
        if code != 0:
            return Outcome(True)
        return Outcome(False, "tests pass before implementation; write a failing test first")

    def tests_green_and_covered(self) -> Outcome:
        code, out = self.run(self.commands["test"])
        if code != 0:
            return Outcome(False, f"tests fail:\n{_tail(out)}")
        _, cov_out = self.run(self.commands["coverage"])
        pct = parse_coverage(cov_out)
        if pct is None:
            return Outcome(False, "could not read a coverage total from the coverage command")
        if pct < self.required_coverage():
            return Outcome(False, f"coverage {pct}% is below {self.required_coverage()}%")
        return Outcome(True, f"coverage {pct}%")


def evaluate(step: str, handoff: Handoff, checks: Checks, steps: list[str]) -> Outcome:
    """Gate result for the step a role just finished."""
    if handoff.status in ("blocked", "failed"):
        return Outcome(False, f"role reported {handoff.status}: {handoff.summary}", counts=False)
    if step == "tests":
        return _retry_here(checks.tests_red(), step)
    if step == "implement":
        return _retry_here(checks.tests_green_and_covered(), step)
    if handoff.status == "done":
        return Outcome(True)
    target = step_for_role(handoff.next_role, steps) or "implement"
    return Outcome(False, handoff.summary or "changes requested", bounce_to=target)


def _retry_here(outcome: Outcome, step: str) -> Outcome:
    if not outcome.passed:
        outcome.bounce_to = step
    return outcome


def _tail(text: str, lines: int = 30) -> str:
    return "\n".join(text.splitlines()[-lines:])
