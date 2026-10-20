"""Acceptance per environment (s95): the due environment, the round's verdicts, the one verdict."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .roles import Handoff
from .story_spec import Spec

REPORT = ".team/acceptance/{story}.md"
SECTION = "## Environment: {environment}"
NO_SECTION = (
    "the report {file} has no section `## Environment: {environment}`; write it, keep the "
    "other environments' sections, and hand off again"
)
NEXT_TEXT = "acceptance environment {environment}: {mark}; next: {next}"
PASSED_TEXT = "acceptance passed in every environment: {names}"
FAILED_TEXT = "acceptance failed in {count} of {total} environments:\n{lines}"
FAILED_LINE = "- {environment}: {acs}: {summary}"
NO_AC_NAMED = "no AC named"
BRIEF = """## Criteria for this step: acceptance environment {environment}

Try only these acceptance criteria; the story's other environments get their own steps.
{criteria}

Write your findings under the heading `{section}` in {file}:
rewrite that section only and keep the other environments' sections. If any of these
criteria fails, hand off `changes_requested` with "failed_acs": the failed ids."""
WORKTREE_LINE = (
    "This step's repo is {repo}: the story file and {file} are under it, "
    "not under the checkout that holds your sandbox."
)


class Mark(StrEnum):
    """One environment's verdict."""

    PASS = "pass"
    FAIL = "fail"


class Decision(StrEnum):
    """What a round's verdicts add up to."""

    NEXT = "next"
    PASS = "pass"
    FAIL = "fail"


@dataclass(frozen=True)
class Tried:
    """One environment's Proxy verdict in the current round."""

    environment: str
    mark: Mark
    failed: tuple[str, ...] = ()
    summary: str = ""
    next_role: str | None = None


def tried_of(environment: str, handoff: Handoff) -> Tried:
    """The verdict a Proxy handoff gives ``environment``."""
    mark = Mark.PASS if handoff.status == "done" else Mark.FAIL
    failed = tuple(handoff.failed_acs) if mark is Mark.FAIL else ()
    return Tried(environment, mark, failed, handoff.summary, handoff.next_role)


def load_tried(data: dict[str, Any]) -> Tried:
    """A ``Tried`` from its ``state.json`` form."""
    return Tried(
        data["environment"],
        Mark(data["mark"]),
        tuple(data.get("failed", [])),
        data.get("summary", ""),
        data.get("next_role"),
    )


@dataclass(frozen=True)
class Round:
    """A story's environments (config order) and this round's verdicts."""

    names: tuple[str, ...]
    tried: tuple[Tried, ...] = ()

    def _verdicts(self) -> dict[str, Tried]:
        return {t.environment: t for t in self.tried if t.environment in self.names}

    def complete(self) -> bool:
        """Whether every environment has a verdict."""
        return set(self.names) <= self._verdicts().keys()

    def due(self) -> str | None:
        """The environment the next Proxy step tries."""
        have = self._verdicts()
        return next((n for n in self.names if n not in have), self.names[0] if self.names else None)

    def with_try(self, new: Tried) -> Round:
        """This round plus ``new``; a decided round starts again with only ``new``."""
        old = {} if self.complete() else self._verdicts()
        merged = {**old, new.environment: new}
        return Round(self.names, tuple(merged[n] for n in self.names if n in merged))

    def failures(self) -> list[Tried]:
        """The failed verdicts, in config order."""
        return [t for t in self._verdicts().values() if t.mark is Mark.FAIL]

    def decision(self) -> Decision:
        """Next while some environment has no verdict; then pass or fail."""
        if not self.complete():
            return Decision.NEXT
        return Decision.FAIL if self.failures() else Decision.PASS

    def next_text(self, new: Tried) -> str:
        """The reason of a ``next`` verdict."""
        return NEXT_TEXT.format(environment=new.environment, mark=new.mark.value, next=self.due())

    def passed_text(self) -> str:
        """The reason of a passed round."""
        return PASSED_TEXT.format(names=", ".join(self.names))

    def failed_text(self) -> str:
        """The reason of a failed round: every failed environment and its ids."""
        lines = "\n".join(_failed_line(t) for t in self.failures())
        return FAILED_TEXT.format(count=len(self.failures()), total=len(self.names), lines=lines)

    def marks(self) -> list[dict[str, str]]:
        """Each environment's verdict for the dashboard (``""`` when not tried)."""
        have = self._verdicts()
        return [{"name": n, "verdict": have[n].mark.value if n in have else ""} for n in self.names]


def _failed_line(tried: Tried) -> str:
    acs = ", ".join(tried.failed) or NO_AC_NAMED
    return FAILED_LINE.format(environment=tried.environment, acs=acs, summary=tried.summary)


def report_file(story: str) -> str:
    """The story's one acceptance report, relative to the repo."""
    return REPORT.format(story=story)


def has_section(text: str | None, environment: str) -> bool:
    """Whether the report has the line ``## Environment: <environment>``."""
    heading = SECTION.format(environment=environment)
    return text is not None and heading in (line.rstrip() for line in text.splitlines())


def brief_section(spec: Spec, environment: str) -> str:
    """The Proxy's prompt section: only ``environment``'s ACs, and where to write."""
    mine: Sequence[str] = [
        f"- {c.id}: {c.text}".replace("\n", "\n  ")
        for c in spec.criteria
        if c.environment == environment
    ]
    return BRIEF.format(
        environment=environment,
        criteria="\n".join(mine),
        section=SECTION.format(environment=environment),
        file=report_file(spec.story),
    )
