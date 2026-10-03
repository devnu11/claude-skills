"""The Product Owner's MCP tools and its main ``query()`` loop.

The PO is the only long-lived session. It orchestrates through these tools;
every other role runs as a fresh query inside ``run_role``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool

from . import gates
from .dispatch import PO, Runtime, StepResult, build_options, collect
from .ledger import Entry, budget_status
from .roles import scope_note, system_prompt
from .state import ModelOverride

SERVER = "team"
POLL_S = 5.0
DEFAULT_WAIT_S = 1800

Sleep = Callable[[float], Awaitable[None]]


def text_result(data: Any) -> dict[str, Any]:
    """MCP tool result carrying ``data`` as JSON text."""
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}


@dataclass
class Tools:
    """Tool implementations bound to one runtime; plain async methods for testing."""

    runtime: Runtime
    sleep: Sleep = asyncio.sleep

    async def run_role(self, args: dict[str, Any]) -> dict[str, Any]:
        rt = self.runtime
        report = await rt.run_role(args["role"], args["brief"], args.get("story") or None)
        return text_result(report)

    async def open_story(self, args: dict[str, Any]) -> dict[str, Any]:
        rt, sid = self.runtime, args["id"]
        if sid in rt.state.stories:
            return text_result({"status": "refused", "reason": f"story {sid} already exists"})
        rt.state.stories[sid] = gates.StoryState(
            sid, args["title"], rt.steps[0], delivery=args.get("delivery") or None
        )
        rt.save()
        return text_result({"status": "opened", "step": rt.steps[0]})

    async def start_sprint(self, args: dict[str, Any]) -> dict[str, Any]:
        rt = self.runtime
        rt.state.sprint += 1
        rt.state.status = "running"
        rt.state.manager_due.append(f"sprint {rt.state.sprint} start: {args.get('goal', '')}")
        rt.save()
        return text_result({"sprint": rt.state.sprint, "next": "run the manager"})

    async def ask_user(self, args: dict[str, Any]) -> dict[str, Any]:
        msg = self.runtime.relay.post("question", args["text"], args.get("stories", []))
        return text_result({"id": msg.id, "blocks": msg.stories})

    async def notify_user(self, args: dict[str, Any]) -> dict[str, Any]:
        rt, kind = self.runtime, args.get("kind", "update")
        msg = rt.relay.post(kind, args["text"], args.get("stories", []))
        if kind in ("sprint-end", "done", "blocked"):
            rt.state.status = kind
            rt.save()
        return text_result({"id": msg.id})

    async def wait_for_answers(self, args: dict[str, Any]) -> dict[str, Any]:
        """Poll the inbox until the given questions are answered or time runs out."""
        rt, ids = self.runtime, list(args.get("ids", []))
        waited, limit = 0.0, float(args.get("timeout_s", DEFAULT_WAIT_S))
        while True:
            answers = rt.relay.answers()
            if all(i in answers for i in ids) or rt.stop_requested() or waited >= limit:
                return text_result({i: answers[i].text for i in ids if i in answers})
            await self.sleep(POLL_S)
            waited += POLL_S

    async def budget(self, _args: dict[str, Any]) -> dict[str, Any]:
        rt = self.runtime
        return text_result(budget_status(rt.ledger, rt.config.team.budget_usd))

    async def set_role_model(self, args: dict[str, Any]) -> dict[str, Any]:
        rt, role = self.runtime, args["role"]
        if role not in rt.book.names():
            return text_result({"status": "refused", "reason": f"unknown role {role!r}"})
        if not args.get("reason"):
            return text_result({"status": "refused", "reason": "a reason is required"})
        rt.state.overrides[role] = ModelOverride(args["model"], args["effort"], args["reason"])
        rt.state.manager_due.append(f"review model override for {role}")
        rt.save()
        return text_result({"status": "set", "manager_review": "due"})

    async def story_status(self, _args: dict[str, Any]) -> dict[str, Any]:
        rt = self.runtime
        stories = {sid: vars(s) for sid, s in rt.state.stories.items()}
        return text_result(
            {
                "stories": stories,
                "manager_due": rt.state.manager_due,
                "roles": rt.book.enabled_names(),
            }
        )


SCHEMAS: dict[str, tuple[str, dict[str, Any]]] = {
    "run_role": (
        "Run one role step on an optional story; returns its handoff and gate.",
        {"role": str, "brief": str, "story": str},
    ),
    "open_story": (
        "Register a story so it enters the pipeline.",
        {"id": str, "title": str, "delivery": str},
    ),
    "start_sprint": ("Begin a sprint; the manager must run next.", {"goal": str}),
    "ask_user": (
        "Ask the human a question; blocks only the listed stories.",
        {"text": str, "stories": list},
    ),
    "notify_user": (
        "Send an update (kind: update, sprint-end, blocked, done).",
        {"text": str, "kind": str, "stories": list},
    ),
    "wait_for_answers": ("Wait for answers to question ids.", {"ids": list, "timeout_s": int}),
    "budget_status": ("Spend so far against the soft budget.", {}),
    "set_role_model": (
        "Override a role's model/effort with a logged reason.",
        {"role": str, "model": str, "effort": str, "reason": str},
    ),
    "story_status": ("Pipeline position of every story.", {}),
}
METHODS = {"budget_status": "budget"}


def mcp_server(tools: Tools) -> Any:
    """SDK MCP server exposing ``tools`` to the PO."""
    defs = []
    for name, (desc, schema) in SCHEMAS.items():
        method = getattr(tools, METHODS.get(name, name))
        defs.append(tool(name, desc, schema)(method))
    return create_sdk_mcp_server(SERVER, tools=defs)


def tool_names() -> list[str]:
    return [f"mcp__{SERVER}__{name}" for name in SCHEMAS]


def po_options(runtime: Runtime, server: Any, resume: str | None) -> ClaudeAgentOptions:
    """Options for the PO's main loop."""
    role = runtime.book.resolve(PO, runtime.state.runtime_overrides(PO))
    scope = runtime.scope_for(role)
    note = scope_note(scope.write, scope.read)
    prompt = system_prompt(runtime.book, role, runtime.config.repo, note)
    options = build_options(
        role, prompt, scope, runtime.env, mcp_servers={SERVER: server}, extra_allowed=tool_names()
    )
    options.resume = resume
    return options


def kickoff_prompt(runtime: Runtime, task: str, onboard: bool) -> str:
    """The PO's first user message."""
    mode = "onboarding sprint (phase B)" if onboard else "delivery"
    return (
        f"Mode: {mode}\nCadence: {runtime.state.cadence}\n"
        f"Roles available: {', '.join(runtime.book.enabled_names())}\n\n"
        f"Task from the human:\n{task}"
    )


async def run_po(
    runtime: Runtime, task: str, onboard: bool = False, resume: bool = False
) -> StepResult:
    """Run the PO loop until it ends its turn; record its cost; save state."""
    server = mcp_server(Tools(runtime))
    session = runtime.state.po_session if resume else None
    options = po_options(runtime, server, session)
    prompt = "Resume the run from state." if session else kickoff_prompt(runtime, task, onboard)
    runtime.state.status = "running"
    runtime.save()
    result = await collect(runtime.query_fn, prompt, options)
    runtime.settle_po()
    role = runtime.book.resolve(PO, runtime.state.runtime_overrides(PO))
    runtime.ledger.record(Entry(PO, role.model, result.cost))
    runtime.state.po_session = result.session_id or runtime.state.po_session
    if runtime.state.status == "running":
        runtime.state.status = "idle"
    runtime.save()
    return result
