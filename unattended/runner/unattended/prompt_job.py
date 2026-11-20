"""Run a prompt job once through the Agent SDK, resuming its session when there is one.

The job inherits the user's Claude Code settings (permissions, hooks), so
headless it may only do what those settings allow. The session id is saved to
``state.json`` from the first message that carries it, so a crash mid-run
cannot lose it. Each assistant message's token usage is summed by model into
``state.run_usage`` as it arrives, so ``unattended cost`` can price the run so
far; the SDK's own ``total_cost_usd`` comes only with the result. Each API
response is also written to the per-call ledger, ``calls.jsonl`` (``ledger``),
and every prompt and message to the run's transcript (``transcript``).
The final result goes to ``output.md``.

Messages from ``unattended tell`` reach the agent at its next tool step, or
with the next run's prompt (``inbox``). The run is a ``ClaudeSDKClient``
session in streaming mode, so its hooks reach unattended between steps
(``steps.Steps``). A watcher checks the run's
``RunWatch`` after each slice beside the session. A stop's graceful phase ends
the run at its next tool step; the hard phase cancels the session, and the SDK
then ends its CLI subprocess.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
)

from .checkpoint import (
    OUTPUT_FORMAT,
    Reply,
    build_resume_prompt,
    load_checkpoint,
    save_checkpoint,
)
from .inbox import deliver_at_start, deliver_at_step
from .ledger import Ledger
from .limits import Metrics, Outcome, OutcomeKind, Spend, classify, strip_exit_suffix
from .pricing import RATES, Estimate, Rates, Usage
from .probes import Stamp
from .rates import load_rates
from .steps import Advice, Steps
from .store import OUTPUT_FILE, Job, JobState, ResumeFrom
from .transcript import Transcript
from .watch import RunWatch, Verdict
from .wrapup import Allowance, build_wrap_up_prompt

SETTING_SOURCES: list[Any] = ["user", "project", "local"]
OUTPUT_ENV = "CLAUDE_CODE_MAX_OUTPUT_TOKENS"  # the CLI's bound on one response's output
# The result subtype the CLI ends a run with when ``max_budget_usd`` is used up.
BUDGET_SUBTYPE = "error_max_budget_usd"
BUDGET_REASON = "cost cap reached mid-run; resume with a higher --max-cost to continue"


class Client(Protocol):
    """What a run needs of a Claude Code session: ``ClaudeSDKClient``, or a fake in tests."""

    async def connect(self) -> None: ...

    async def query(self, prompt: str) -> None: ...  # house-rules: allow verb-name -- SDK's name

    def receive_response(self) -> AsyncIterator[Any]: ...

    async def interrupt(self) -> None: ...

    async def disconnect(self) -> None: ...


ClientFactory = Callable[[ClaudeAgentOptions], Client]


def open_client(options: ClaudeAgentOptions) -> Client:
    """A real Claude Code session with ``options``."""
    return ClaudeSDKClient(options=options)


def prompt_for(job: Job, state: JobState) -> str:
    """The prompt for the job's next run, by what its later runs continue from."""
    return PROMPTS[state.spec.resume_from](job, state)


def _continue_session(job: Job, state: JobState) -> str:
    """The resume prompt once a session exists, else the job's prompt."""
    return state.spec.resume_prompt if state.session_id else state.spec.prompt


def _continue_checkpoint(job: Job, state: JobState) -> str:
    """The resume prompt with the last checkpoint, else the job's prompt."""
    found = load_checkpoint(job)
    return (
        state.spec.prompt if found is None else build_resume_prompt(state.spec.resume_prompt, found)
    )


PROMPTS: dict[ResumeFrom, Callable[[Job, JobState], str]] = {
    ResumeFrom.SESSION: _continue_session,
    ResumeFrom.CHECKPOINT: _continue_checkpoint,
}


def options_for(run: Run) -> ClaudeAgentOptions:
    """SDK options: the user's settings, cwd, model, session, the cost cap left and the hooks."""
    state, spec = run.state, run.state.spec
    return ClaudeAgentOptions(
        cwd=spec.cwd,
        model=spec.model,
        resume=state.session_id if spec.resume_from is ResumeFrom.SESSION else None,
        output_format=OUTPUT_FORMAT if spec.resume_from is ResumeFrom.CHECKPOINT else None,
        setting_sources=SETTING_SOURCES,
        permission_mode=spec.permission_mode,  # type: ignore[arg-type]
        env=build_env(run),
        max_budget_usd=state.bounds.compute_session_budget(state.cost),
        hooks=run.steps.hooks,
    )


def build_env(run: Run) -> dict[str, str]:
    """The run's environment, with the output bound per response when the job sets one."""
    bound = run.state.spec.max_output_tokens
    return {**run.env, **({OUTPUT_ENV: str(bound)} if bound else {})}


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


def read_usage(message: Any) -> tuple[str, str, Usage] | None:
    """(message id, model, usage) of an assistant message that reports usage, else None."""
    if not isinstance(message, AssistantMessage) or not message.usage:
        return None
    return message.message_id or str(id(message)), message.model, Usage.from_sdk(message.usage)


