from __future__ import annotations

import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ProcessError,
    ResultError,
    ResultMessage,
    SystemMessage,
    TextBlock,
)
from unattended import prompt_job
from unattended.auth import ENV_VAR
from unattended.limits import Bounds, Metrics, Outcome, OutcomeKind
from unattended.pricing import Usage
from unattended.prompt_job import PromptJob
from unattended.store import (
    DEFAULT_RESUME_PROMPT,
    HEARTBEAT_ENV,
    HEARTBEAT_FILE,
    OUTPUT_FILE,
    Job,
    JobKind,
    Spec,
)
from unattended.watch import RunWatch

from .conftest import MakeJob
from .fakes import FakeClient, Sleep, Tool

LIMIT_TEXT = (
    "Claude Code returned an error result: You've hit your session limit · "
    "resets 7:20pm (America/Edmonton)"
)
USAGE = {"input_tokens": 10, "output_tokens": 5}


def init(session: str = "s1") -> SystemMessage:
    return SystemMessage("init", {"session_id": session})


def said(text: str, session: str = "s1") -> AssistantMessage:
    return AssistantMessage([TextBlock(text)], "model", session_id=session)


def result(text: str | None = "all done", is_error: bool = False) -> ResultMessage:
    return ResultMessage(
        "success", 1, 1, is_error, 3, "s1", total_cost_usd=0.25, usage=USAGE, result=text
    )


def prompt_spec(workdir: Path) -> Spec:
    return Spec(JobKind.PROMPT, str(workdir), prompt="Reply pong", model="haiku")


@pytest.fixture
def job(make_job: MakeJob, workdir: Path) -> Job:
    return make_job(prompt_spec(workdir))


def test_done_writes_output_and_metrics(job: Job) -> None:
    fake = FakeClient([init(), said("thinking"), result()])
    outcome = PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert outcome == Outcome(OutcomeKind.DONE, metrics=Metrics(0.25, 3, USAGE))
    assert job.path(OUTPUT_FILE).read_text() == "all done\n"
    assert job.load().session_id == "s1"


def test_first_run_options(job: Job, workdir: Path) -> None:
    fake = FakeClient([result()])
    PromptJob(job, {ENV_VAR: "k"}, fake).run_once(RunWatch(job))
    call = fake.calls[0]
    options = call["options"]
    assert call["prompt"] == "Reply pong"
    assert options.resume is None
    assert options.cwd == str(workdir)
    assert options.model == "haiku"
    assert options.setting_sources == ["user", "project", "local"]
    assert options.env == {ENV_VAR: "k", HEARTBEAT_ENV: str(job.path(HEARTBEAT_FILE))}


def test_session_id_is_saved_at_the_first_message(job: Job) -> None:
    fake = FakeClient([init("early"), said("x", "early")], RuntimeError("crash"))
    seen: list[str | None] = []
    fake.on_message.append(lambda: seen.append(job.load().session_id))
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert seen[0] == "early"
    assert job.load().session_id == "early"


def test_resume_passes_the_session_and_resume_prompt(job: Job) -> None:
    job.update(lambda st: setattr(st, "session_id", "s1"))
    fake = FakeClient([result()])
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert fake.calls[0]["options"].resume == "s1"
    assert fake.calls[0]["prompt"] == DEFAULT_RESUME_PROMPT


def test_limit_error_becomes_limit(job: Job) -> None:
    error = ResultError(LIMIT_TEXT, {"result": "x"}, exit_code=1)
    fake = FakeClient([init(), result("You've hit your session limit", is_error=True)], error)
    outcome = PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert outcome.kind is OutcomeKind.LIMIT
    assert outcome.reason == "session limit, resets 7:20pm (America/Edmonton)"
    assert outcome.metrics.cost == 0.25


def test_limit_in_an_exception_group(job: Job) -> None:
    group = ExceptionGroup("g", [ProcessError("Command failed", 1), ResultError(LIMIT_TEXT)])
    outcome = PromptJob(job, {}, FakeClient([], group)).run_once(RunWatch(job))
    assert outcome.reason == "session limit, resets 7:20pm (America/Edmonton)"


