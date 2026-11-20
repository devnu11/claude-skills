"""The points between a prompt run's steps, where unattended's code decides.

The Claude Code CLI runs the agent loop. The SDK calls a PreToolUse hook before
each tool call and a PostToolUse hook after it, and those calls are the places
between model calls that belong to unattended:

- **After each step** every check in ``Steps.checks`` runs, in order. A check
  may add text for the model (``additionalContext``, which the CLI appends after
  the tool result, so the cached prefix is untouched) or ask to end the run.
- **Ending a run** (``Steps.stop``) refuses the next step with ``continue: false``,
  so the run ends at a step boundary rather than mid-call. The first reason given
  is the one kept.
- **Wrapping up** (``Steps.wrap_up``) denies every later tool call instead, so the
  agent's last turn can only write (see ``wrapup``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from claude_agent_sdk import HookMatcher

PRE = "PreToolUse"
POST = "PostToolUse"
WRAP_UP_DENIAL = "The run is wrapping up: no more tool calls. Reply with your summary."
type HookOutput = dict[str, Any]


@dataclass(frozen=True)
class Advice:
    """What one check says after a step: text for the model, and why the run must end."""

    context: str = ""
    stop: str = ""


type StepCheck = Callable[[], Advice]


class Mode(StrEnum):
    """What the hooks do with the next step."""

    RUN = "run"
    WRAP_UP = "wrap-up"


@dataclass
class Steps:
    """The hooks of one run, and the checks they run after each step."""

    checks: list[StepCheck] = field(default_factory=list)
    halt: str | None = None
    mode: Mode = Mode.RUN

    def stop(self, reason: str) -> None:
        """End the run at the next step boundary; the first reason is kept."""
        self.halt = self.halt or reason

    def wrap_up(self) -> None:
        """Deny every later tool call, so the last turn can only write."""
        self.mode = Mode.WRAP_UP

    @property
    def hooks(self) -> dict[Any, list[HookMatcher]]:
        """The SDK ``hooks`` option for these steps."""
        return {
            PRE: [HookMatcher(hooks=[self.check_step])],
            POST: [HookMatcher(hooks=[self.complete_step])],
        }

    async def check_step(self, *_hook_args: Any) -> HookOutput:
        """Deny the step while wrapping up, refuse it once the run must end, else allow it."""
        if self.mode is Mode.WRAP_UP:
            return build_denial(WRAP_UP_DENIAL)
        return {} if self.halt is None else build_stop(self.halt)

    async def complete_step(self, *_hook_args: Any) -> HookOutput:
        """Run each check; pass on their text, and end the run if one asks."""
        found = [check() for check in self.checks]
        for advice in found:
            if advice.stop:
                self.stop(advice.stop)
        return build_reply(join_context(found), self.halt)


def join_context(found: list[Advice]) -> str:
    """The checks' texts for the model, one paragraph each."""
    return "\n\n".join(advice.context for advice in found if advice.context)


def build_stop(reason: str) -> HookOutput:
    """The hook output that ends the agent loop with ``reason``."""
    return {"continue_": False, "stopReason": reason}


def build_denial(reason: str) -> HookOutput:
    """The PreToolUse output that denies one tool call and lets the turn go on."""
    decision = {"permissionDecision": "deny", "permissionDecisionReason": reason}
    return {"hookSpecificOutput": {"hookEventName": PRE, **decision}}


def build_reply(context: str, halt: str | None) -> HookOutput:
    """A PostToolUse output: ``context`` for the model, and the stop when ``halt`` is set."""
    reply: HookOutput = build_stop(halt) if halt else {}
    if context:
        reply["hookSpecificOutput"] = {"hookEventName": POST, "additionalContext": context}
    return reply