def sum_by_model(messages: dict[str, tuple[str, Usage]]) -> dict[str, Usage]:
    """Usage summed per model over the (model, usage) of each message."""
    summed: dict[str, Usage] = {}
    for model, usage in messages.values():
        summed[model] = summed.get(model, Usage()) + usage
    return summed


def metrics_of(result: ResultMessage | None, estimate: float | None) -> Metrics:
    """The SDK's figures from the result, beside the run's estimate from its tokens."""
    if result is None:
        return Metrics(estimate=estimate)
    cost, usage = result.total_cost_usd or 0.0, dict(result.usage or {})
    return Metrics(cost, result.num_turns, usage, estimate)


@dataclass
class Drain:
    """What a query has produced so far; saves the session id as soon as it appears.

    Each message ticks ``spend``: an agent that is thinking or spending is making progress.
    Usage is kept per message id, because the CLI repeats one API response's usage
    on each of its content blocks; the latest reading per message counts once.
    """

    job: Job
    session_id: str | None
    ledger: Ledger
    transcript: Transcript
    spend: Stamp = field(default_factory=Stamp)
    text: str = ""
    result: ResultMessage | None = None
    usage: dict[str, tuple[str, Usage]] = field(default_factory=dict)
    rates: Rates = field(default_factory=dict)

    def note(self, message: Any) -> None:
        self.spend.tick()
        self.transcript.record_message(message)
        self._save_session(session_of(message))
        self._save_usage(read_usage(message))
        self.text = text_of(message) or self.text
        if isinstance(message, ResultMessage):
            self.result = message

    def _save_usage(self, found: tuple[str, str, Usage] | None) -> None:
        if found is None:
            return
        message_id, model, usage = found
        self.usage[message_id] = (model, usage)
        self.ledger.note(found)
        summed = {model: asdict(usage) for model, usage in sum_by_model(self.usage).items()}
        self.job.update(lambda st: setattr(st, "run_usage", summed))

    def close(self) -> None:
        """Write the ledger's last response; call once the run has ended."""
        self.ledger.close()

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

    @property
    def metrics(self) -> Metrics:
        return metrics_of(self.result, self.estimate)

    @property
    def estimate(self) -> float | None:
        """The run's cost from its tokens and the rate table; None before any usage arrived."""
        if not self.usage:
            return None
        return Estimate.compute(sum_by_model(self.usage), self.rates).usd

    def finished(self) -> Outcome:
        """``DONE``, unless the result itself is an error."""
        metrics = self.metrics
        if self.budget_spent([]):
            return Outcome(OutcomeKind.BUDGET, BUDGET_REASON, metrics)
        if self.result and self.result.is_error:
            return _with(classify(self.result.result or "error result"), metrics)
        return Outcome(OutcomeKind.DONE, metrics=metrics)

    def failed(self, exc: Exception) -> Outcome:
        """A budget stop, limit, rate limit or failure read from the exception."""
        found = leaves(exc)
        if self.budget_spent(found):
            return Outcome(OutcomeKind.BUDGET, BUDGET_REASON, self.metrics)
        outcome = classify("\n".join(strip_exit_suffix(str(leaf)) for leaf in found))
        if outcome.kind is OutcomeKind.FAILED:
            outcome = Outcome(outcome.kind, f"crashed: {type(found[0]).__name__}: {outcome.reason}")
        return _with(outcome, self.metrics)


def _with(outcome: Outcome, metrics: Metrics) -> Outcome:
    return Outcome(outcome.kind, outcome.reason, metrics)


def leaves(exc: BaseException) -> list[BaseException]:
    """``exc``, or the flattened leaf exceptions of an exception group."""
    if not isinstance(exc, BaseExceptionGroup):
        return [exc]
    return [leaf for inner in exc.exceptions for leaf in leaves(inner)]


@dataclass
class CapCheck:
    """A step check: end the run once its estimated spend reaches the job's or the run's cap.

    The bounds are re-read at each step, so ``extend`` applies live. A run whose model
    cannot be priced is left to the CLI's own ``max_budget_usd``.
    """

    job: Job
    drain: Drain
    tripped: str | None = None

    def __call__(self) -> Advice:
        state = self.job.load()
        reason = state.bounds.find_cap_reason(Spend(state.cost, self.drain.estimate))
        self.tripped = self.tripped or reason
        return Advice(stop=reason or "")

    def settle(self, outcome: Outcome) -> Outcome:
        """``outcome``, or ``BUDGET`` with the cap's reason once a cap ended the run."""
        if self.tripped is None:
            return outcome
        return Outcome(OutcomeKind.BUDGET, self.tripped, outcome.metrics)


@dataclass(frozen=True)
class Sender:
    """Sends prompts into a session, recording each in the run's transcript first."""

    client: Client
    transcript: Transcript

    async def send(self, prompt: str) -> None:
        """Record ``prompt``, then send it."""
        self.transcript.record_prompt(prompt)
        await self.client.query(prompt)


