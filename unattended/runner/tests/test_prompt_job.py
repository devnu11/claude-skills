from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, replace
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
from unattended import inbox, prompt_job
from unattended.auth import ENV_VAR
from unattended.checkpoint import OUTPUT_FORMAT, Reply, load_checkpoint, save_checkpoint
from unattended.ledger import read_calls
from unattended.limits import Bounds, Metrics, Outcome, OutcomeKind
from unattended.pricing import Usage
from unattended.prompt_job import PromptJob
from unattended.store import (
    DEFAULT_RESUME_PROMPT,
    EVENTS_FILE,
    HEARTBEAT_ENV,
    HEARTBEAT_FILE,
    OUTPUT_FILE,
    Job,
    JobKind,
    ResumeFrom,
    Spec,
)
from unattended.transcript import Transcript
from unattended.watch import RunWatch

from .conftest import MakeJob
from .fakes import GOOD, FakeClient, Sleep, Tool

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
    assert options.env == {ENV_VAR: "k", **RunWatch(job).env()}
    assert options.env[HEARTBEAT_ENV] == str(job.path(HEARTBEAT_FILE))


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


def test_a_message_reaches_the_agent_after_its_next_step(job: Job) -> None:
    fake = FakeClient([init(), Tool(), result()])
    posts = ["check the logs"]
    fake.on_message.append(lambda: posts and inbox.queue_message(job, posts.pop()))
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    context = fake.replies[0]["hookSpecificOutput"]["additionalContext"]
    assert context.endswith("check the logs")
    assert inbox.count_messages(job) == 0


def test_a_waiting_message_goes_with_the_next_prompt(job: Job) -> None:
    inbox.queue_message(job, "use the staging data")
    fake = FakeClient([result()])
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert fake.calls[0]["prompt"].startswith("Reply pong\n\nMessage from the operator")
    assert fake.calls[0]["prompt"].endswith("use the staging data")


def test_each_api_response_lands_in_the_ledger_once(job: Job) -> None:
    messages = [init(), spent("claude-opus-5-5", "m1", 5), spent("claude-opus-5-5", "m1", 9)]
    messages += [spent("claude-haiku-5-5", "m2", 7), result()]
    PromptJob(job, {}, FakeClient(messages)).run_once(RunWatch(job))
    calls = read_calls(job)
    assert [(c["message_id"], c["tokens"]["output"]) for c in calls] == [("m1", 9), ("m2", 7)]
    assert {c["run"] for c in calls} == {1}


def test_a_crashed_run_still_writes_its_last_response(job: Job) -> None:
    fake = FakeClient([init(), spent("claude-opus-5-5", "m1", 5)], RuntimeError("crash"))
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert [c["message_id"] for c in read_calls(job)] == ["m1"]


def capped(job: Job, bounds: Bounds) -> None:
    job.update(lambda st: setattr(st, "bounds", bounds))


def test_the_cli_budget_is_the_tighter_of_job_and_run_caps(job: Job) -> None:
    capped(job, Bounds(max_cost=5.0, max_run_cost=0.5))
    fake = FakeClient([result()])
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert fake.calls[0]["options"].max_budget_usd == 0.5


def test_a_run_cap_ends_the_run_at_its_next_step(job: Job) -> None:
    capped(job, Bounds(max_run_cost=1.0))
    script = [init(), spent("claude-opus-5-5", "m1", 60_000), Tool(), Tool(), result()]
    fake = FakeClient(script)
    outcome = PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert outcome.kind is OutcomeKind.BUDGET
    assert outcome.reason == "run cost ~$1.20 reached the $1.00 run cap"
    assert len(fake.replies) == 1


def test_a_job_cap_counts_the_ended_runs(job: Job) -> None:
    capped(job, Bounds(max_cost=1.0))
    job.update(lambda st: setattr(st, "cost", 0.9))
    fake = FakeClient([init(), spent("claude-opus-5-5", "m1", 10_000), Tool(), said("never")])
    outcome = PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert outcome == Outcome(
        OutcomeKind.BUDGET, "cost ~$1.10 reached the $1.00 cap", outcome.metrics
    )
    assert fake.replies[0]["continue_"] is False


def test_under_the_caps_the_run_goes_on(job: Job) -> None:
    capped(job, Bounds(max_cost=100.0, max_run_cost=50.0))
    fake = FakeClient([init(), spent("claude-opus-5-5", "m1", 10), Tool(), result()])
    assert PromptJob(job, {}, fake).run_once(RunWatch(job)).kind is OutcomeKind.DONE


def test_an_output_bound_reaches_the_cli(job: Job) -> None:
    job.update(lambda st: setattr(st.spec, "max_output_tokens", 4000))
    fake = FakeClient([result()])
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert fake.calls[0]["options"].env[prompt_job.OUTPUT_ENV] == "4000"


def wrap_up_events(job: Job) -> list[dict[str, Any]]:
    lines = job.path(EVENTS_FILE).read_text().splitlines()
    return [e for e in map(json.loads, lines) if e["event"].startswith("wrap-up")]


def over_the_run_cap(job: Job, wrap_up: float | None) -> FakeClient:
    capped(job, Bounds(max_run_cost=1.0, wrap_up=wrap_up))
    return FakeClient([init(), spent("claude-opus-5-5", "m1", 60_000), Tool(), result()])


def test_a_capped_run_gets_one_wrap_up_reply(job: Job) -> None:
    fake = over_the_run_cap(job, 0.5)
    fake.scripts.append([said("summary so far"), result("summary so far")])
    outcome = PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert outcome.kind is OutcomeKind.BUDGET
    assert len(fake.calls) == 2
    assert "run cost ~$1.20 reached the $1.00 run cap" in fake.calls[1]["prompt"]
    assert job.path(OUTPUT_FILE).read_text() == "summary so far\n"
    assert wrap_up_events(job)[0]["allowance"] == 0.5


