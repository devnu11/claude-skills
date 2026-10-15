"""A role step's Stop hook: the role's mechanical checks run before the step may end (s126).

The hook refuses a ``done`` stop while the role has failures it can fix, handing
them back to the same agent (at most ``MAX_REFUSALS`` times, within a time
budget). The tables below are data: a new row needs no code.
"""

from __future__ import annotations

import asyncio
import fnmatch
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import HookMatcher

from . import gates, guard, requirement_changes, requirements, stages, system
from . import owners as owners_mod
from .boundary import StepKind
from .commands import TIMED_OUT
from .config import FileCommand
from .events import EventKind
from .gates import REUSED, Outcome, Pipeline, Verdict
from .owners import Item, Owners, Split
from .results import result_tail
from .roles import Handoff, HandoffError, parse_handoff

if TYPE_CHECKING:
    from .dispatch import Plan, Runtime


class StopCheck(StrEnum):
    """Every check a Stop hook can run."""

    HANDOFF = "handoff"
    LINT = "lint"
    SUITE = "suite"
    RED = "red"
    PRESENTATION = "presentation"
    REQUIREMENTS = "requirements"


@dataclass(frozen=True)
class Spec:
    """One check's stage, and the story step it needs (None: every stop)."""

    stage: stages.Name
    step: str | None = None


SPECS: dict[StopCheck, Spec] = {
    StopCheck.HANDOFF: Spec(stages.Name.STOP_HANDOFF),
    StopCheck.LINT: Spec(stages.Name.STOP_LINT),
    StopCheck.SUITE: Spec(stages.Name.STOP_SUITE, "implement"),
    StopCheck.RED: Spec(stages.Name.STOP_RED, "tests"),
    StopCheck.PRESENTATION: Spec(stages.Name.STOP_PRESENTATION, "e2e"),
    StopCheck.REQUIREMENTS: Spec(stages.Name.STOP_REQUIREMENTS),
}
EVERY_ROLE: tuple[StopCheck, ...] = (StopCheck.HANDOFF, StopCheck.LINT)
STOP_CHECKS: dict[str, tuple[StopCheck, ...]] = {
    "developer": (StopCheck.SUITE,),
    "unit-tester": (StopCheck.RED,),
    "integration-tester": (StopCheck.PRESENTATION,),
    "architect": (StopCheck.REQUIREMENTS,),
}
MAX_REFUSALS = 3
STOP_HOOK_TIMEOUT_S = 86_400.0
EVENT_LINES = 20
STOP_HOOK_KINDS = frozenset({StepKind.ROLE, StepKind.GATE_FIX})

WAY_OUT = "fix these, or hand off `changes_requested` with a `dispute` naming the test and why"
REFUSAL = (
    "The runner's stop checks failed (refusal {n} of {of}); your step is not finished.\n\n"
    "{failures}\n\n" + WAY_OUT
)
FAILURE = "[{check}] {text}"
HANDOFF_BAD = "your handoff block does not parse: {error}"
SUITE_FAILED = "{count} failing test(s) are yours to fix (run them with run_tests):\n{lines}"
STOP_CHORE = "stop checks for {role} on {story}"
COVERAGE_ROW = re.compile(r"^(?P<name>\S+)\s+\d+\s+(?P<miss>\d+)\s+.*?\d+%")


def family(role: str) -> str:
    """``developer`` for every developer specialisation, else the role."""
    return "developer" if role.startswith("developer") else role


def checks_for(role: str) -> tuple[StopCheck, ...]:
    """EVERY_ROLE, then the role's STOP_CHECKS row (SC2)."""
    return EVERY_ROLE + STOP_CHECKS.get(family(role), ())


@dataclass(frozen=True)
class Failure:
    """One check's failure: its text and how long the check took."""

    check: StopCheck
    text: str
    seconds: float


@dataclass(frozen=True)
class Proof:
    """The suite run the hook kept, and the content it ran on (SC8, SC13)."""

    base: str
    digest: str
    outcome: Outcome


def refusal_text(failures: list[Failure], attempt: stages.Attempt) -> str:
    """REFUSAL with the failures shortest first (SC12)."""
    ordered = sorted(failures, key=lambda f: len(f.text))
    body = "\n\n".join(FAILURE.format(check=f.check, text=f.text) for f in ordered)
    return REFUSAL.format(n=attempt.n, of=attempt.of, failures=body)


def own_items(outcome: Outcome, owners: Owners, listing: str) -> Split:
    """The suite's test findings split between this step's role and others (SC11)."""
    found = gates.test_findings(outcome)
    return owners_mod.split(owners_mod.placed(found, listing), owners)