def test_rate_limit_error(job: Job) -> None:
    error = ResultError("API Error: 529 Overloaded", exit_code=1)
    outcome = PromptJob(job, {}, FakeClient([], error)).run_once(RunWatch(job))
    assert outcome == Outcome(OutcomeKind.RATE_LIMITED, "rate limited (HTTP 529)")


def test_other_errors_fail(job: Job) -> None:
    fake = FakeClient([said("partial")], ValueError("bad\nmore"))
    outcome = PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert outcome == Outcome(OutcomeKind.FAILED, "crashed: ValueError: bad")
    assert job.path(OUTPUT_FILE).read_text() == "partial\n"


def test_error_result_without_an_exception(job: Job) -> None:
    fake = FakeClient([result("API Error: 429 rate limited", is_error=True)])
    outcome = PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert outcome.kind is OutcomeKind.RATE_LIMITED
    assert outcome.metrics.turns == 3


def test_error_result_without_text(job: Job) -> None:
    outcome = PromptJob(job, {}, FakeClient([result(None, is_error=True)])).run_once(RunWatch(job))
    assert outcome == Outcome(OutcomeKind.FAILED, "error result", Metrics(0.25, 3, USAGE))


def test_no_messages_writes_no_output(job: Job) -> None:
    assert PromptJob(job, {}, FakeClient([])).run_once(RunWatch(job)) == Outcome(OutcomeKind.DONE)
    assert not job.path(OUTPUT_FILE).exists()


def test_text_of_ignores_other_messages() -> None:
    assert prompt_job.text_of(init()) == ""
    assert prompt_job.session_of(said("x")) == "s1"
    assert prompt_job.session_of(object()) is None


def budget_result() -> ResultMessage:
    return ResultMessage(
        prompt_job.BUDGET_SUBTYPE, 1, 1, True, 4, "s1", total_cost_usd=1.5, usage=USAGE
    )


def test_options_pass_what_is_left_of_the_cost_cap(job: Job) -> None:
    fake = FakeClient([result()])
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert fake.calls[0]["options"].max_budget_usd is None
    job.update(lambda st: (setattr(st.bounds, "max_cost", 5.0), setattr(st, "cost", 3.5)))
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert fake.calls[1]["options"].max_budget_usd == 1.5


def test_budget_result_becomes_budget(job: Job) -> None:
    outcome = PromptJob(job, {}, FakeClient([init(), budget_result()])).run_once(RunWatch(job))
    assert outcome == Outcome(OutcomeKind.BUDGET, prompt_job.BUDGET_REASON, Metrics(1.5, 4, USAGE))


def test_budget_error_becomes_budget(job: Job) -> None:
    error = ResultError(
        "Claude Code returned an error result: budget", {"subtype": "error_max_budget_usd"}
    )
    outcome = PromptJob(job, {}, FakeClient([init()], error)).run_once(RunWatch(job))
    assert outcome.kind is OutcomeKind.BUDGET
    assert job.load().session_id == "s1"


# ----- watched runs ----------------------------------------------------------------------


def hard_stopped(job: Job) -> RunWatch:
    """A watch past its deadline and hard stop, checking every 10 ms."""
    job.update(lambda st: setattr(st, "bounds", Bounds(deadline=1000.0, hardstop=0.0)))
    return RunWatch(job, time.time, 0.01)


def test_the_hard_stop_cancels_the_query(job: Job) -> None:
    fake = FakeClient([init("kept"), said("working", "kept"), Sleep(math.inf)])
    watch = hard_stopped(job)
    outcome = watch.settle(PromptJob(job, {}, fake).run_once(watch))
    assert outcome == Outcome(OutcomeKind.HALTED, "deadline (hard stop after 0s)")
    assert fake.closed
    assert job.load().session_id == "kept"
    assert job.path(OUTPUT_FILE).read_text() == "working\n"


def graceful_stopped(job: Job) -> RunWatch:
    """A watch past its deadline with no hard stop, checking every 10 ms."""
    job.update(lambda st: setattr(st, "bounds", Bounds(deadline=1000.0)))
    return RunWatch(job, time.time, 0.01)


