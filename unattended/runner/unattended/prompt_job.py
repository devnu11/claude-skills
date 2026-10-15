"""Run a prompt job once through the Agent SDK, resuming its session when there is one.

The job inherits the user's Claude Code settings (permissions, hooks), so
headless it may only do what those settings allow. The session id is saved to
``state.json`` from the first message that carries it, so a crash mid-run
cannot lose it. The final result goes to ``output.md``.

A watcher checks the run's ``RunWatch`` after each slice beside the query.
A hard stop cancels the query; the SDK then ends its CLI subprocess. Prompt
jobs have no stop command, so the graceful phase lets the run go on.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    query,
)

from .limits import Metrics, Outcome, OutcomeKind, classify, strip_exit_suffix
from .probes import Stamp
from .store import OUTPUT_FILE, Job, JobState
from .watch import RunWatch, Verdict

SETTING_SOURCES: list[Any] = ["user", "project", "local"]
# The result subtype the CLI ends a run with when ``max_budget_usd`` is used up.
BUDGET_SUBTYPE = "error_max_budget_usd"
BUDGET_REASON = "cost cap reached mid-run; resume with a higher --max-cost to continue"
QueryFn = Callable[..., AsyncIterator[Any]]


def prompt_for(state: JobState) -> str:
    """The resume prompt once a session exists, else the job's prompt."""
    return state.spec.resume_prompt if state.session_id else state.spec.prompt


def options_for(state: JobState, env: Mapping[str, str]) -> ClaudeAgentOptions:
    """SDK options: the user's settings, cwd, model, session and what is left of the cost cap."""
    spec = state.spec
    return ClaudeAgentOptions(
        cwd=spec.cwd,
        model=spec.model,
        resume=state.session_id,
        setting_sources=SETTING_SOURCES,
        permission_mode=spec.permission_mode,  # type: ignore[arg-type]
        env=dict(env),
        max_budget_usd=state.bounds.budget_left(state.cost),
    )


def session_of(message: Any) -> str | None:
    """The session id a message carries: the init message's data, else its attribute."""
    if isinstance(message, SystemMessage):
        return message.data.get("session_id")
    return getattr(message, "session_id", None)


def text_of(message: Any) -> str:
    """The text blocks of an assistant message, joined."""
    if not isinstance(message, AssistantMessage):
        return ""
    return "\n".join(block.text for block in message.content if isinstance(block, TextBlock))


def metrics_of(result: ResultMessage | None) -> Metrics:
    if result is None:
        return Metrics()
    return Metrics(result.total_cost_usd or 0.0, result.num_turns, dict(result.usage or {}))


@dataclass
class Drain:
    """What a query has produced so far; saves the session id as soon as it appears.

    Each message ticks ``spend``: an agent that is thinking or spending is making progress.
    """

    job: Job
    session_id: str | None
    spend: Stamp = field(default_factory=Stamp)
    text: str = ""
    result: ResultMessage | None = None

    def note(self, message: Any) -> None:
        self.spend.tick()
        self._save_session(session_of(message))
        self.text = text_of(message) or self.text
        if isinstance(message, ResultMessage):
            self.result = message

    def _save_session(self, session_id: str | None) -> None:
        if session_id and session_id != self.session_id:
            self.session_id = session_id
            self.job.update(lambda st: setattr(st, "session_id", session_id))

    @property
    def output(self) -> str:
        return (self.result.result if self.result else None) or self.text

    def budget_spent(self, found: list[BaseException]) -> bool:
        """True when the result or an exception says the run's budget ran out."""
        return any(getattr(x, "subtype", None) == BUDGET_SUBTYPE for x in [self.result, *found])

    def finished(self) -> Outcome:
        """``DONE``, unless the result itself is an error."""
        metrics = metrics_of(self.result)
        if self.budget_spent([]):
            return Outcome(OutcomeKind.BUDGET, BUDGET_REASON, metrics)
        if self.result and self.result.is_error:
            return _with(classify(self.result.result or "error result"), metrics)
        return Outcome(OutcomeKind.DONE, metrics=metrics)

    def failed(self, exc: Exception) -> Outcome:
        """A budget stop, limit, rate limit or failure read from the exception."""
        found = leaves(exc)
        if self.budget_spent(found):
            return Outcome(OutcomeKind.BUDGET, BUDGET_REASON, metrics_of(self.result))
        outcome = classify("\n".join(strip_exit_suffix(str(leaf)) for leaf in found))
        if outcome.kind is OutcomeKind.FAILED:
            outcome = Outcome(outcome.kind, f"crashed: {type(found[0]).__name__}: {outcome.reason}")
        return _with(outcome, metrics_of(self.result))


def _with(outcome: Outcome, metrics: Metrics) -> Outcome:
    return Outcome(outcome.kind, outcome.reason, metrics)


def leaves(exc: BaseException) -> list[BaseException]:
    """``exc``, or the flattened leaf exceptions of an exception group."""
    if not isinstance(exc, BaseExceptionGroup):
        return [exc]
    return [leaf for inner in exc.exceptions for leaf in leaves(inner)]


@dataclass(frozen=True)
class Run:
    """One run: the job's state when it started and what its query has produced."""

    state: JobState
    drain: Drain


async def _watch(watch: RunWatch, scope: anyio.CancelScope) -> None:
    """Check ``watch`` after each slice; cancel ``scope`` when it says to end the run.

    An anyio cancel, not a bare ``asyncio`` task cancel: the SDK's transport
    shields its subprocess cleanup only against anyio cancellation.
    """
    while True:
        await anyio.sleep(watch.slice)
        if Verdict.END in watch.check():
            scope.cancel()
            return


@dataclass(frozen=True)
class PromptJob:
    """Runs the job's prompt, or its resume prompt in the saved session."""

    job: Job
    env: Mapping[str, str]
    query_fn: QueryFn = query

    def run_once(self, watch: RunWatch) -> Outcome:
        state = self.job.load()
        drain = Drain(self.job, state.session_id, watch.spend)
        try:
            asyncio.run(self._watched(Run(state, drain), watch))
        except Exception as exc:
            return drain.failed(exc)
        finally:
            self._write_output(drain)
        return drain.finished()

    async def _watched(self, run: Run, watch: RunWatch) -> None:
        """Drain the query beside a watcher; a hard stop cancels both, ending the run."""
        with anyio.CancelScope() as scope:
            async with anyio.create_task_group() as watcher:
                watcher.start_soon(_watch, watch, scope)
                await self._drain(run)
                watcher.cancel_scope.cancel()

    async def _drain(self, run: Run) -> None:
        options = options_for(run.state, self.env)
        async for message in self.query_fn(prompt=prompt_for(run.state), options=options):
            run.drain.note(message)

    def _write_output(self, drain: Drain) -> None:
        if drain.output:
            self.job.path(OUTPUT_FILE).write_text(drain.output.rstrip() + "\n")