def coverage_rows(output: str) -> list[str]:
    """The coverage table's rows with a non-zero Miss column, and its TOTAL row."""
    rows = [(line, COVERAGE_ROW.match(line)) for line in output.splitlines()]
    return [line for line, m in rows if m and (m["miss"] != "0" or m["name"] == "TOTAL")]


def suite_text(outcome: Outcome, own: list[Item]) -> str:
    """SUITE_FAILED for own items; else the reason, plus coverage rows with misses (SC11)."""
    if own:
        lines = "\n".join(line for item in own for line in item.lines)
        return SUITE_FAILED.format(count=len(own), lines=lines)
    rows = [] if gates.tests_failed(outcome.output) else coverage_rows(outcome.output)
    return "\n".join([outcome.reason, *rows])


def _passed() -> Outcome:
    return Outcome(Verdict.PASS)


def _timed_out(outcome: Outcome) -> bool:
    return outcome.ran is not None and outcome.ran.code == TIMED_OUT


@dataclass(eq=False)
class StopChecks:
    """One step's Stop hook: runs the role's checks; refuses own failures, at most 3 times."""

    runtime: Runtime
    plan: Plan
    refusals: int = 0
    spent: float = 0.0
    proof: Proof | None = None

    def matcher(self) -> HookMatcher:
        """The SDK matcher for this hook, with our own timeout (SC17)."""
        return HookMatcher(matcher=None, hooks=[self.hook], timeout=STOP_HOOK_TIMEOUT_S)

    async def hook(
        self, input_data: dict[str, Any], _tool_use_id: str | None, _ctx: Any
    ) -> dict[str, Any]:
        """Refuse the stop with the role's own failures, or allow it with ``{}``."""
        await system.async_sleep(0)
        if self._capped():
            return {}
        attempt = stages.Attempt(self.refusals + 1, MAX_REFUSALS)
        start = system.monotonic()
        with self.runtime.stage_log.trying(attempt), self.runtime.pulse.doing(self._chore()):
            failures = await self._failures(input_data)
        self.spent += system.monotonic() - start
        return self._refuse(failures, attempt) if failures else {}

    def reusing(self, pipeline: Pipeline) -> Pipeline:
        """A copy of ``pipeline`` whose coverage gate reuses this hook's run (SC13)."""
        return replace(pipeline, checks=replace(pipeline.checks, reuse=self.reused))

    def reused(self) -> Outcome | None:
        """The kept suite outcome if the tree has the same content; used at most once."""
        proof, self.proof = self.proof, None
        if proof is None or self.runtime.git.content_digest(proof.base) != proof.digest:
            return None
        return replace(proof.outcome, reason=REUSED.format(reason=proof.outcome.reason))

    def _hooked(self, stage: stages.Name) -> Pipeline:
        """A copy of the pipeline whose gates open ``stage`` in place of their own."""
        p = self.runtime.served(self.plan)
        return replace(p, checks=replace(p.checks, stages=lambda _name: self._open(stage)))

    def _open(self, stage: stages.Name) -> Any:
        return self.runtime.stage_log.open(stage)

    def _chore(self) -> str:
        story = self.plan.story
        return STOP_CHORE.format(role=self.plan.role.name, story=story.id if story else "-")

    def _capped(self) -> bool:
        budget = self.runtime.config.gates.stop_check_budget_s
        return self.refusals >= MAX_REFUSALS or self.spent >= budget

    def _said(self, input_data: dict[str, Any]) -> str:
        return input_data.get("last_assistant_message") or self.plan.said.text

    def _handoff(self, text: str) -> Handoff | Failure:
        start = system.monotonic()
        try:
            with self._open(stages.Name.STOP_HANDOFF):
                return parse_handoff(text)
        except HandoffError as error:
            bad = HANDOFF_BAD.format(error=error)
            return Failure(StopCheck.HANDOFF, bad, system.monotonic() - start)

    async def _failures(self, input_data: dict[str, Any]) -> list[Failure]:
        parsed = self._handoff(self._said(input_data))
        if isinstance(parsed, Failure):
            return [parsed]
        if parsed.status != "done":
            return []
        return await asyncio.to_thread(self._attempt, parsed)

    def _attempt(self, handoff: Handoff) -> list[Failure]:
        due = [c for c in checks_for(self.plan.role.name) if c in RUNNERS and self._due(c)]
        return [f for f in (self._timed(c, handoff) for c in due) if f]

    def _due(self, check: StopCheck) -> bool:
        step, story = SPECS[check].step, self.plan.story
        if step is None:
            return True
        return self.plan.kind is StepKind.ROLE and story is not None and story.step == step

    def _timed(self, check: StopCheck, handoff: Handoff) -> Failure | None:
        start = system.monotonic()
        text = RUNNERS[check](self, handoff)
        return Failure(check, text, system.monotonic() - start) if text else None

    def _refuse(self, failures: list[Failure], attempt: stages.Attempt) -> dict[str, Any]:
        self.refusals += 1
        for failure in failures:
            self._log(failure, attempt)
        return {"decision": "block", "reason": refusal_text(failures, attempt)}

    def _log(self, failure: Failure, attempt: stages.Attempt) -> None:
        text = "\n".join(failure.text.splitlines()[:EVENT_LINES])
        self.runtime.emit(
            EventKind.STOP_CHECK,
            self.plan,
            check=str(failure.check),
            stage=str(SPECS[failure.check].stage),
            attempt=attempt.n,
            of=attempt.of,
            seconds=failure.seconds,
            text=text,
        )

    # ----- the checks (RUNNERS rows) -----

    def _changed_lintable(self) -> list[str]:
        audit = guard.audit_step(self.runtime.git, self.plan.scope)
        globs = self.runtime.config.toolchain.files.lintable
        on_disk = [p for p in audit.in_scope if system.is_file(self.runtime.config.repo / p)]
        return [p for p in on_disk if any(fnmatch.fnmatch(p, g) for g in globs)]

    def _lint(self, _handoff: Handoff) -> str | None:
        toolchain, run = self.runtime.config.toolchain, self.runtime.pipeline.checks.run
        files = self._changed_lintable()
        fixes = toolchain.file_runs(FileCommand.FIX, files)
        lints = toolchain.file_runs(FileCommand.LINT, files)
        if not files or not (fixes or lints):
            return None
        with self._open(stages.Name.STOP_LINT):
            for command in fixes:
                run(command)
            ran = [run(command) for command in lints]
        bad = [out for code, out in ran if code not in (0, TIMED_OUT)]
        return result_tail("\n".join(bad)) if bad else None

    def _gated(self, stage: stages.Name, handoff: Handoff) -> Outcome:
        gate = self._hooked(stage).step_gate(self.plan.story, handoff) or _passed
        return gate()

    def _suite(self, handoff: Handoff) -> str | None:
        git = self.runtime.git
        base = git.head()
        digest = git.content_digest(base)
        outcome = self._gated(stages.Name.STOP_SUITE, handoff)
        self.proof = Proof(base, digest, outcome)
        if outcome.verdict is Verdict.PASS or _timed_out(outcome):
            return None
        return self._suite_failure(outcome)

    def _suite_failure(self, outcome: Outcome) -> str | None:
        story, checks = self.plan.story, self.runtime.pipeline.checks
        split = own_items(outcome, self.runtime.owners(story), checks.listing())
        if split.own or not split.fixes:
            return suite_text(outcome, split.own)
        return None

    def _red(self, handoff: Handoff) -> str | None:
        outcome = self._gated(stages.Name.STOP_RED, handoff)
        if outcome.verdict is Verdict.PASS or _timed_out(outcome):
            return None
        return outcome.reason

    def _presentation(self, _handoff: Handoff) -> str | None:
        checks = self.runtime.pipeline.checks
        if "acceptance" not in self.runtime.pipeline.steps:
            return None
        with self._open(stages.Name.STOP_PRESENTATION):
            return checks.presentation(self.plan.story)

    def _check_requirements(self, handoff: Handoff) -> str | None:
        """Refuse while a changed or retired requirement has no reason (C5)."""
        with self._open(stages.Name.STOP_REQUIREMENTS):
            audit = guard.audit_step(self.runtime.git, self.plan.scope)
            folder = requirements.folder_of(self.runtime.config)
            paths = requirement_changes.candidates(audit.in_scope, folder)
            found = requirement_changes.find_changes(self.runtime.git, paths)
            held = requirement_changes.sort_changes(found, handoff.requirement_changes).held
        if not held:
            return None
        return requirement_changes.STOP_EXPLAIN.format(
            explain=requirement_changes.explain_text(held)
        )


RUNNERS: dict[StopCheck, Callable[[StopChecks, Handoff], str | None]] = {
    StopCheck.LINT: StopChecks._lint,
    StopCheck.SUITE: StopChecks._suite,
    StopCheck.RED: StopChecks._red,
    StopCheck.PRESENTATION: StopChecks._presentation,
    StopCheck.REQUIREMENTS: StopChecks._check_requirements,
}
