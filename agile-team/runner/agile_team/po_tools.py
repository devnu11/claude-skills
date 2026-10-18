"""The Product Owner's MCP tools and its main ``query()`` loop.

The PO is the only long-lived session. It orchestrates through these tools;
every other role runs as a fresh query inside ``run_role``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from typing import Any, ClassVar

from claude_agent_sdk import ResultError, create_sdk_mcp_server, tool

from . import (
    backlog,
    handover,
    kept_sessions,
    live,
    po_session,
    priority,
    reorders,
    salvage,
    sprint_end,
    story_admin,
    switchover,
    system,
    threads,
)
from .boundary import (
    CI_BUG_FIRST,
    CI_BUG_HOLDS,
    Boundary,
    BoundaryHold,
    BoundaryOutcome,
    Edge,
    Permission,
    held_text,  # noqa: F401  (re-exported)
    own_entry,
)
from .boundary_runner import BoundaryRunner, boundary_event
from .checkout import CheckoutChanged
from .ci import CI_OURS_REFUSAL, ours_text
from .dispatch import (
    PO,
    Launch,
    Plan,
    Runtime,
    StepRequest,
    StepResult,
    collect,
    halted_report,
    refused,
)
from .events import Event, EventKind
from .gates import FINISHED, StoryState, StoryStatus, continue_refusal, role_fits_step
from .ledger import Entry, SessionCost, budget_status
from .po_desk import TurnSnapshot
from .po_session import RenewPath
from .priority import Change, Placement, Priority, Pull, Reorder
from .providers import DEFAULT as DEFAULT_PROVIDER
from .relay import REPLY, Note
from .reverts import Reverter
from .router import Router
from .runner_tools import is_refused, text_result
from .sprint_add import (  # noqa: F401  (re-exported)
    ADD_NEEDS_REASON,
    ALREADY_IN_SPRINT,
    NO_OPEN_SPRINT,
    SPRINT_REFUSAL_BOUNDARY,
    Addition,
    SprintAdd,
)
from .stage_log import place_of
from .state import ModelOverride, RunStatus
from .story_admin import Act, Clerk
from .workspaces import Workspaces

SERVER = "team"
POLL_S = 5.0
WAIT_CHORE = "waiting for answers to {ids}"
DEFAULT_WAIT_S = 1800
RESUME_NOTE = "Resume the run from state."
USE_REPLY = "use reply_story to answer on a story's thread"


@dataclass(frozen=True)
class Evidence:
    """What the PO saw: the story and step, the failing output, the files involved."""

    story: str
    step: str
    output: str
    files: list[str]

    @classmethod
    def of(cls, raw: dict[str, Any]) -> Evidence:
        """Read a checked evidence object; the output keeps its last ``MAX_OUTPUT`` characters."""
        output = raw["output"]
        if len(output) > MAX_OUTPUT:
            output = CUT_HEAD.format(n=len(output) - MAX_OUTPUT) + output[-MAX_OUTPUT:]
        return cls(raw.get("story", ""), raw.get("step", ""), output, raw.get("files", []))


def _evidence_refusal(raw: dict[str, Any], stories: dict[str, StoryState]) -> str | None:
    """S5 refusals 3 to 6, in order."""
    for key in ("story", "step", "output"):
        if not isinstance(raw.get(key, ""), str):
            return EVIDENCE_NOT_STRING.format(key=key)
    story = raw.get("story", "")
    if story and story not in stories:
        return f"unknown story {story!r}"
    if not raw.get("output", "").strip():
        return EVIDENCE_NO_OUTPUT
    files = raw.get("files", [])
    ok = isinstance(files, list) and all(isinstance(f, str) for f in files)
    return None if ok else EVIDENCE_BAD_FILES


def _request_text(summary: str, evidence: Evidence) -> str:
    where = f"{evidence.story} at {evidence.step}" if evidence.story else "none"
    files = ", ".join(evidence.files) or "none"
    return REQUEST_TEXT.format(summary=summary, where=where, files=files, output=evidence.output)


def _no_refusal(_runtime: Runtime) -> str | None:
    return None


def _keep_going_refusal(runtime: Runtime) -> str | None:
    return sprint_end.keep_going_refusal(runtime.state, runtime.relay.blocked_stories())


KIND_REFUSALS: dict[str, Callable[[Runtime], str | None]] = {
    REPLY: lambda _runtime: USE_REPLY,
    "sprint-end": lambda runtime: sprint_end.end_refusal(runtime.state),
    "done": _keep_going_refusal,
    "blocked": _keep_going_refusal,
}
STUCK_RESETS = frozenset(
    {
        "continue_story",
        "release_story",
        "run_role",
        "revert_story",
        "request_cancel",
        "request_story",
        "pass_tests",
    }
)
REASON_CUT = 200
STATUS_KINDS = {"sprint-end", "done"}
RESTART_NEEDS_REASON = (
    "sprint {sprint} still has unfinished stories ({ids}); use add_to_sprint to add work, "
    "or give a reason for starting a new sprint"
)
NO_BOUNDARY = "no sprint boundary is pending"
CI_BUG_PULL = "CI failed on the pushed code; {story} fixes it"
NO_CI_HOLD = (
    "no boundary is held on failed CI; record_ci_bug applies after a ci_failed, ci_infra "
    "or main_broken hand-over"
)
MAX_OUTPUT = 6000
CUT_HEAD = "[first {n} characters cut]\n"
REQUEST_TEXT = (
    "The PO asks for a story: {summary}\nStory: {where}\nFiles: {files}\nFailing output:\n{output}"
)
REQUEST_NEXT = "the liaison writes the story; the runner opens it and tells you its id"
NEEDS_SUMMARY = "a summary is required"
EVIDENCE_NOT_OBJECT = "evidence must be an object {story, step, output, files}"
EVIDENCE_NOT_STRING = "evidence.{key} must be a string"
EVIDENCE_NO_OUTPUT = "evidence.output must hold the failing output"
EVIDENCE_BAD_FILES = "evidence.files must be a list of paths"
UNKNOWN_BUG = (
    "unknown story {story!r}; ask the liaison for it with request_story, "
    "then record_ci_bug once the runner opens it"
)
DONE_BUG = "story {story} is done; open a new story for the failing CI"
NOT_HELD = "the sprint {sprint} {edge} boundary is not held; the runner is on it"
PERMISSION_REFUSAL = 'answer must be "yes" or "no"'
RUNNING_STORY = "story {story} has a step running; wait for it"
LAND_NOT_MOVABLE = "story {id} is landing; it can't leave the sprint until land ends"
SWITCH_REFUSED = "story branches can't start yet:\n{lines}"
AFTER_REVIEW = frozenset({BoundaryHold.ESCALATED, BoundaryHold.REVIEWED})


class StartMode(StrEnum):
    """How ``agile-team start`` begins the PO loop."""

    WORK = "work"
    ONBOARD = "onboarding sprint (phase B)"
    RESUME = "resume"


@dataclass(frozen=True)
class Start:
    """The human's task and the start mode."""

    task: str
    mode: StartMode = StartMode.WORK


