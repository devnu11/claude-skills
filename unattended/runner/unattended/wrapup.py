"""The wrap-up turn: when a cap or a graceful stop ends a prompt run, one last reply.

A run ended at a step boundary (``steps.Steps.end``) leaves its session open.
With ``--wrap-up USD`` set, the runner then sends the wrap-up prompt, naming why
the run stopped, in the same session. During that turn every tool call is
denied, so the agent can only write. Its spend is a separate allowance, counted
from the run's estimate (input tokens included, since the turn rereads the
context): reaching it interrupts the turn at once, a hard kill. The CLI's
``max_budget_usd`` leaves room for the allowance as a backstop.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_WRAP_UP_PROMPT = (
    "The run is being stopped: {reason}. Do not call any tools. In this one reply, "
    "write a summary another run can continue from: the goal, what you did, what you "
    "found and the evidence for it, what you ruled out and why, and the next steps."
)


def build_wrap_up_prompt(template: str, reason: str) -> str:
    """The wrap-up prompt, naming why the run stopped."""
    return template.replace("{reason}", reason)


@dataclass(frozen=True)
class Allowance:
    """The wrap-up turn's budget: ``usd`` on top of the run's estimate at its start."""

    usd: float
    start: float

    def is_used_up(self, estimate: float | None) -> bool:
        """True once the turn has used the allowance; an unpriced run never trips it."""
        return estimate is not None and estimate - self.start >= self.usd