@dataclass(frozen=True)
class Run:
    """One run: the job's state when it started, what its session has produced, its env,
    its watch and the hooks between its steps."""

    state: JobState
    drain: Drain
    env: dict[str, str]
    watch: RunWatch
    steps: Steps = field(default_factory=Steps)


async def _watch(run: Run, scope: anyio.CancelScope) -> None:
    """Check the run's watch after each slice: a graceful stop ends the run at its next
    step, a hard one cancels ``scope``.

    An anyio cancel, not a bare ``asyncio`` task cancel: the SDK's transport
    shields its subprocess cleanup only against anyio cancellation.
    """
    while True:
        await anyio.sleep(run.watch.slice)
        verdicts = run.watch.check()
        if Verdict.GRACEFUL in verdicts:
            run.steps.stop(run.watch.halt or "")
        if Verdict.END in verdicts:
            scope.cancel()
            return


@dataclass(frozen=True)
class PromptJob:
    """Runs the job's prompt, or its resume prompt in the saved session."""

    job: Job
    env: Mapping[str, str]
    open_client: ClientFactory = open_client
    rates_file: Path | None = None  # the stored rate table; the built-in one when None

    def run_once(self, watch: RunWatch) -> Outcome:
        state = self.job.load()
        rates = self.rates
        number = state.runs + 1
        ledger, transcript = Ledger(self.job, number, rates), Transcript(self.job, number)
        drain = Drain(self.job, state.session_id, ledger, transcript, watch.spend, rates=rates)
        cap = CapCheck(self.job, drain)
        run = Run(state, drain, {**self.env, **watch.env()}, watch, self.build_steps(cap))
        return cap.settle(self._run(run))

    def _run(self, run: Run) -> Outcome:
        """Run the session; the outcome from its result, or from what it raised."""
        try:
            asyncio.run(self._watched(run))
        except Exception as exc:
            return run.drain.failed(exc)
        finally:
            self._write_output(run.drain)
            self._save_checkpoint(run)
            run.drain.close()
        return run.drain.finished()

    def _save_checkpoint(self, run: Run) -> None:
        """Keep the run's structured reply as the checkpoint, when the job resumes from one."""
        if run.state.spec.resume_from is not ResumeFrom.CHECKPOINT:
            return
        found = run.drain.result.structured_output if run.drain.result else None
        number = run.state.runs + 1
        if found is None:
            self.job.event("checkpoint-missing", {"run": number})
            return
        save_checkpoint(self.job, Reply(number, found))

    def build_steps(self, cap: CapCheck) -> Steps:
        """A run's step hooks: deliver waiting messages, then end the run at a cap."""
        return Steps([lambda: deliver_at_step(self.job), cap])

    @property
    def rates(self) -> Rates:
        """The stored table, else the built-in one."""
        return RATES if self.rates_file is None else load_rates(self.rates_file)

    async def _watched(self, run: Run) -> None:
        """Drain the session beside a watcher; a hard stop cancels both, ending the run."""
        with anyio.CancelScope() as scope:
            async with anyio.create_task_group() as watcher:
                watcher.start_soon(_watch, run, scope)
                await self._drain(run)
                watcher.cancel_scope.cancel()

    async def _drain(self, run: Run) -> None:
        """Send the prompt and note each message until the result; always disconnect."""
        client = self.open_client(options_for(run))
        await client.connect()
        try:
            prompt = deliver_at_start(self.job, prompt_for(self.job, run.state))
            await Sender(client, run.drain.transcript).send(prompt)
            async for message in client.receive_response():
                run.drain.note(message)
            await self._wrap_up(client, run)
        finally:
            with anyio.CancelScope(shield=True):
                await client.disconnect()

    async def _wrap_up(self, client: Client, run: Run) -> None:
        """After a run ended at a step, its wrap-up turn, when the job grants one."""
        usd = self.job.load().bounds.wrap_up
        if run.steps.halt is None or usd is None:
            return
        run.steps.wrap_up()
        self.job.event("wrap-up", {"reason": run.steps.halt, "allowance": usd})
        prompt = build_wrap_up_prompt(run.state.spec.wrap_up_prompt, run.steps.halt)
        await Sender(client, run.drain.transcript).send(prompt)
        await self._drain_within(client, run)

    async def _drain_within(self, client: Client, run: Run) -> None:
        """Note the turn's messages; interrupt it once it has used the wrap-up allowance."""
        allowance = Allowance(self.job.load().bounds.wrap_up or 0.0, run.drain.estimate or 0.0)
        async for message in client.receive_response():
            run.drain.note(message)
            if allowance.is_used_up(run.drain.estimate):
                self.job.event("wrap-up-cut", {"allowance": allowance.usd})
                await client.interrupt()
                return

    def _write_output(self, drain: Drain) -> None:
        if drain.output:
            self.job.path(OUTPUT_FILE).write_text(drain.output.rstrip() + "\n")
