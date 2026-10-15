"""When the runner hands control to the PO.

The ``HANDOVERS`` table over step reports, and the hand-over prompt.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .gates import (
    ROUTABLE_STEPS,
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
    GATE_HOLD = "gate_hold"
    BAD_HANDOFF = "bad_handoff"
    QUESTIONS = "questions"
    QUARANTINE = "quarantine"
    AFFECTED_DONE = "affected_done"
    ROUND_CAP = "round_cap"
    UNROUTABLE = "unroutable"
    HUMAN_MESSAGE = "human_message"
    SPRINT_END = "sprint_end"
    NEXT_SPRINT = "next_sprint"
    STALLED = "stalled"
    SPRINT_BACKLOG_STUCK = "sprint_backlog_stuck"
    RULING_NOT_APPLIED = "ruling_not_applied"
    RUNNER_FAULT = "runner_fault"
    OFF_PIPELINE_FAULT = "off_pipeline_fault"
    FAULT_NOT_APPLIED = "fault_not_applied"
    SYNC_CONFLICT = "sync_conflict"
    REBASE_CONFLICT = "rebase_conflict"
    PUSH_PERMISSION = "push_permission"
    PUSH_REJECTED = "push_rejected"
    BOUNDARY_ERROR = "boundary_error"
    BOUNDARY_ESCALATED = "boundary_escalated"
    CI_GREEN = "ci_green"
    CI_FAILED = "ci_failed"
    CI_INFRA = "ci_infra"
    MAIN_BROKEN = "main_broken"
    CI_PENDING = "ci_pending"
    KNOWN_FAILURES = "known_failures"


@dataclass(frozen=True)
class Rule:
    """One hand-over row: the trigger, when it applies and the line the PO reads."""

    trigger: Trigger
    applies: Callable[[dict], bool]
    line: str


def _gate(report: dict) -> dict:
    return report.get("gate") or {}


def _fault(report: dict) -> dict:
    return report.get("fault") or {}


def _boundary(report: dict) -> dict:
    return report.get("boundary") or {}


def _held(hold: str) -> Callable[[dict], bool]:
    return lambda r: _boundary(r).get("hold") == hold


def _faulted(report: dict, kind: str) -> bool:
    fault = _fault(report)
    return fault.get("applied") is True and fault.get("kind") == kind


def _capped(report: dict) -> bool:
    gate = _gate(report)
    return (
        gate.get("story_status") == StoryStatus.NEEDS_MANAGER and gate.get("verdict") != "escalate"
    )


def _unroutable(report: dict) -> bool:
    target = report.get("next_role")
    if _gate(report).get("verdict") != "bounce" or not target:
        return False
    return not any(role_fits_step(target, step) for step in ROUTABLE_STEPS)


def _bad_ungated(report: dict) -> bool:
    return report.get("status") == "bad_handoff" and report.get("role") in UNGATED_ROLES


def _gate_held(report: dict) -> bool:
    stopped = report.get("status") in STOPPED_HANDOFFS
    return _gate(report).get("verdict") == "hold" and not stopped


KNOWN_LINE = (
    "{story}: sprint {sprint} starts with {known_count} known failures on {team_branch} at "
    "{sha}: {known}. Nothing is held and the sprint goes on. Unless an open story already "
    "covers them, ask the liaison for a story now with request_story (evidence: the failing "
    "output below); the liaison writes it and places it at the top of this sprint or later, and "
    "the runner tells you its id. Failing output:\n{boundary_reason}"
)

AFFECTED_DONE_LINE = (
    "{story}: {role} changed requirements that done stories trace ({requirement_changes}): "
    "{affected_done}. Ask the liaison with request_story for a follow-up story that checks "
    "them against the changed requirements"
)
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
    Rule(
        Trigger.GATE_HOLD,
        _gate_held,
        "{story}: {role}'s gate is on hold: {gate_reason}; fix it, then continue_story",
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
        Trigger.AFFECTED_DONE,
        lambda r: bool(r.get("affected_done_stories")),
        AFFECTED_DONE_LINE,
    ),
    Rule(
        Trigger.ROUND_CAP,
        _capped,
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
    Rule(
        Trigger.RUNNER_FAULT,
        lambda r: _faulted(r, "runner"),
        "{story}: runner fault: {fault_reason}; the story is blocked and the human was told. "
        "Open a story to fix the runner; once it is fixed, run the manager on {story} "
        "with a ruling",
    ),
    Rule(
        Trigger.OFF_PIPELINE_FAULT,
        lambda r: _faulted(r, "off_pipeline"),
        "{story}: the manager puts the setback ({fault_reason}) on {fault}, which owns no "
        "pipeline step; brief {fault} yourself, then continue_story",
    ),
    Rule(
        Trigger.FAULT_NOT_APPLIED,
        lambda r: _fault(r).get("applied") is False,
        "{story}: the manager's fault ruling was not applied: {fault_why}; "
        "run the manager on {story} again",
    ),
    Rule(
        Trigger.SYNC_CONFLICT,
        _held("sync_conflict"),
        "{story}: sprint {sprint} end: rebasing {team_branch} onto {target} stopped at "
        '{commit} "{subject}" with {file_count} conflicting files: {file_groups}. The rebase '
        "was aborted and the team branch is unchanged. continue_boundary reruns the rebase; a "
        "conflict now goes to a DevOps step (s151)",
    ),
    Rule(
        Trigger.REBASE_CONFLICT,
        _held("rebase_conflict"),
        "{story}: sprint {sprint} end: rebasing {team_branch} onto {target} stopped at "
        '{commit} "{subject}" with {file_count} conflicting files: {file_groups}. DevOps could '
        "not settle it on the scratch branch {branch}: {reason}. DevOps's notes: {notes}. The "
        "team branch is unchanged and the liaison has the same text. continue_boundary(note) "
        "runs the rebase and a new DevOps step with your note; if the human rebases "
        "{team_branch} by hand first, the runner picks that up",
    ),
    Rule(
        Trigger.PUSH_PERMISSION,
        _held("push_permission"),
        "{story}: sprint {sprint}'s review branches are built and checked: {branches}. Ask the "
        "human once: may the team push review branches and open or update pull requests? Then "
        'set_push_permission with "yes" or "no"; it applies to every later sprint',
    ),
    Rule(
        Trigger.PUSH_REJECTED,
        _held("push_rejected"),
        "{story}: pushing {branch} was rejected and nothing after it was pushed: "
        "{boundary_reason}. Tell the human (someone else may have pushed to it), then "
        "continue_boundary",
    ),
    Rule(
        Trigger.BOUNDARY_ERROR,
        _held("error"),
        "{story}: sprint {sprint} {edge} boundary failed at {stage}: {boundary_reason}; "
        "details in .team/run/crash.log. Fix it, then continue_boundary",
    ),
    Rule(
        Trigger.BOUNDARY_ESCALATED,
        lambda r: _boundary(r).get("reviewed") is True,
        "{story}: sprint {sprint} {edge} boundary failed the same way again at {stage}; the "
        "manager reviewed it: {summary}. Once something has changed (a fix, the human's "
        "answer), continue_boundary(note); your note reaches the next devops fix",
    ),
    Rule(
        Trigger.CI_GREEN,
        lambda r: _boundary(r).get("ci") == "green",
        '{story}: sprint {sprint}\'s CI passed: {prs} is ready to merge ("Rebase and merge"). '
        "Tell the human.",
    ),
    Rule(
        Trigger.CI_FAILED,
        _held("ci_failed"),
        "{story}: sprint {sprint}'s CI failed where our code ran, on {prs}; the PR is NOT ready. "
        "Failing checks:\n{checks}\ncontinue_boundary is refused here: a re-run is not a fix. "
        "Ask the liaison for a bug story now (request_story), or pick an open story that fixes "
        "it, record it with record_ci_bug(story), tell the human the PR is NOT ready, and list "
        "the story "
        "first when you start the next sprint",
    ),
    Rule(
        Trigger.CI_INFRA,
        _held("ci_infra"),
        "{story}: sprint {sprint}'s CI job never ran a step on {prs}, and the runner's "
        "one re-run did not run either; the PR is NOT ready:\n{checks}\nTell the human (GitHub "
        "may have no runner for it). continue_boundary reads the checks again once they re-ran "
        "it; or open a story to change the CI job and record_ci_bug(story)",
    ),
    Rule(
        Trigger.MAIN_BROKEN,
        _held("main_broken"),
        "{story}: sprint {sprint}'s CI failed on {prs}, and the same job and step fail on "
        "{target}'s head: main is broken, not this sprint:\n{checks}\nAsk the liaison for a "
        "bug story for main now (request_story), and record_ci_bug(story) once the runner "
        'opens it. The sprint then ends as "ended, CI blocked '
        'by main": NOT done, the PR stays unmerged, and you start the next sprint with that '
        "story first. Tell the human",
    ),
    Rule(
        Trigger.CI_PENDING,
        _held("ci_pending"),
        "{story}: sprint {sprint}'s PR {prs} is NOT ready: {boundary_reason}:\n{checks}\n"
        "Tell the human, then continue_boundary to wait again",
    ),
    Rule(
        Trigger.KNOWN_FAILURES,
        lambda r: bool(_boundary(r).get("known_failures")),
        KNOWN_LINE,
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
    fields["affected_done"] = ", ".join(report.get("affected_done_stories") or [])
    changes = report.get("requirement_changes") or []
    fields["requirement_changes"] = "; ".join(
        f"{c['id']} {c['change']}: {c['reason']}" for c in changes
    )
    ruling = report.get("ruling") or {}
    fields["gate_reason"] = str(_gate(report).get("reason") or "")
    fields["ruling"] = str(ruling.get("ruling") or "")
    fields["ruling_why"] = str(ruling.get("why") or "")
    fault = _fault(report)
    fields["fault"] = str(fault.get("fault") or "")
    fields["fault_reason"] = str(fault.get("reason") or "")
    fields["fault_why"] = str(fault.get("why") or "")
    return {**fields, **_boundary_fields(report), "story": story_id or "run"}


BOUNDARY_TEXT = (
    "sha",
    "sprint",
    "edge",
    "stage",
    "target",
    "team_branch",
    "branch",
    "prs",
    "checks",
    "commit",
    "subject",
    "reason",
    "notes",
)


def group_files(files: Sequence[str]) -> str:
    """Paths grouped by parent directory: ``dir (n): a, b; dir2 (m): c``."""
    groups: dict[str, list[str]] = {}
    for path in files:
        parent, _, name = path.rpartition("/")
        groups.setdefault(parent or ".", []).append(name)
    return "; ".join(f"{d} ({len(n)}): {', '.join(sorted(n))}" for d, n in sorted(groups.items()))


def _boundary_fields(report: dict) -> dict[str, str]:
    """The fields of a boundary report; none for any other report."""
    boundary = _boundary(report)
    if not boundary:
        return {}
    fields = {name: str(boundary.get(name) or "") for name in BOUNDARY_TEXT}
    fields["boundary_reason"] = str(boundary.get("reason") or "")
    files = boundary.get("files") or []
    fields["files"] = ", ".join(files)
    fields["file_count"] = str(len(files))
    fields["file_groups"] = group_files(files)
    fields["branches"] = ", ".join(boundary.get("branches") or [])
    return {**fields, **_build_known_fields(boundary)}


def _build_known_fields(boundary: dict) -> dict[str, str]:
    known = boundary.get("known_failures") or []
    return {"known": ", ".join(known), "known_count": str(len(known))}


def report_lines(report: dict, story_id: str | None) -> list[str]:
    """One line per matching row, for the hand-over prompt."""
    fields = report_fields(report, story_id)
    return [rule.line.format(**fields) for rule in matching(report)]


def previous_step(report: dict) -> PreviousStep | None:
    """What a gated step leaves for the next brief, or ``None`` for other reports."""
    role, status = str(report.get("role", "")), report.get("status")
    if status == "bad_handoff":
        verdict = str(_gate(report).get("verdict") or "bounce")
        return PreviousStep(role, status, "", verdict, str(report.get("reason", "")))
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
