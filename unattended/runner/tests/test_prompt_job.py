from __future__ import annotations

from collections.abc import AsyncIterator
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
from unattended.limits import Metrics, Outcome, OutcomeKind
from unattended.prompt_job import PromptJob
from unattended.store import DEFAULT_RESUME_PROMPT, OUTPUT_FILE, Job, JobKind, Spec

from .conftest import MakeJob

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


class FakeQuery:
    """Yields ``messages``, then raises ``error`` if given; records each call."""

    def __init__(self, messages: list[Any], error: Exception | None = None) -> None:
        self.messages, self.error = messages, error
        self.calls: list[dict[str, Any]] = []
        self.on_message: list[Any] = []

    async def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        self.calls.append({"prompt": prompt, "options": options})
        for message in self.messages:
            yield message
            for check in self.on_message:
                check()
        if self.error:
            raise self.error


def prompt_spec(workdir: Path) -> Spec:
    return Spec(JobKind.PROMPT, str(workdir), prompt="Reply pong", model="haiku")


@pytest.fixture
def job(make_job: MakeJob, workdir: Path) -> Job:
    return make_job(prompt_spec(workdir))


def test_done_writes_output_and_metrics(job: Job) -> None:
    fake = FakeQuery([init(), said("thinking"), result()])
    outcome = PromptJob(job, {}, fake).run_once()
    assert outcome == Outcome(OutcomeKind.DONE, metrics=Metrics(0.25, 3, USAGE))
    assert job.path(OUTPUT_FILE).read_text() == "all done\n"
    assert job.load().session_id == "s1"


def test_first_run_options(job: Job, workdir: Path) -> None:
    fake = FakeQuery([result()])
    PromptJob(job, {ENV_VAR: "k"}, fake).run_once()
    call = fake.calls[0]
    options = call["options"]
    assert call["prompt"] == "Reply pong"
    assert options.resume is None
    assert options.cwd == str(workdir)
    assert options.model == "haiku"
    assert options.setting_sources == ["user", "project", "local"]
    assert options.env == {ENV_VAR: "k"}


def test_session_id_is_saved_at_the_first_message(job: Job) -> None:
    fake = FakeQuery([init("early"), said("x", "early")], RuntimeError("crash"))
    seen: list[str | None] = []
    fake.on_message.append(lambda: seen.append(job.load().session_id))
    PromptJob(job, {}, fake).run_once()
    assert seen[0] == "early"
    assert job.load().session_id == "early"


def test_resume_passes_the_session_and_resume_prompt(job: Job) -> None:
    job.update(lambda st: setattr(st, "session_id", "s1"))
    fake = FakeQuery([result()])
    PromptJob(job, {}, fake).run_once()
    assert fake.calls[0]["options"].resume == "s1"
    assert fake.calls[0]["prompt"] == DEFAULT_RESUME_PROMPT


def test_limit_error_becomes_limit(job: Job) -> None:
    error = ResultError(LIMIT_TEXT, {"result": "x"}, exit_code=1)
    fake = FakeQuery([init(), result("You've hit your session limit", is_error=True)], error)
    outcome = PromptJob(job, {}, fake).run_once()
    assert outcome.kind is OutcomeKind.LIMIT
    assert outcome.reason == "session limit, resets 7:20pm (America/Edmonton)"
    assert outcome.metrics.cost == 0.25


def test_limit_in_an_exception_group(job: Job) -> None:
    group = ExceptionGroup("g", [ProcessError("Command failed", 1), ResultError(LIMIT_TEXT)])
    outcome = PromptJob(job, {}, FakeQuery([], group)).run_once()
    assert outcome.reason == "session limit, resets 7:20pm (America/Edmonton)"


def test_rate_limit_error(job: Job) -> None:
    error = ResultError("API Error: 529 Overloaded", exit_code=1)
    outcome = PromptJob(job, {}, FakeQuery([], error)).run_once()
    assert outcome == Outcome(OutcomeKind.RATE_LIMITED, "rate limited (HTTP 529)")


def test_other_errors_fail(job: Job) -> None:
    outcome = PromptJob(job, {}, FakeQuery([said("partial")], ValueError("bad\nmore"))).run_once()
    assert outcome == Outcome(OutcomeKind.FAILED, "crashed: ValueError: bad")
    assert job.path(OUTPUT_FILE).read_text() == "partial\n"


def test_error_result_without_an_exception(job: Job) -> None:
    fake = FakeQuery([result("API Error: 429 rate limited", is_error=True)])
    outcome = PromptJob(job, {}, fake).run_once()
    assert outcome.kind is OutcomeKind.RATE_LIMITED
    assert outcome.metrics.turns == 3


def test_error_result_without_text(job: Job) -> None:
    outcome = PromptJob(job, {}, FakeQuery([result(None, is_error=True)])).run_once()
    assert outcome == Outcome(OutcomeKind.FAILED, "error result", Metrics(0.25, 3, USAGE))


def test_no_messages_writes_no_output(job: Job) -> None:
    assert PromptJob(job, {}, FakeQuery([])).run_once() == Outcome(OutcomeKind.DONE)
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
    fake = FakeQuery([result()])
    PromptJob(job, {}, fake).run_once()
    assert fake.calls[0]["options"].max_budget_usd is None
    job.update(lambda st: (setattr(st.bounds, "max_cost", 5.0), setattr(st, "cost", 3.5)))
    PromptJob(job, {}, fake).run_once()
    assert fake.calls[1]["options"].max_budget_usd == 1.5


def test_budget_result_becomes_budget(job: Job) -> None:
    outcome = PromptJob(job, {}, FakeQuery([init(), budget_result()])).run_once()
    assert outcome == Outcome(OutcomeKind.BUDGET, prompt_job.BUDGET_REASON, Metrics(1.5, 4, USAGE))


def test_budget_error_becomes_budget(job: Job) -> None:
    error = ResultError(
        "Claude Code returned an error result: budget", {"subtype": "error_max_budget_usd"}
    )
    outcome = PromptJob(job, {}, FakeQuery([init()], error)).run_once()
    assert outcome.kind is OutcomeKind.BUDGET
    assert job.load().session_id == "s1"