def test_a_graceful_stop_lets_the_current_step_finish(job: Job) -> None:
    watch = graceful_stopped(job)
    fake = FakeClient([Sleep(0.05), init(), Sleep(0.05), result()])
    assert PromptJob(job, {}, fake).run_once(watch).kind is OutcomeKind.DONE
    assert watch.halt == "deadline (graceful)"


def test_a_graceful_stop_ends_the_run_at_its_next_tool_step(job: Job) -> None:
    watch = graceful_stopped(job)
    fake = FakeClient([init(), Sleep(0.05), Tool(), said("never"), result()])
    outcome = watch.settle(PromptJob(job, {}, fake).run_once(watch))
    assert outcome.kind is OutcomeKind.HALTED
    assert outcome.reason == "deadline (graceful)"
    assert fake.replies == []
    assert job.path(OUTPUT_FILE).read_text() == "stopped\n"


def test_tool_steps_pass_through_the_hooks(job: Job) -> None:
    fake = FakeClient([init(), Tool(), Tool("Read"), result()])
    outcome = PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert outcome.kind is OutcomeKind.DONE
    assert fake.replies == [{}, {}]


def test_each_message_stamps_spend_progress(job: Job) -> None:
    watch = RunWatch(job)
    PromptJob(job, {}, FakeClient([init(), said("a"), result()])).run_once(watch)
    assert watch.spend.count == 3


def spent(model: str, message_id: str, output: int) -> AssistantMessage:
    usage = {"input_tokens": 10, "output_tokens": output}
    return AssistantMessage([TextBlock("…")], model, usage=usage, message_id=message_id)


def test_run_usage_is_summed_by_model_as_messages_arrive(job: Job) -> None:
    messages = [init(), spent("claude-opus-5-5", "m1", 5), spent("claude-haiku-5-5", "m2", 7)]
    fake = FakeClient(messages, RuntimeError("crash"))
    seen: list[dict[str, Any]] = []
    fake.on_message.append(lambda: seen.append(job.load().run_usage))
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert seen[0] == {}
    assert seen[1]["claude-opus-5-5"]["output"] == 5
    assert seen[2] == {
        "claude-opus-5-5": asdict(Usage(input=10, output=5)),
        "claude-haiku-5-5": asdict(Usage(input=10, output=7)),
    }


def test_run_usage_counts_one_message_once_per_id(job: Job) -> None:
    # The CLI repeats an API response's usage on each content block it emits.
    messages = [init(), spent("m", "same", 5), spent("m", "same", 9), spent("m", None, 1)]
    PromptJob(job, {}, FakeClient(messages)).run_once(RunWatch(job))
    assert job.load().run_usage == {"m": asdict(Usage(input=20, output=10))}


def test_messages_without_usage_change_nothing(job: Job) -> None:
    PromptJob(job, {}, FakeClient([init(), said("x"), result()])).run_once(RunWatch(job))
    assert job.load().run_usage == {}


def test_metrics_carry_the_runs_estimate(job: Job) -> None:
    messages = [init(), spent("claude-opus-5-5", "m1", 1_000_000), result()]
    outcome = PromptJob(job, {}, FakeClient(messages)).run_once(RunWatch(job))
    assert outcome.metrics.estimate == pytest.approx(20 + 10 * 4 / 1_000_000)
    assert outcome.metrics.cost == 0.25


def test_estimate_is_none_before_any_usage(job: Job) -> None:
    outcome = PromptJob(job, {}, FakeClient([init(), said("x"), result()])).run_once(RunWatch(job))
    assert outcome.metrics.estimate is None


def test_estimate_is_none_for_an_unpriced_model(job: Job) -> None:
    messages = [init(), spent("mystery", "m1", 5), result()]
    outcome = PromptJob(job, {}, FakeClient(messages)).run_once(RunWatch(job))
    assert outcome.metrics.estimate is None


def test_open_client_builds_a_real_session_without_connecting() -> None:
    options = prompt_job.ClaudeAgentOptions(cwd=".")
    client = prompt_job.open_client(options)
    assert isinstance(client, prompt_job.ClaudeSDKClient)
    assert client.options is options