@dataclass(frozen=True)
class Sprint:
    """The arguments of one start_sprint call."""

    goal: str
    ids: list[str]
    reason: str


STORY_ARGS: dict[str, tuple[str, ...]] = {}
DEFAULT_STORY_ARGS = ("story", "stories")


def _as_ids(value: Any) -> list[str]:
    """The non-empty strings in ``value``: a string is one id, a list many, else none."""
    items = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return [i for i in items if isinstance(i, str) and i]


def named_stories(name: str, args: dict[str, Any]) -> list[str]:
    """The story ids a call of tool ``name`` with ``args`` names (s113 PT2)."""
    keys = STORY_ARGS.get(name, DEFAULT_STORY_ARGS)
    return [i for key in keys for i in _as_ids(args.get(key))]


@dataclass
class Touched:
    """The story ids one PO turn's tool calls named, first named first (s113 PT1)."""

    ids: list[str] = field(default_factory=list)

    def note(self, name: str, args: dict[str, Any]) -> None:
        """Add the stories this call names that are not noted yet."""
        self.ids.extend(dict.fromkeys(i for i in named_stories(name, args) if i not in self.ids))


@dataclass
class Tools:
    """Tool implementations bound to one runtime; plain async methods for testing."""

    runtime: Runtime
    touched: Touched = field(default_factory=lambda: Touched())
    snapshot: TurnSnapshot | None = None

    def __post_init__(self) -> None:
        """Hook for subclasses to observe a freshly built set of tools."""

    def noted(self, name: str) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
        """Tool ``name``'s method, noting the stories each call names first (PT3)."""
        method = getattr(self, METHODS.get(name, name))

        async def call(args: dict[str, Any]) -> dict[str, Any]:
            self.touched.note(name, args)
            ids = named_stories(name, args)
            if moved := self._find_move(ids):
                return text_result(refused(moved))
            result = await method(args)
            self._note_reset(name, result)
            self._accept(ids)
            return result

        return call

    def _find_move(self, ids: list[str]) -> str | None:
        """C9: the refusal for a story that changed since the turn began, else ``None``."""
        return self.snapshot.moved(ids, self.runtime.state) if self.snapshot else None

    def _accept(self, ids: list[str]) -> None:
        """C9: the PO's own change to a story never refuses its later calls."""
        if self.snapshot:
            self.snapshot.refresh(ids, self.runtime.state)

    def _note_reset(self, name: str, result: dict[str, Any]) -> None:
        """S5: a tool that acted on a Sprint Backlog story clears the stuck count."""
        if name in STUCK_RESETS and not is_refused(result):
            self.runtime.state.clear_stuck()
            self.runtime.save()

    async def run_role(self, args: dict[str, Any]) -> dict[str, Any]:
        request = StepRequest(args["role"], args["brief"], args.get("story") or None)
        running = self.runtime.flags.running
        if request.story_id in running:
            return text_result(refused(RUNNING_STORY.format(story=request.story_id)))
        running.add(request.story_id or "")
        try:
            return text_result(await self.runtime.run_role(request))
        finally:
            running.discard(request.story_id or "")

    async def request_story(self, args: dict[str, Any]) -> dict[str, Any]:
        """Ask the liaison for a story; the runner opens it and tells the PO its id (s135)."""
        if reason := self._request_refusal(args):
            return text_result(refused(reason))
        evidence = Evidence.of(args["evidence"])
        summary = args["summary"].strip()
        story = evidence.story
        note = Note("story-request", _request_text(summary, evidence), [story] if story else [])
        msg = self.runtime.relay.post(note)
        data = {"message": msg.id, "summary": summary, "step": evidence.step}
        data["files"] = evidence.files
        self.runtime.events.emit(Event(EventKind.STORY_REQUEST, PO, story or None, data))
        return text_result({"status": "requested", "message": msg.id, "next": REQUEST_NEXT})

    def _request_refusal(self, args: dict[str, Any]) -> str | None:
        summary, evidence = args.get("summary"), args.get("evidence")
        if not (isinstance(summary, str) and summary.strip()):
            return NEEDS_SUMMARY
        if not isinstance(evidence, dict):
            return EVIDENCE_NOT_OBJECT
        return _evidence_refusal(evidence, self.runtime.state.stories)

    async def start_sprint(self, args: dict[str, Any]) -> dict[str, Any]:
        ids = list(dict.fromkeys(args.get("stories") or []))
        sprint = Sprint(args.get("goal", ""), ids, args.get("reason") or "")
        reason = self._sprint_refusal(sprint) or self.runtime.load_dependencies()
        reason = reason or self._find_leaving_refusal(ids) or self._switch_refusal(ids)
        if reason:
            return text_result(refused(reason))
        self._release_leavers(ids)
        self._begin_sprint(sprint)
        state = self.runtime.state
        return text_result(
            {
                "sprint": state.sprint,
                "stories": ids,
                "order": state.order,
                "next": "run the manager",
            }
        )

    async def add_to_sprint(self, args: dict[str, Any]) -> dict[str, Any]:
        """Add open stories to the running sprint without restarting it."""
        ids = list(dict.fromkeys(args.get("stories") or []))
        add, adder = Addition(ids, args.get("reason") or ""), SprintAdd(self.runtime)
        if reason := adder.refusal(add):
            return text_result(refused(reason))
        order = adder.apply(add)
        state = self.runtime.state
        return text_result(
            {"status": "added", "sprint": state.sprint, "stories": ids, "order": order}
        )

    def _find_leaving_refusal(self, ids: list[str]) -> str | None:
        """E5: a story at land can't leave the sprint until its land ends."""
        state = self.runtime.state
        here = [s for s in state.stories.values() if s.sprint == state.sprint]
        stuck = [s.id for s in here if s.step == "land" and s.id not in ids]
        stuck = [i for i in stuck if state.stories[i].status not in FINISHED]
        return LAND_NOT_MOVABLE.format(id=stuck[0]) if stuck else None

    def _switch_refusal(self, ids: list[str]) -> str | None:
        """W1: the first sprint after the upgrade switches to story branches, or says why not."""
        state = self.runtime.state
        if state.story_branches:
            return None
        found = switchover.refusals(switchover.read_facts(self.runtime, ids))
        if found:
            return SWITCH_REFUSED.format(lines="\n".join(f"- {line}" for line in found))
        state.story_branches = True
        return None

    def _restart_refusal(self, reason: str) -> str | None:
        state = self.runtime.state
        unfinished = state.unfinished_in_sprint()
        if not unfinished or reason.strip():
            return None
        return RESTART_NEEDS_REASON.format(sprint=state.sprint, ids=", ".join(unfinished))

    def _sprint_refusal(self, sprint: Sprint) -> str | None:
        if pending := SprintAdd(self.runtime).boundary_refusal():
            return pending
        if not sprint.ids:
            return "no stories listed; pass the story ids this sprint commits to"
        unknown = self.runtime.state.unknown_stories(sprint.ids)
        if unknown:
            return priority.UNKNOWN.format(ids=", ".join(unknown))
        return self._restart_refusal(sprint.reason) or self._bug_first(sprint.ids)

    def _bug_first(self, ids: list[str]) -> str | None:
        state = self.runtime.state
        bug = state.upstream.ci_bug
        story = state.stories.get(bug)
        if bug and story and story.status is not StoryStatus.DONE and ids[:1] != [bug]:
            return CI_BUG_FIRST.format(story=bug)
        return None

    def _sprint_pull(self, bug: str, goal: str) -> tuple[Pull, str]:
        story = self.runtime.state.stories.get(bug)
        if bug and story and story.status is not StoryStatus.DONE:
            return Pull((bug,), (bug,)), f"{goal}; {CI_BUG_PULL.format(story=bug)}"
        return Pull(), goal

    def _begin_sprint(self, sprint: Sprint) -> None:
        state = self.runtime.state
        goal, ids = sprint.goal, sprint.ids
        pull, why = self._sprint_pull(state.upstream.ci_bug, goal)
        state.begin_sprint(ids)
        state.upstream.ci_bug = ""
        state.goal, state.boundary = goal, Boundary(Edge.START, state.sprint)
        state.status = RunStatus.RUNNING
        state.manager_due.append(f"sprint {state.sprint} start: {goal} ({', '.join(ids)})")
        state.po_renew_due.append(f"sprint {state.sprint} start")
        self.runtime.save()
        data: dict[str, Any] = {"sprint": state.sprint, "goal": goal, "stories": ids}
        if sprint.reason.strip():
            data["reason"] = sprint.reason
        self.runtime.events.emit(Event(EventKind.SPRINT_START, PO, None, data))
        order = self.runtime.priority().with_first(ids, state.stories.values())
        self._reorder(Reorder(Change.SPRINT, order, None, why, pull))

    def _release_leavers(self, ids: list[str]) -> None:
        """E1: a story that leaves the sprint gives up its worktree and keeps its branch."""
        rt = self.runtime
        space = Workspaces(rt.git, rt.config)
        for story in rt.state.stories.values():
            if story.worktree_head and story.id not in ids and story.status not in FINISHED:
                space.remove(story.id)
                story.worktree_head = ""
                data = {"action": "removed", "branch": story.branch, "base_sha": story.base_sha}
                data["replays"] = story.replays
                rt.events.emit(Event(EventKind.STORY_BRANCH, PO, story.id, data))

    async def prioritise(self, args: dict[str, Any]) -> dict[str, Any]:
        """Set the order the team works in."""
        rt, ids = self.runtime, list(dict.fromkeys(args.get("stories") or []))
        why = args.get("reason", "")

        def pull_of() -> Pull:
            return priority.set_pull(ids, rt.state.stories)

        def order_of() -> list[str]:
            return rt.priority().with_first(ids, rt.state.stories.values())

        reason = priority.first_refusal(
            [
                lambda: priority.order_refusal(ids, rt.state.stories),
                lambda: priority.pull_refusal(pull_of(), why),
                lambda: backlog.human_refusal(self._human_check(order_of(), pull_of()), why),
            ]
        )
        if reason:
            return text_result(refused(reason))
        return text_result(self._reorder(Reorder(Change.SET, order_of(), None, why, pull_of())))

    async def move_story(self, args: dict[str, Any]) -> dict[str, Any]:
        """Move one story to a position in the order."""
        rt, stories = self.runtime, self.runtime.state.stories
        placement = Placement(args["story"], args.get("position"))
        why, prio = args.get("reason", ""), rt.priority()

        def pull_of() -> Pull:
            return prio.move_pull(placement, stories)

        def order_of() -> list[str]:
            return prio.with_move(placement, stories)

        reason = priority.first_refusal(
            [
                lambda: prio.move_refusal(placement, stories),
                lambda: priority.pull_refusal(pull_of(), why),
                lambda: backlog.human_refusal(self._human_check(order_of(), pull_of()), why),
            ]
        )
        if reason:
            return text_result(refused(reason))
        result = self._reorder(Reorder(Change.MOVE, order_of(), placement.story, why, pull_of()))
        return text_result(self._with_note(result, placement))

    @staticmethod
    def _with_note(result: dict[str, Any], placement: Placement) -> dict[str, Any]:
        landed = result["order"].index(placement.story) + 1
        if landed != placement.position:
            note = priority.RANKED_ELSEWHERE.format(
                story=placement.story, landed=landed, position=placement.position
            )
            return {**result, "note": note}
        return result

    def _reorder(self, change: Reorder) -> dict[str, Any]:
        return {"status": "ordered", "order": self.runtime.reorder(change)}

    def _human_check(self, order: list[str], pull: Pull) -> backlog.HumanCheck:
        """What a change would do to the order the human set (B17)."""
        state = self.runtime.state
        view = backlog.View.of(state)
        after = Priority(order, self.runtime.priority().repulled(pull, state.stories))
        return backlog.HumanCheck(
            backlog.guarded(state.human_order, view),
            view.queue,
            after.queue(state.stories.values()),
        )

    async def continue_boundary(self, args: dict[str, Any]) -> dict[str, Any]:
        """Release a held sprint boundary so the runner retries its stage."""
        b = self.runtime.state.boundary
        if b is None or b.hold is None:
            return text_result(refused(self._not_held(b)))
        if b.hold is BoundaryHold.CI_FAILED and not self._check_moved_on(b):
            return text_result(refused(self._ours_refusal(b)))
        if b.hold in AFTER_REVIEW:
            b.streak, b.rounds, b.escalated = [], 0, None
        if b.hold is BoundaryHold.REBASE_CONFLICT:
            b.rebase_fix = None
        b.hold, b.failure, b.note = None, None, args.get("note", "")
        boundary_event(self.runtime, b, BoundaryOutcome.CONTINUED, note=b.note)
        self.runtime.save()
        return text_result({"status": "continued", "stage": b.stage})

    def _check_moved_on(self, b: Boundary) -> bool:
        """R9: a CI failure is released once the sprint branch moved past the head that failed."""
        own = own_entry(self.runtime.state.upstream.stack, b.sprint)
        return bool(own and own.ci and own.pushed != own.ci.head)

    def _ours_refusal(self, b: Boundary) -> str:
        results = [e.ci for e in self.runtime.state.upstream.stack if e.ci]
        return CI_OURS_REFUSAL.format(sprint=b.sprint, failures=ours_text(results))

    async def record_ci_bug(self, args: dict[str, Any]) -> dict[str, Any]:
        """Record the bug story for a PR whose CI failed; the boundary then finishes."""
        story = args["story"]
        reason = self._bug_refusal(story)
        if reason:
            return text_result(refused(reason))
        BoundaryRunner(self.runtime).settle_bug(story)
        return text_result({"status": "recorded", "story": story})

    def _bug_refusal(self, story: str) -> str | None:
        b = self.runtime.state.boundary
        if b is None or b.hold not in CI_BUG_HOLDS:
            return NO_CI_HOLD
        found = self.runtime.state.stories.get(story)
        if found is None:
            return UNKNOWN_BUG.format(story=story)
        return DONE_BUG.format(story=story) if found.status is StoryStatus.DONE else None

    def _not_held(self, b: Boundary | None) -> str:
        if b is None:
            return NO_BOUNDARY
        return NOT_HELD.format(sprint=b.sprint, edge=b.edge)

    async def set_push_permission(self, args: dict[str, Any]) -> dict[str, Any]:
        """Record the human's answer to: may the team push review branches?"""
        answer = args.get("answer")
        if answer not in (Permission.YES, Permission.NO):
            return text_result(refused(PERMISSION_REFUSAL))
        state = self.runtime.state
        state.upstream.push = Permission(answer)
        boundary_event(self.runtime, state.boundary, BoundaryOutcome.PERMISSION, answer=answer)
        self.runtime.save()
        return text_result({"status": "set", "answer": answer})

    async def ask_user(self, args: dict[str, Any]) -> dict[str, Any]:
        msg = self.runtime.relay.post(Note("question", args["text"], args.get("stories", [])))
        return text_result({"id": msg.id, "blocks": msg.stories})

    async def notify_user(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = args.get("kind", "update")
        if text := KIND_REFUSALS.get(kind, _no_refusal)(self.runtime):
            return text_result(refused(text))
        msg = self.runtime.relay.post(Note(kind, args["text"], args.get("stories", [])))
        if kind in STATUS_KINDS or kind == "blocked":
            reason = args["text"].splitlines()[0][:REASON_CUT] if args["text"] else None
            status = RunStatus(kind) if kind in STATUS_KINDS else RunStatus.RUNNING
            self.runtime.state.mark(status, reason)  # I4: waiting on the human ends nothing
            self.runtime.save()
        return text_result({"id": msg.id})

    async def reply_story(self, args: dict[str, Any]) -> dict[str, Any]:
        """Answer the human on a story's thread (s84)."""
        story, text = args.get("story", ""), args.get("text", "")
        stories = self.runtime.state.stories
        reason = priority.first_refusal(
            [lambda: threads.story_refusal(story, stories), lambda: threads.text_refusal(text)]
        )
        if reason:
            return text_result(refused(reason))
        msg = self.runtime.relay.post(Note(REPLY, text.strip(), [story]))
        return text_result({"status": "posted", "id": msg.id})

    async def wait_for_answers(self, args: dict[str, Any]) -> dict[str, Any]:
        """Poll the inbox until the given questions are answered or time runs out."""
        ids, limit = list(args.get("ids", [])), float(args.get("timeout_s", DEFAULT_WAIT_S))
        with self.runtime.pulse.doing(WAIT_CHORE.format(ids=", ".join(ids) or "—")):
            await self._poll(ids, limit)
        Clerk(self.runtime).settle()
        Reverter(self.runtime).settle()
        answers = self.runtime.relay.answers()
        given = {i: answers[i].text for i in ids if i in answers}
        self._mark_delivered(list(given))
        return text_result(given)

    async def _poll(self, ids: list[str], limit: float) -> None:
        waited = 0.0
        while not self._settled(ids) and waited < limit:
            await system.async_sleep(POLL_S)
            waited += POLL_S

    def _mark_delivered(self, ids: list[str]) -> None:
        state = self.runtime.state
        state.delivered = [
            *(state.delivered or []),
            *(i for i in ids if i not in (state.delivered or [])),
        ]
        self.runtime.save()

    async def continue_story(self, args: dict[str, Any]) -> dict[str, Any]:
        """Release a held story and pass the PO's note to its next step."""
        story, reason = self._story_for(args)
        reason = reason or continue_refusal(story)  # type: ignore[arg-type]
        if story is None or reason:
            return text_result(refused(reason))
        story.hold, story.note = None, args.get("note", "")
        self.runtime.save()
        return text_result({"status": "continued", "story": story.id, "step": story.step})

    async def hold_story(self, args: dict[str, Any]) -> dict[str, Any]:
        """Hold a story with a reason (s53)."""
        return text_result(Clerk(self.runtime).run(Act.HOLD, args))

    async def release_story(self, args: dict[str, Any]) -> dict[str, Any]:
        """Release the PO's hold, or a blocked story with no open question (s53)."""
        return text_result(Clerk(self.runtime).run(Act.RELEASE, args))

    async def request_cancel(self, args: dict[str, Any]) -> dict[str, Any]:
        """Ask the human to cancel a story (s53)."""
        return text_result(Clerk(self.runtime).run(Act.REQUEST_CANCEL, args))

    async def revert_story(self, args: dict[str, Any]) -> dict[str, Any]:
        """Revert a story's commits and put it back in the Product Backlog (s124)."""
        if moved := self.runtime.drift_halt():
            return text_result(halted_report(PO, moved))
        if pending := SprintAdd(self.runtime).boundary_refusal():
            return text_result(refused(pending))
        return text_result(Reverter(self.runtime).run(args))

    async def pass_tests(self, args: dict[str, Any]) -> dict[str, Any]:
        """Move a story stuck at tests on to the next step when the suite is green."""
        moved = self.runtime.checkout_moved()
        if moved:
            return text_result(halted_report(PO, moved))
        story, reason = self._story_for(args)
        reason = reason or self._pass_refusal(story, args)
        if reason:
            return text_result(refused(reason))
        return text_result(self._pass_tests(story, args["reason"]))  # type: ignore[arg-type]

    def _pass_refusal(self, story: StoryState | None, args: dict[str, Any]) -> str | None:
        if not args.get("reason"):
            return "a reason is required"
        with self.runtime.stage_log.within(place_of(story)):
            return self.runtime.pipeline.pass_tests_refusal(story)  # type: ignore[arg-type]

    def _pass_tests(self, story: StoryState, reason: str) -> dict[str, Any]:
        rt = self.runtime
        test = story.dispute.test if story.dispute else None
        rt.pipeline.pass_tests(story)
        story.hold, story.note = None, reason
        rt.state.manager_due.append(f"{story.id}: PO passed tests by hand: {reason}")
        rt.save()
        data = {"from": "tests", "now_at": story.step, "reason": reason, "test": test}
        rt.events.emit(Event(EventKind.TESTS_PASSED, PO, story.id, data))
        return {"status": "passed", "story": story.id, "now_at": story.step}

    async def set_developer(self, args: dict[str, Any]) -> dict[str, Any]:
        """Choose the developer specialisation for a story's implement steps."""
        story, reason = self._story_for(args)
        reason = reason or self._developer_refusal(args["role"])
        if reason:
            return text_result(refused(reason))
        story.po_developer = args["role"]  # type: ignore[union-attr]  # refused when None
        self.runtime.save()
        return text_result({"status": "set", "story": args["story"], "developer": args["role"]})

    def _story_for(self, args: dict[str, Any]) -> tuple[StoryState | None, str | None]:
        story = self.runtime.state.stories.get(args["story"])
        if story is None:
            return None, story_admin.UNKNOWN.format(story=args["story"])
        return story, None

    def _developer_refusal(self, role: str) -> str | None:
        if role not in self.runtime.book.names():
            return f"unknown role {role!r}"
        return None if role_fits_step(role, "implement") else f"{role} is not a developer role"

    def _settled(self, ids: list[str]) -> bool:
        answers = self.runtime.relay.answers()
        return all(i in answers for i in ids) or self.runtime.stop_requested()

    async def budget(self, _args: dict[str, Any]) -> dict[str, Any]:
        rt = self.runtime
        return text_result(budget_status(rt.ledger, rt.config.team.budget_usd))

    async def set_role_model(self, args: dict[str, Any]) -> dict[str, Any]:
        reason = self._override_refusal(args)
        if reason:
            return text_result(refused(reason))
        self._record_override(args)
        return text_result({"status": "set", "manager_review": "due"})

    def _record_override(self, args: dict[str, Any]) -> None:
        """Store the override and queue it for the Manager's review."""
        state, role = self.runtime.state, args["role"]
        state.overrides[role] = ModelOverride(
            args["model"], args["effort"], args["reason"], args["provider"]
        )
        state.unreviewed.append(role)
        state.manager_due.append(f"review model override for {role}")
        for story in state.stories.values():
            kept_sessions.drop_role(story, role)
        self.runtime.save()
        self.runtime.events.emit(Event(EventKind.OVERRIDE, PO, None, dict(args)))

    def _override_refusal(self, args: dict[str, Any]) -> str | None:
        if args["role"] not in self.runtime.book.names():
            return f"unknown role {args['role']!r}"
        if args["provider"] not in self.runtime.providers.names():
            return f"unknown provider {args['provider']!r}"
        return None if args.get("reason") else "a reason is required"

    async def story_status(self, _args: dict[str, Any]) -> dict[str, Any]:
        return text_result(story_status_data(self.runtime))


def story_status_data(runtime: Runtime) -> dict[str, Any]:
    """What ``story_status`` reports: sprint, stories, review reasons, enabled roles."""
    ranking = runtime.priority()
    ranked = ranking.ranked(runtime.state.stories.values())
    return {
        "sprint": runtime.state.sprint,
        "stories": {s.id: asdict(s) for s in ranked},
        "order": ranking.queue(ranked),
        "pulled": runtime.state.pulled,
        "manager_due": runtime.state.manager_due,
        "roles": runtime.book.enabled_names(),
        "boundary": asdict(b) if (b := runtime.state.boundary) else None,
    }


DASHBOARD_REASON = (
    "A reason is also required when the change changes the Product Backlog order "
    "the human set on the dashboard."
)
SCHEMAS: dict[str, tuple[str, dict[str, Any]]] = {
    "run_role": (
        "Run one role step yourself with your own brief; the runner runs standard steps on "
        "its own. Returns the handoff and gate.",
        {"role": str, "brief": str, "story": str},
    ),
    "start_sprint": (
        "Begin the next sprint with exactly the listed story ids; unfinished stories "
        "not listed go back to the Product Backlog. The manager must run next."
        " The order you list them in is their priority within each group; "
        "started stories still come first. "
        "It first reloads depends_on from every open story's file. A bad list (not ids, "
        "self, unknown, cycle) refuses the sprint and names the stories."
        " While the current sprint has unfinished stories, a reason is required; "
        "to add work to it, use add_to_sprint instead.",
        {"goal": str, "stories": list, "reason": str},
    ),
    "add_to_sprint": (
        "Add open stories to the running sprint without starting a new one: the sprint keeps "
        "its number, goal and review branch, and no boundary, manager or session renewal runs. "
        "The listed ids go first in the order, in that order, as prioritise places them; "
        "started stories still come first. A reason is required. Refused, with nothing "
        "changed, for unknown, done or cancelled ids, a story already in the sprint, a "
        "depends_on that is not done and not in the sprint (add both in one call), no open "
        "sprint, or while a boundary is pending.",
        {"stories": list, "reason": str},
    ),
    "prioritise": (
        "Set the order the team works in: the listed story ids first, in that order; every "
        "other unfinished story keeps its order after them. Started stories (with commits) "
        "always rank first, held ones after those in progress, then stories not started; "
        "the order ranks stories within each group. To pull a not-started story ahead of "
        "started ones, list it before a started one and give a reason; without a reason "
        "that is refused. Unknown or done ids are refused. " + DASHBOARD_REASON,
        {"stories": list, "reason": str},
    ),
    "move_story": (
        "Move one story to a position in the order (1 = next; the board shows each "
        "story's #position). Moving a not-started story before a started one pulls it "
        "ahead and needs a reason. If the groups place the story elsewhere for now, the "
        "result says so and the order keeps its place. " + DASHBOARD_REASON,
        {"story": str, "position": int, "reason": str},
    ),
    "ask_user": (
        "Ask the human a question; blocks only the listed stories.",
        {"text": str, "stories": list},
    ),
    "notify_user": (
        "Send an update (kind: update, sprint-end, blocked, done)."
        " kind sprint-end is refused while any story in the sprint is unfinished.",
        {"text": str, "kind": str, "stories": list},
    ),
    "reply_story": (
        "Answer the human on a story's thread (shown under the story on the dashboard). "
        "Use it when a hand-over says the human wrote to you on a story's thread. Unknown "
        "stories and empty or over-long texts are refused.",
        {"story": str, "text": str},
    ),
    "continue_story": (
        "Release a story the runner handed to you (a done story too, to clear its hold); "
        "your note is added to its next step's standard brief.",
        {"story": str, "note": str},
    ),
    "hold_story": (
        "Hold a story that isn't done or cancelled, with a reason: the router skips it and it "
        "keeps its place. No question is asked; holding again replaces the reason. Use this "
        "instead of a parked ask_user.",
        {"story": str, "reason": str},
    ),
    "release_story": (
        "Release your hold, or a blocked story with no open question, to the step it stopped "
        "at (status active); the reason goes to its next step's brief.",
        {"story": str, "reason": str},
    ),
    "request_cancel": (
        "Ask the human to cancel a story: it is held as cancel requested and the human gets one "
        'question (cancel / keep). Only their "cancel" answer cancels it; "keep" releases it. '
        "For a story with commits, say what happens to its code.",
        {"story": str, "reason": str},
    ),
    "revert_story": (
        "Revert a story's commits on the team branch in one commit and put it back in the "
        "Product Backlog at the step before tests. The runner records it in the story file, the "
        "events, the board, the review PR and the next brief of each role that worked on "
        "it, and tells the human. A story reverted before is not reverted at once: the human "
        "is asked (revert or keep). Refused for an unknown, done or cancelled story, a blank "
        "reason, a pending cancel or revert question, a story with no commits, one that "
        "started stories depend on, and while a boundary is pending.",
        {"story": str, "reason": str},
    ),
    "pass_tests": (
        "Move a story stuck at tests (open dispute, round cap, block or repeated setback) to "
        "the next step when the suite is green, e.g. a disputed test that was corrected but "
        "the gate missed it. The runner runs the tests first; the manager reviews it. A "
        "reason is required.",
        {"story": str, "reason": str},
    ),
    "set_developer": (
        "Choose the developer specialisation for a story's implement steps (overrides the "
        "architect's pick).",
        {"story": str, "role": str},
    ),
    "continue_boundary": (
        "Release a held sprint boundary (sync, checks, review branches, push) so the runner "
        "retries its stage; your note reaches the next devops fix; at the CI stage it waits "
        "for the checks again. Refused at ci_failed: a failure where our code ran needs a fix, "
        "not a re-run.",
        {"note": str},
    ),
    "record_ci_bug": (
        "After a ci_failed, ci_infra or main_broken hand-over: record the bug story you opened "
        "for the failing CI (it must exist and not be done). The boundary then finishes; list "
        "the story first in the next start_sprint.",
        {"story": str},
    ),
    "set_push_permission": (
        "Record the human's answer to: may the team push review branches and open or update "
        'PRs? answer is "yes" or "no"; it applies to every later sprint.',
        {"answer": str},
    ),
    "wait_for_answers": ("Wait for answers to question ids.", {"ids": list, "timeout_s": int}),
    "budget_status": (
        "Corrected spend so far against the budget ceiling; the run halts when spend reaches it.",
        {},
    ),
    "set_role_model": (
        "Override a role's provider/model/effort with a logged reason.",
        {"role": str, "provider": str, "model": str, "effort": str, "reason": str},
    ),
    "request_story": (
        "Ask the liaison to write a story, for a bug the team couldn't fix in its own turns; "
        "you can't write story files. summary: what is wrong, in a sentence or two. evidence: "
        "{story, step, output, files}: the story and step where it showed (empty for a failure "
        "outside any story), the failing output, and the files involved. The liaison writes "
        "the story; the runner opens it and tells you its id.",
        {"summary": str, "evidence": dict},
    ),
    "story_status": ("Pipeline position of every story, in priority order, with the order.", {}),
}
METHODS = {"budget_status": "budget"}


def mcp_server(tools: Tools) -> Any:
    """SDK MCP server exposing ``tools`` to the PO."""
    defs = [tool(name, desc, schema)(tools.noted(name)) for name, (desc, schema) in SCHEMAS.items()]
    return create_sdk_mcp_server(SERVER, tools=defs)


def tool_names() -> list[str]:
    return [f"mcp__{SERVER}__{name}" for name in SCHEMAS]


def resume_session(runtime: Runtime, start: Start) -> str | None:
    return runtime.state.po_session if start.mode is StartMode.RESUME else None


def first_prompt(runtime: Runtime, start: Start) -> str:
    """The PO's kickoff message."""
    mode = StartMode.WORK if start.mode is StartMode.RESUME else start.mode
    roles = ", ".join(role_label(runtime, name) for name in runtime.book.enabled_names())
    return (
        f"Mode: {mode}\nCadence: {runtime.state.cadence}\nRoles available: {roles}\n\n"
        f"Task from the human:\n{start.task}"
    )


def resume_prompt(message: str) -> str:
    """The resume note, plus anything new the human said when resuming."""
    return f"{RESUME_NOTE}\n\nNew from the human:\n{message}" if message else RESUME_NOTE


def role_label(runtime: Runtime, name: str) -> str:
    """``name``, plus its provider and model when it is not on Anthropic."""
    role = runtime.resolve(name)
    return name if role.provider == DEFAULT_PROVIDER else f"{name} ({role.provider}: {role.model})"


@dataclass(frozen=True)
class PoTurn:
    """One PO query: its prompt and the session it resumes."""

    prompt: str
    resume: str | None


def plan_for(tools: Tools, turn: PoTurn) -> Plan:
    """The PO's step on ``tools``: its MCP tools, its scope, and resume when asked."""
    runtime = tools.runtime
    role = runtime.resolve(PO)
    plan = Plan(role, runtime.scope_for(role), prompt=turn.prompt)
    plan.launch = Launch(
        mcp_servers={SERVER: mcp_server(tools)},
        extra_allowed=tool_names(),
        resume=turn.resume,
    )
    return runtime.finish(plan)


def po_plan(runtime: Runtime, turn: PoTurn) -> Plan:
    """The PO's step with fresh tools (kept for callers that need no stories)."""
    return plan_for(Tools(runtime), turn)


async def run_po(runtime: Runtime, start: Start) -> StepResult:
    """Drive the run: PO turns for judgement, the scheduler's tasks for the pipeline."""
    from .scheduler import Scheduler

    return await Scheduler(runtime, start).run()


@dataclass
class PoRun:
    """One invocation of the driver: PO turns alternating with router passes."""

    runtime: Runtime
    start: Start
    router: Router = field(init=False)
    ended_by: str | None = field(default=None, init=False)
    main_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    RENEWERS: ClassVar[dict[RenewPath, Callable[[PoRun, PoTurn], Awaitable[PoTurn]]]] = {}

    def __post_init__(self) -> None:
        self.router = Router(self.runtime)

    async def run(self) -> StepResult:
        state = self.runtime.state
        self.runtime.halted_by = None
        if state.delivered is None:
            state.delivered = list(self.runtime.relay.answers())
        state.unsaved = None
        self._set_status(RunStatus.RUNNING)
        result = await self._turns()
        if state.status is RunStatus.RUNNING:
            self._set_status(RunStatus.IDLE, self.ended_by)
        return result

    async def _turns(self) -> StepResult:
        result = StepResult("", 0.0)
        turn = None if self.runtime.enforce_ceiling() else await self._opening()
        while turn:
            turn = await self._renewed(turn)
            result = await self._turn(turn)
            turn = await self._after_po()
        return result

    async def _renewed(self, turn: PoTurn) -> PoTurn:
        state = self.runtime.state
        if not state.po_renew_due:
            return turn
        if turn.resume is not None:
            turn = await self.RENEWERS[RenewPath(state.po_renew_path)](self, turn)
        state.po_renew_due.clear()
        self.runtime.save()
        return turn

    async def _compact(self, turn: PoTurn) -> PoTurn:
        state, relay = self.runtime.state, self.runtime.relay
        result = await self._turn(PoTurn(po_session.COMPACT_PROMPT, turn.resume))
        if result.compacted_from is None:
            state.po_renew_path = RenewPath.HANDOFF.value
            self.runtime.save()
            return await self._handoff(turn)
        self._renew_event(RenewPath.COMPACT, result.compacted_from)
        return PoTurn(po_session.with_carry_over(relay, turn.prompt), state.po_session)

    async def _handoff(self, turn: PoTurn) -> PoTurn:
        repo, state = self.runtime.config.repo, self.runtime.state
        po_session.clear_handoff(repo)
        await self._turn(PoTurn(po_session.HANDOFF_PROMPT, turn.resume))
        text = po_session.read_handoff(repo)
        if not text:
            self._renew_event(RenewPath.KEPT, None)
            return PoTurn(
                po_session.with_carry_over(self.runtime.relay, turn.prompt), state.po_session
            )
        self._renew_event(RenewPath.HANDOFF, None)
        return PoTurn(self._fresh_prompt(text, turn), None)

    def _fresh_prompt(self, handoff: str, turn: PoTurn) -> str:
        rt = self.runtime
        status = json.dumps(story_status_data(rt), indent=1)
        parts = [
            first_prompt(rt, Start(rt.state.task)),
            po_session.fresh_lead(handoff, status),
            po_session.carry_over(rt.relay),
            turn.prompt,
        ]
        return "\n\n".join(p for p in parts if p)

    def _renew_event(self, path: RenewPath, pre_tokens: int | None) -> None:
        reasons = list(self.runtime.state.po_renew_due)
        data = {"path": path.value, "reasons": reasons, "pre_tokens": pre_tokens}
        self.runtime.events.emit(Event(EventKind.PO_SESSION, PO, None, data))

    async def _opening(self) -> PoTurn | None:
        told = self._take_interrupted()
        session = resume_session(self.runtime, self.start)
        if session is None:
            return PoTurn(_joined(first_prompt(self.runtime, self.start), told), None)
        if self.start.task or told:
            return PoTurn(_joined(resume_prompt(self.start.task), told), session)
        return self._hand_over(await self.router.advance(), RESUME_NOTE + "\n\n")

    def _take_interrupted(self) -> str:
        """The resume section on cut-off steps; it is told once, then cleared."""
        state = self.runtime.state
        section = salvage.resume_section(state.interrupted)
        state.interrupted.clear()
        self.runtime.save()
        return section

    def _take_reorders(self) -> str:
        """The dashboard reorders section; it is told once, then cleared (B15)."""
        state = self.runtime.state
        section = reorders.told_section(state.reorders_told)
        state.reorders_told.clear()
        self.runtime.save()
        return section

    async def _after_po(self) -> PoTurn | None:
        found = await self.router.advance()
        if found.quiet():
            self.ended_by = found.lines[0] if found.lines else None
            return None
        return self._hand_over(found, "")

    def _hand_over(self, found: handover.Pass, lead: str) -> PoTurn | None:
        if not found.kinds:
            return None
        data = {"triggers": [k.value for k in found.kinds], "stories": found.stories}
        self.runtime.events.emit(
            Event(EventKind.HANDOVER, PO, None, {**data, "steps": found.steps})
        )
        state = self.runtime.state
        told = self._take_reorders()
        return PoTurn(lead + told + handover.prompt(found, state), state.po_session)

    async def _turn(self, turn: PoTurn) -> StepResult:
        if self.is_turn_refused:
            return StepResult("", 0.0)
        tools = Tools(self.runtime, snapshot=TurnSnapshot.take(self.runtime.state))
        plan = plan_for(tools, turn)
        raw = await self._query(plan, tools.touched)
        result = self.runtime.priced(plan, self._own_cost(turn, raw))
        async with self.main_lock:  # D3: a land or a story step may own the checkout
            self._settle()
        self._record(plan.role.model, result)
        return result

    @property
    def is_turn_refused(self) -> bool:
        """The run halted, or the checkout moved. The drift check waits out a holder of the
        main lock, which records its own checkout move (N2)."""
        if self.runtime.halted_by:
            return True
        return not self.main_lock.locked() and self.runtime.checkout_moved()

    def _own_cost(self, turn: PoTurn, raw: StepResult) -> StepResult:
        """``raw`` with only this query's cost; remembers the session's running total."""
        if raw.session_id is None:
            return raw
        state = self.runtime.state
        known = state.po_cost or self._seed_cost()
        own = known.own_cost(turn.resume, raw.cost)
        state.po_cost = SessionCost(raw.session_id, raw.cost)
        return replace(raw, cost=own)

    def _seed_cost(self) -> SessionCost:
        """The baseline for a state.json written before s25 (C6)."""
        last = self.runtime.ledger.last_cost(PO)
        return SessionCost(self.runtime.state.po_session, last)

    def _settle(self) -> None:
        """Commit the PO's work, unless the run halted: then leave the tree for the human."""
        if not self.runtime.halted_by:
            with contextlib.suppress(CheckoutChanged):
                self.runtime.settle_po()

    async def _collect(self, plan: Plan) -> StepResult:
        """Drain the PO's query. On an SDK error result, keep its session for resume."""
        pulse = self.runtime.pulse
        plan.meter = pulse.open(self.runtime.who(plan))
        try:
            return await collect(self.runtime.query_fn, plan)
        except ResultError as exc:
            state = self.runtime.state
            state.po_session = exc.session_id or state.po_session
            self.runtime.save()
            raise
        finally:
            pulse.close(plan.meter)

    async def _query(self, plan: Plan, touched: Touched) -> StepResult:
        """Run the PO's query; emit its ``po-turn`` event whatever happens (PT4)."""
        try:
            return await self._collect(plan)
        finally:
            self._turn_event(plan.meter, touched)

    def _turn_event(self, meter: live.Meter, touched: Touched) -> None:
        """One ``po-turn`` event per PO query: its time split and the stories it named."""
        data = {
            **meter.time_split(),
            **self.runtime.pulse.clocks(),
            "stories": list(touched.ids),
        }
        self.runtime.events.emit(Event(EventKind.PO_TURN, PO, None, data))

    def _set_status(self, status: RunStatus, reason: str | None = None) -> None:
        self.runtime.state.mark(status, reason)
        self.runtime.save()

    def _record(self, model: str, result: StepResult) -> None:
        """Ledger the PO's cost, keep its session for resume, then hold the budget ceiling."""
        state = self.runtime.state
        entry = Entry(PO, model, result.cost, tokens=result.tokens, turns=result.turns)
        self.runtime.ledger.record(entry)
        state.po_session = result.session_id or state.po_session
        self.runtime.save()
        self.runtime.enforce_ceiling()


PoRun.RENEWERS = {RenewPath.COMPACT: PoRun._compact, RenewPath.HANDOFF: PoRun._handoff}


def _joined(*parts: str) -> str:
    return "\n\n".join(p for p in parts if p)
