"""The Product Owner's MCP tools and its main ``query()`` loop.

The PO is the only long-lived session. It orchestrates through these tools;
every other role runs as a fresh query inside ``run_role``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from claude_agent_sdk import ResultError, create_sdk_mcp_server, tool

from . import handover
from .dispatch import PO, Launch, Plan, Runtime, StepRequest, StepResult, collect, refused
from .events import Event, EventKind
from .gates import StoryState, StoryStatus, role_fits_step
from .ledger import Entry, budget_status
from .providers import DEFAULT as DEFAULT_PROVIDER
from .relay import Note
from .router import Router
from .state import ModelOverride, RunStatus

SERVER = "team"
POLL_S = 5.0
DEFAULT_WAIT_S = 1800
RESUME_NOTE = "Resume the run from state."
STATUS_KINDS = {"sprint-end", "done", "blocked"}

Sleep = Callable[[float], Awaitable[None]]


class StartMode(StrEnum):
    """How ``agile-team start`` begins the PO loop."""

    DELIVERY = "delivery"
    ONBOARD = "onboarding sprint (phase B)"
    RESUME = "resume"


@dataclass(frozen=True)
class Start:
    """The human's task and the start mode."""

    task: str
    mode: StartMode = StartMode.DELIVERY


def text_result(data: Any) -> dict[str, Any]:
    """MCP tool result carrying ``data`` as JSON text."""
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}


@dataclass
class Tools:
    """Tool implementations bound to one runtime; plain async methods for testing."""

    runtime: Runtime
    sleep: Sleep = asyncio.sleep

    async def run_role(self, args: dict[str, Any]) -> dict[str, Any]:
        request = StepRequest(args["role"], args["brief"], args.get("story") or None)
        return text_result(await self.runtime.run_role(request))

    async def open_story(self, args: dict[str, Any]) -> dict[str, Any]:
        rt, sid = self.runtime, args["id"]
        if sid in rt.state.stories:
            return text_result(refused(f"story {sid} already exists"))
        first = rt.pipeline.first()
        rt.state.stories[sid] = StoryState(sid, args["title"], first, delivery=args.get("delivery"))
        rt.save()
        rt.events.emit(
            Event(EventKind.STORY_OPENED, PO, sid, {"title": args["title"], "step": first})
        )
        return text_result({"status": "opened", "step": first})

    async def start_sprint(self, args: dict[str, Any]) -> dict[str, Any]:
        ids = list(dict.fromkeys(args.get("stories") or []))
        reason = self._sprint_refusal(ids)
        if reason:
            return text_result(refused(reason))
        self._begin_sprint(args.get("goal", ""), ids)
        return text_result(
            {"sprint": self.runtime.state.sprint, "stories": ids, "next": "run the manager"}
        )

    def _sprint_refusal(self, ids: list[str]) -> str | None:
        if not ids:
            return "no stories listed; pass the story ids this sprint commits to"
        unknown = self.runtime.state.unknown_stories(ids)
        if unknown:
            return f"unknown stories: {', '.join(unknown)}; open them with open_story first"
        return None

    def _begin_sprint(self, goal: str, ids: list[str]) -> None:
        state = self.runtime.state
        state.begin_sprint(ids)
        state.status = RunStatus.RUNNING
        state.manager_due.append(f"sprint {state.sprint} start: {goal} ({', '.join(ids)})")
        self.runtime.save()
        data = {"sprint": state.sprint, "goal": goal, "stories": ids}
        self.runtime.events.emit(Event(EventKind.SPRINT_START, PO, None, data))

    async def ask_user(self, args: dict[str, Any]) -> dict[str, Any]:
        msg = self.runtime.relay.post(Note("question", args["text"], args.get("stories", [])))
        return text_result({"id": msg.id, "blocks": msg.stories})

    async def notify_user(self, args: dict[str, Any]) -> dict[str, Any]:
        kind = args.get("kind", "update")
        msg = self.runtime.relay.post(Note(kind, args["text"], args.get("stories", [])))
        if kind in STATUS_KINDS:
            self.runtime.state.status = RunStatus(kind)
            self.runtime.save()
        return text_result({"id": msg.id})

    async def wait_for_answers(self, args: dict[str, Any]) -> dict[str, Any]:
        """Poll the inbox until the given questions are answered or time runs out."""
        ids, limit = list(args.get("ids", [])), float(args.get("timeout_s", DEFAULT_WAIT_S))
        waited = 0.0
        while not self._settled(ids) and waited < limit:
            await self.sleep(POLL_S)
            waited += POLL_S
        answers = self.runtime.relay.answers()
        given = {i: answers[i].text for i in ids if i in answers}
        self._mark_delivered(list(given))
        return text_result(given)

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
        if story is None or story.status is StoryStatus.DONE:
            return text_result(refused(reason or f"story {args['story']} is done"))
        story.hold, story.note = None, args.get("note", "")
        self.runtime.save()
        return text_result({"status": "continued", "story": story.id, "step": story.step})

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
            return None, f"unknown story {args['story']!r}; open it with open_story"
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
        self.runtime.save()
        self.runtime.events.emit(Event(EventKind.OVERRIDE, PO, None, dict(args)))

    def _override_refusal(self, args: dict[str, Any]) -> str | None:
        if args["role"] not in self.runtime.book.names():
            return f"unknown role {args['role']!r}"
        if args["provider"] not in self.runtime.providers.names():
            return f"unknown provider {args['provider']!r}"
        return None if args.get("reason") else "a reason is required"

    async def story_status(self, _args: dict[str, Any]) -> dict[str, Any]:
        rt = self.runtime
        return text_result(
            {
                "sprint": rt.state.sprint,
                "stories": {sid: asdict(s) for sid, s in rt.state.stories.items()},
                "manager_due": rt.state.manager_due,
                "roles": rt.book.enabled_names(),
            }
        )