def test_the_wrap_up_turn_cannot_call_tools(job: Job) -> None:
    fake = over_the_run_cap(job, 0.5)
    fake.scripts.append([Tool("Edit"), said("done"), result("done")])
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert len(fake.denials) == 1
    assert fake.denials[0]["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_the_wrap_up_allowance_is_a_hard_kill(job: Job) -> None:
    fake = over_the_run_cap(job, 0.5)
    fake.scripts.append([spent("claude-opus-5-5", "w1", 30_000), said("never"), result()])
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert fake.interrupts == 1
    assert [e["event"] for e in wrap_up_events(job)] == ["wrap-up", "wrap-up-cut"]


def test_no_wrap_up_without_an_allowance(job: Job) -> None:
    fake = over_the_run_cap(job, None)
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert len(fake.calls) == 1


def test_no_wrap_up_for_a_run_that_ended_by_itself(job: Job) -> None:
    capped(job, Bounds(wrap_up=0.5))
    fake = FakeClient([init(), Tool(), result()])
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert len(fake.calls) == 1


def test_a_graceful_stop_gets_the_wrap_up_too(job: Job) -> None:
    job.update(lambda st: setattr(st, "bounds", Bounds(deadline=1000.0, wrap_up=0.2)))
    watch = RunWatch(job, time.time, 0.01)
    fake = FakeClient([init(), Sleep(0.05), Tool(), result()])
    fake.scripts.append([result("handover")])
    PromptJob(job, {}, fake).run_once(watch)
    assert "deadline (graceful)" in fake.calls[1]["prompt"]


def test_the_cli_backstop_leaves_room_for_the_wrap_up(job: Job) -> None:
    capped(job, Bounds(max_run_cost=1.0, wrap_up=0.25))
    fake = FakeClient([result()])
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert fake.calls[0]["options"].max_budget_usd == 1.25


def checkpointing(job: Job) -> None:
    job.update(lambda st: setattr(st.spec, "resume_from", ResumeFrom.CHECKPOINT))


def structured(value: Any) -> ResultMessage:
    found = result("{}")
    found.structured_output = value
    return found


def test_checkpoint_mode_asks_for_the_schema_and_keeps_the_reply(job: Job) -> None:
    checkpointing(job)
    fake = FakeClient([init(), structured(GOOD)])
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    options = fake.calls[0]["options"]
    assert options.output_format == OUTPUT_FORMAT
    assert load_checkpoint(job)["goal"] == GOOD["goal"]


def test_a_later_run_starts_fresh_from_the_checkpoint(job: Job) -> None:
    checkpointing(job)
    job.update(lambda st: setattr(st, "session_id", "old"))
    save_checkpoint(job, Reply(1, GOOD))
    fake = FakeClient([result()])
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    call = fake.calls[0]
    assert call["options"].resume is None
    assert call["prompt"].startswith(DEFAULT_RESUME_PROMPT + "\n\nCheckpoint from the previous run")


def test_without_a_checkpoint_the_job_prompt_runs_again(job: Job) -> None:
    checkpointing(job)
    job.update(lambda st: setattr(st, "session_id", "old"))
    fake = FakeClient([result()])
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert fake.calls[0]["prompt"] == "Reply pong"
    assert '"event": "checkpoint-missing"' in job.path(EVENTS_FILE).read_text()


def test_session_mode_asks_for_no_schema_and_saves_none(job: Job) -> None:
    fake = FakeClient([structured(GOOD)])
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert fake.calls[0]["options"].output_format is None
    assert load_checkpoint(job) is None


def transcript_types(job: Job, run: int = 1) -> list[str]:
    lines = Transcript(job, run).path.read_text().splitlines()
    return [json.loads(line)["type"] for line in lines]


def test_a_run_writes_its_transcript(job: Job) -> None:
    PromptJob(job, {}, FakeClient([init(), said("x"), result()])).run_once(RunWatch(job))
    assert transcript_types(job) == ["prompt", "SystemMessage", "AssistantMessage", "ResultMessage"]


def test_a_crashed_run_keeps_its_transcript(job: Job) -> None:
    fake = FakeClient([init(), said("x")], RuntimeError("crash"))
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert transcript_types(job) == ["prompt", "SystemMessage", "AssistantMessage"]


def test_the_wrap_up_prompt_is_in_the_transcript(job: Job) -> None:
    fake = over_the_run_cap(job, 0.5)
    fake.scripts.append([result("summary")])
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert transcript_types(job).count("prompt") == 2


def test_options_carry_effort_tool_rules_and_scope(job: Job, workdir: Path) -> None:
    tuned = {"effort": "max", "allowed_tools": ["Read"], "disallowed_tools": ["Bash"]}
    tuned |= {"add_dirs": ["/data"], "setting_sources": ["project"]}
    job.update(lambda st: setattr(st, "spec", replace(st.spec, **tuned)))
    fake = FakeClient([result()])
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    options = fake.calls[0]["options"]
    assert (options.effort, options.add_dirs, options.setting_sources) == (
        "max",
        ["/data"],
        ["project"],
    )
    assert (options.allowed_tools, options.disallowed_tools) == (["Read"], ["Bash"])


def test_a_run_that_parks_ends_at_its_next_step(job: Job) -> None:
    fake = FakeClient([init(), Tool(), Tool(), result()])
    fake.on_message.append(lambda: job.path("park.json").write_text('{"check": "true"}'))
    PromptJob(job, {}, fake).run_once(RunWatch(job))
    assert len(fake.replies) == 1
    assert fake.replies[0]["continue_"] is False
    assert job.path("park.json").exists()
