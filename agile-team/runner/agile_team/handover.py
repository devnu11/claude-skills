"""When the runner hands control to the PO.

The ``HANDOVERS`` table over step reports, and the hand-over prompt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .gates import (
    STEP_ROLES,
    STOPPED_HANDOFFS,
    UNGATED_ROLES,
    PreviousStep,
    StoryStatus,
    role_fits_step,
)
from .state import RunState


class Trigger(StrEnum):
    """Why the PO is needed."""

    REFUSED = "refused"
    ERROR = "error"
    STOPPED = "stopped"
    BAD_HANDOFF = "bad_handoff"
    QUESTIONS = "questions"
    QUARANTINE = "quarantine"
    ROUND_CAP = "round_cap"
    UNROUTABLE = "unroutable"
    HUMAN_MESSAGE = "human_message"
    SPRINT_END = "sprint_end"
    STALLED = "stalled"
    RULING_NOT_APPLIED = "ruling_not_applied"


@dataclass(frozen=True)
class Rule:
    """One hand-over row: the trigger, when it applies and the line the PO reads."""

    trigger: Trigger
    applies: Callable[[dict], bool]
    line: str


def _gate(report: dict) -> dict:
    return report.get("gate") or {}


def _unroutable(report: dict) -> bool:
    target = report.get("next_role")
    if _gate(report).get("verdict") != "bounce" or not target:
        return False
    return not any(role_fits_step(target, step) for step in STEP_ROLES)


def _bad_ungated(report: dict) -> bool:
    return report.get("status") == "bad_handoff" and report.get("role") in UNGATED_ROLES


HANDOVERS: tuple[Rule, ...] = (
    Rule(
        Trigger.REFUSED,
        lambda r: r.get("status") == "refused",
        "{story}: {role} was refused: {reason}",
    ),
    Rule(
        Trigger.ERROR,
        lambda r: r.get("status") == "error",
        "{story}: {role} crashed: {reason}; details in .team/run/crash.log",
    ),
    Rule(
        Trigger.STOPPED,
        lambda r: r.get("status") in STOPPED_HANDOFFS,
        "{story}: {role} reported {status}: {summary}",
    ),
    Rule(Trigger.BAD_HANDOFF, _bad_ungated, "{story}: {role} gave no valid handoff: {reason}"),
    Rule(
        Trigger.QUESTIONS,
        lambda r: bool(r.get("open_questions")),
        "{story}: {role} asks: {questions}",
    ),
    Rule(
        Trigger.QUARANTINE,
        lambda r: bool(r.get("quarantine")),
        "{story}: {role}'s out-of-scope changes are quarantined in {quarantine}; tell the "
        "owning role to reuse them (git cherry-pick -n {quarantine}) or ignore them",
    ),
    Rule(
        Trigger.ROUND_CAP,
        lambda r: _gate(r).get("story_status") == StoryStatus.NEEDS_MANAGER,
        "{story}: hit the round cap; run the manager on it for a ruling",
    ),
    Rule(
        Trigger.UNROUTABLE,
        _unroutable,
        "{story}: {role} sent it back for {next_role}, which owns no pipeline step; "
        "brief {next_role} yourself, then continue_story",
    ),
    Rule(
        Trigger.RULING_NOT_APPLIED,
        lambda r: (r.get("ruling") or {}).get("applied") is False,
        "{story}: the manager's {ruling} ruling was not applied: {ruling_why}",
    ),
)
QUIET_AFTER_PO = frozenset({Trigger.SPRINT_END, Trigger.STALLED})
HANDOVER_FOOTER = (
    "Handle these, then end your turn; the runner carries on with the pipeline.\n"
    "continue_story(story, note) releases a held story and passes your note to its\n"
    "next step. set_developer(story, role) picks its developer. Use run_role only\n"
    "for a step that needs a brief of your own."
)
FIELDS = ("role", "status", "summary", "reason", "next_role", "quarantine")


def matching(report: dict) -> list[Rule]:
    """The rows that apply to ``report``, in table order."""
    return [rule for rule in HANDOVERS if rule.applies(report)]


def triggers(report: dict) -> list[Trigger]:
    """The triggers ``report`` raises, in table order."""
    return [rule.trigger for rule in matching(report)]


def hold_reason(report: dict) -> str | None:
    """The matching trigger names joined by ``, ``, or ``None`` when nothing matches."""
    names = triggers(report)
    return ", ".join(names) if names else None


def report_fields(report: dict, story_id: str | None) -> dict[str, str]:
    """The text fields a line can use; ``""`` when the report lacks one."""
    fields = {name: str(report.get(name) or "") for name in FIELDS}
    fields["questions"] = "; ".join(report.get("open_questions") or [])
    ruling = report.get("ruling") or {}
    fields["ruling"] = str(ruling.get("ruling") or "")
    fields["ruling_why"] = str(ruling.get("why") or "")
    return {**fields, "story": story_id or "run"}


def report_lines(report: dict, story_id: str | None) -> list[str]:
    """One line per matching row, for the hand-over prompt."""
    fields = report_fields(report, story_id)
    return [rule.line.format(**fields) for rule in matching(report)]


def previous_step(report: dict) -> PreviousStep | None:
    """What a gated step leaves for the next brief, or ``None`` for other reports."""
    role, status = str(report.get("role", "")), report.get("status")
    if status == "bad_handoff":
        return PreviousStep(role, status, "", "bounce", str(report.get("reason", "")))
    gate = report.get("gate")
    if not gate:
        return None
    summary, next_role = str(report.get("summary") or ""), report.get("next_role")
    verdict, reason = str(gate.get("verdict", "")), str(gate.get("reason", ""))
    return PreviousStep(role, str(status), summary, verdict, reason, next_role)


@dataclass
class Pass:
    """What a router pass ended with; no ``kinds`` means the run ended."""

    kinds: list[Trigger]
    lines: list[str]
    stories: list[str]
    steps: int = field(default=0)

    def quiet(self) -> bool:
        """True when the pass started no step and only reports a state the PO already knew."""
        return self.steps == 0 and bool(self.kinds) and set(self.kinds) <= QUIET_AFTER_PO


def _board_entry(story: Any) -> str:
    if story.status is StoryStatus.DONE:
        return f"{story.id} done"
    entry = f"{story.id} {story.step} r{story.rounds}"
    if story.hold:
        return f"{entry} held"
    return entry if story.status is StoryStatus.ACTIVE else f"{entry} {story.status}"


def board(state: RunState) -> str:
    """The ``Stories:`` line for the current sprint."""
    current = [s for s in state.stories.values() if s.sprint == state.sprint]
    return "Stories: " + ", ".join(_board_entry(s) for s in current)


def prompt(pass_: Pass, state: RunState) -> str:
    """The PO's turn message for a hand-over."""
    head = (
        f"The runner needs you (sprint {state.sprint}; {pass_.steps} steps since your last turn):"
    )
    lines = [f"- {line}" for line in pass_.lines]
    return "\n".join([head, *lines, board(state), HANDOVER_FOOTER])