SCHEMAS: dict[str, tuple[str, dict[str, Any]]] = {
    "run_role": (
        "Run one role step yourself with your own brief; the runner runs standard steps on "
        "its own. Returns the handoff and gate.",
        {"role": str, "brief": str, "story": str},
    ),
    "open_story": (
        "Register a story; it starts in the backlog until start_sprint lists it.",
        {"id": str, "title": str, "delivery": str},
    ),
    "start_sprint": (
        "Begin the next sprint with exactly the listed story ids; unfinished stories "
        "not listed go back to the backlog. The manager must run next.",
        {"goal": str, "stories": list},
    ),
    "ask_user": (
        "Ask the human a question; blocks only the listed stories.",
        {"text": str, "stories": list},
    ),
    "notify_user": (
        "Send an update (kind: update, sprint-end, blocked, done).",
        {"text": str, "kind": str, "stories": list},
    ),
    "continue_story": (
        "Release a story the runner handed to you; your note is added to its next step's "
        "standard brief.",
        {"story": str, "note": str},
    ),
    "set_developer": (
        "Choose the developer specialisation for a story's implement steps (overrides the "
        "architect's pick).",
        {"story": str, "role": str},
    ),
    "wait_for_answers": ("Wait for answers to question ids.", {"ids": list, "timeout_s": int}),
    "budget_status": ("Spend so far against the soft budget.", {}),
    "set_role_model": (
        "Override a role's provider/model/effort with a logged reason.",
        {"role": str, "provider": str, "model": str, "effort": str, "reason": str},
    ),
    "story_status": ("Pipeline position of every story.", {}),
}
METHODS = {"budget_status": "budget"}


def mcp_server(tools: Tools) -> Any:
    """SDK MCP server exposing ``tools`` to the PO."""
    defs = [
        tool(name, desc, schema)(getattr(tools, METHODS.get(name, name)))
        for name, (desc, schema) in SCHEMAS.items()
    ]
    return create_sdk_mcp_server(SERVER, tools=defs)


def tool_names() -> list[str]:
    return [f"mcp__{SERVER}__{name}" for name in SCHEMAS]


def resume_session(runtime: Runtime, start: Start) -> str | None:
    return runtime.state.po_session if start.mode is StartMode.RESUME else None


def first_prompt(runtime: Runtime, start: Start) -> str:
    """The PO's kickoff message."""
    mode = StartMode.DELIVERY if start.mode is StartMode.RESUME else start.mode
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


def po_plan(runtime: Runtime, turn: PoTurn) -> Plan:
    """The PO's step: its MCP tools, its scope, and resume when asked."""
    role = runtime.resolve(PO)
    plan = Plan(role, runtime.scope_for(role), prompt=turn.prompt)
    plan.launch = Launch(
        mcp_servers={SERVER: mcp_server(Tools(runtime))},
        extra_allowed=tool_names(),
        resume=turn.resume,
    )
    return runtime.finish(plan)


async def run_po(runtime: Runtime, start: Start) -> StepResult:
    """Drive the run: PO turns for judgement, router passes for the pipeline."""
    return await PoRun(runtime, start).run()


@dataclass
class PoRun:
    """One invocation of the driver: PO turns alternating with router passes."""

    runtime: Runtime
    start: Start
    router: Router = field(init=False)

    def __post_init__(self) -> None:
        self.router = Router(self.runtime)

    async def run(self) -> StepResult:
        state = self.runtime.state
        self.runtime.halted_by = None
        if state.delivered is None:
            state.delivered = list(self.runtime.relay.answers())
        self._set_status(RunStatus.RUNNING)
        result = await self._turns()
        if state.status is RunStatus.RUNNING:
            self._set_status(RunStatus.IDLE)
        return result

    async def _turns(self) -> StepResult:
        result, turn = StepResult("", 0.0), await self._opening()
        while turn:
            result = await self._turn(turn)
            turn = await self._after_po()
        return result

    async def _opening(self) -> PoTurn | None:
        session = resume_session(self.runtime, self.start)
        if session is None:
            return PoTurn(first_prompt(self.runtime, self.start), None)
        if self.start.task:
            return PoTurn(resume_prompt(self.start.task), session)
        return self._hand_over(await self.router.advance(), RESUME_NOTE + "\n\n")

    async def _after_po(self) -> PoTurn | None:
        found = await self.router.advance()
        return None if found.quiet() else self._hand_over(found, "")

    def _hand_over(self, found: handover.Pass, lead: str) -> PoTurn | None:
        if not found.kinds:
            return None
        data = {"triggers": [k.value for k in found.kinds], "stories": found.stories}
        self.runtime.events.emit(
            Event(EventKind.HANDOVER, PO, None, {**data, "steps": found.steps})
        )
        state = self.runtime.state
        return PoTurn(lead + handover.prompt(found, state), state.po_session)

    async def _turn(self, turn: PoTurn) -> StepResult:
        plan = po_plan(self.runtime, turn)
        result = self.runtime.priced(plan, await self._collect(plan))
        self._settle()
        self._record(plan.role.model, result)
        return result

    def _settle(self) -> None:
        """Commit the PO's work, unless the run halted: then leave the tree for the human."""
        if not self.runtime.halted_by:
            self.runtime.settle_po()

    async def _collect(self, plan: Plan) -> StepResult:
        """Drain the PO's query. On an SDK error result, keep its session for resume."""
        try:
            return await collect(self.runtime.query_fn, plan)
        except ResultError as exc:
            state = self.runtime.state
            state.po_session = exc.session_id or state.po_session
            self.runtime.save()
            raise

    def _set_status(self, status: RunStatus) -> None:
        self.runtime.state.mark(status)
        self.runtime.save()

    def _record(self, model: str, result: StepResult) -> None:
        """Ledger the PO's cost and keep its session for resume."""
        state = self.runtime.state
        entry = Entry(PO, model, result.cost, tokens=result.tokens, turns=result.turns)
        self.runtime.ledger.record(entry)
        state.po_session = result.session_id or state.po_session
        self.runtime.save()
