"""s8: a usage limit, a crash or SIGTERM stops the runner cleanly with a status and a note."""

import asyncio
import json
import os
import signal
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from agile_team import (
    cli,
    halt,
    po_tools,
)
from agile_team import state as state_mod
from agile_team.dispatch import StepRequest
from agile_team.po_tools import Start, StartMode
from agile_team.relay import Relay
from agile_team.state import RunState, RunStatus
from claude_agent_sdk import AssistantMessage, ResultError, TextBlock

from .conftest import FakeQuery, result_message

LIMIT_TEXT = "You've hit your session limit · resets 2:20pm (America/Edmonton)"
LIMIT_REASON = "session limit, resets 2:20pm (America/Edmonton)"
RESUME_ADVICE = "run `agile-team start --resume` after the reset"
LIMIT_LINE = f"agile-team start: {LIMIT_REASON}; {RESUME_ADVICE}\n"


def limit_error(text: str = LIMIT_TEXT) -> ResultError:
    data = {"subtype": "success", "is_error": True, "session_id": "po-sess", "result": text}
    return ResultError(f"Claude Code returned an error result: {text}", data=data)


class RaisingQuery:
    """A fake query that yields ``before`` messages and then raises ``exc`` mid-stream."""

    def __init__(self, exc: BaseException, before: int = 1):
        self.exc, self.before, self.calls = exc, before, []

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        self.calls.append(prompt)
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        for _ in range(self.before):
            yield AssistantMessage(content=[TextBlock(text="working")], model="m")
        raise self.exc


class Router:
    """PO calls (those carrying MCP servers) go to ``po``; role calls to ``role``."""

    def __init__(self, po: Any, role: Any):
        self.po, self.role = po, role

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        target = self.po if options.mcp_servers else self.role
        return target(prompt=prompt, options=options)


class PoCallingRole:
    """A PO whose turn runs ``steps`` role steps, then ends normally or raises ``then``."""

    def __init__(self, rt_holder: list, steps: int = 1, then: BaseException | None = None):
        self.rt_holder, self.steps, self.then, self.reports = rt_holder, steps, then, []

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        for _ in range(self.steps):
            self.reports.append(await self.rt_holder[0].run_role(StepRequest("architect", "b")))
        if self.then:
            raise self.then
        yield result_message("PO text", session="po-sess")


def notes(rt) -> list:
    return Relay(rt.config.run_dir).messages()


def crash_log(rt) -> str:
    return (rt.config.run_dir / halt.CRASH_LOG).read_text()


def run_cli(rt, start: Start | None = None) -> int:
    return cli._run(rt, start or Start("task"))


# ----- classification (AC3) --------------------------------------------------


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        (LIMIT_TEXT, LIMIT_REASON),
        ("You've hit your weekly limit", "weekly limit"),
        ("Claude AI usage limit reached|1760000000", "usage limit reached"),
        ("HIT YOUR session LIMIT · resets 9am (UTC)", "session limit, resets 9am (UTC)"),
    ],
)
def test_limit_patterns_keep_reset_text(message: str, reason: str) -> None:
    found = halt.classify(limit_error(message))
    assert (found.kind, found.reason) == (halt.HaltKind.LIMIT, reason)


def test_reset_text_is_copied_not_computed() -> None:
    found = halt.classify(RuntimeError("You've hit your session limit · resets tomorrow-ish"))
    assert found.reason == "session limit, resets tomorrow-ish"


def test_group_wrapping_a_limit_classifies_as_limit() -> None:
    group = BaseExceptionGroup("g", [ValueError("x"), ExceptionGroup("n", [limit_error()])])
    assert halt.classify(group).reason == LIMIT_REASON


def test_limit_halt_is_none_for_other_errors() -> None:
    assert halt.limit_halt(ValueError("boom")) is None


def test_limit_beats_crash_and_sigterm_in_a_group() -> None:
    group = BaseExceptionGroup("g", [asyncio.CancelledError(), limit_error()])
    assert halt.classify(group).kind is halt.HaltKind.LIMIT


@pytest.mark.parametrize(
    ("exc", "kind", "reason"),
    [
        (ValueError("boom\nmore"), "crash", "crashed: ValueError: boom"),
        (ValueError(), "crash", "crashed: ValueError"),
        (ValueError("x" * 500), "crash", "crashed: ValueError: " + "x" * 200),
        (asyncio.CancelledError(), "sigterm", "stopped by stop --now"),
    ],
)
def test_crash_and_sigterm_classification(exc, kind: str, reason: str) -> None:
    found = halt.classify(exc)
    assert (found.kind, found.reason) == (kind, reason)


def test_halt_table_values() -> None:
    rules = {k: (r.status, r.note_kind, r.exit_code) for k, r in halt.HALTS.items()}
    assert rules == {
        halt.HaltKind.LIMIT: (RunStatus.BLOCKED, "blocked", 75),
        halt.HaltKind.CRASH: (RunStatus.FAILED, "failed", 70),
        halt.HaltKind.SIGTERM: (RunStatus.STOPPED, "stopped", 143),
    }


def test_halt_message_joins_reason_and_advice() -> None:
    found = halt.Halt(halt.HaltKind.LIMIT, LIMIT_REASON)
    assert found.message() == f"{LIMIT_REASON}; {RESUME_ADVICE}"


def test_log_traceback_appends_entries(tmp_path: Path) -> None:
    run_dir = tmp_path / "new" / "run"
    for text in ("first", "second"):
        try:
            raise ValueError(text)
        except ValueError as exc:
            halt.log_traceback(run_dir, exc)
    log = (run_dir / "crash.log").read_text()
    assert log.count("--- ") == 2 and "ValueError" in log
    assert "Traceback" in log and "second" in log


# ----- PO session (AC1, AC2) -------------------------------------------------


def test_po_limit_stops_cleanly(make_runtime, capsys) -> None:
    rt = make_runtime(RaisingQuery(limit_error()))
    assert run_cli(rt) == 75
    saved = state_mod.load(rt.config.run_dir)
    assert (saved.status, saved.status_reason) == (RunStatus.BLOCKED, LIMIT_REASON)
    assert saved.po_session == "po-sess"
    last = notes(rt)[-1]
    assert (last.kind, last.text) == ("blocked", f"{LIMIT_REASON}; {RESUME_ADVICE}")
    out = capsys.readouterr()
    assert out.err == LIMIT_LINE and "Traceback" not in out.out
    assert "ResultError" in crash_log(rt)
    assert not (rt.config.run_dir / state_mod.PID_FILE).exists()


def test_po_crash_is_failed(make_runtime, capsys) -> None:
    rt = make_runtime(RaisingQuery(RuntimeError("boom")))
    assert run_cli(rt) == 70
    saved = state_mod.load(rt.config.run_dir)
    assert (saved.status, saved.status_reason) == (RunStatus.FAILED, "crashed: RuntimeError: boom")
    assert [(m.kind, "boom" in m.text) for m in notes(rt)] == [("failed", True)]
    err = capsys.readouterr().err
    assert err.startswith("agile-team start: crashed: RuntimeError: boom;")
    assert "crash.log" in err and "Traceback" not in err
    assert "RuntimeError: boom" in crash_log(rt) and "Traceback" in crash_log(rt)
    assert not (rt.config.run_dir / state_mod.PID_FILE).exists()


def test_sigterm_stops_the_po(make_runtime, capsys) -> None:
    class KillSelf:
        def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
            return self._gen()

        async def _gen(self) -> AsyncIterator[Any]:
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.sleep(10)
            yield  # pragma: no cover

    rt = make_runtime(KillSelf())
    assert run_cli(rt) == 143
    saved = state_mod.load(rt.config.run_dir)
    assert (saved.status, saved.status_reason) == (RunStatus.STOPPED, "stopped by stop --now")
    assert [m.kind for m in notes(rt)] == ["stopped"]
    assert capsys.readouterr().err.startswith("agile-team start: stopped by stop --now;")
    assert not (rt.config.run_dir / state_mod.PID_FILE).exists()


def test_normal_run_still_exits_zero(make_runtime, capsys) -> None:
    rt = make_runtime(FakeQuery("fine"))
    assert run_cli(rt) == 0
    assert "fine" in capsys.readouterr().out and notes(rt) == []


# ----- role step (AC1) -------------------------------------------------------


def test_role_limit_returns_halted_report(make_runtime) -> None:
    rt = make_runtime(RaisingQuery(limit_error()))
    report = asyncio.run(rt.run_role(StepRequest("architect", "b")))
    assert report["status"] == "halted" and report["role"] == "architect"
    assert report["reason"] == LIMIT_REASON
    assert (rt.state.status, rt.state.status_reason) == (RunStatus.BLOCKED, LIMIT_REASON)
    saved = state_mod.load(rt.config.run_dir)
    assert (saved.status, saved.status_reason) == (RunStatus.BLOCKED, LIMIT_REASON)
    assert [(m.kind, m.text) for m in notes(rt)] == [
        ("blocked", f"{LIMIT_REASON}; {RESUME_ADVICE}")
    ]
    assert "ResultError" in crash_log(rt)


def test_role_limit_leaves_later_steps_refused(make_runtime) -> None:
    rt = make_runtime(RaisingQuery(limit_error()))
    asyncio.run(rt.run_role(StepRequest("architect", "b")))
    again = asyncio.run(rt.run_role(StepRequest("architect", "b")))
    assert again["reason"] == f"the run is blocked ({LIMIT_REASON}); end your turn"


def test_refusal_without_reason_is_unchanged(make_runtime) -> None:
    rt = make_runtime()
    rt.state.status = RunStatus.BLOCKED
    again = asyncio.run(rt.run_role(StepRequest("architect", "b")))
    assert again["reason"] == "the run is blocked; end your turn"


def test_role_non_limit_error_propagates_unchanged(make_runtime) -> None:
    rt = make_runtime(RaisingQuery(ValueError("boom")))
    rt.state.status = RunStatus.RUNNING
    with pytest.raises(ValueError, match="boom"):
        asyncio.run(rt.run_role(StepRequest("architect", "b")))
    assert rt.state.status is RunStatus.RUNNING and notes(rt) == []
    assert "ValueError: boom" in crash_log(rt)


def test_role_limit_through_the_po_reaches_exit_75(make_runtime, capsys) -> None:
    holder: list = []
    po = PoCallingRole(holder)
    rt = make_runtime(Router(po, RaisingQuery(limit_error())))
    holder.append(rt)
    assert run_cli(rt) == 75
    out = capsys.readouterr()
    assert "PO text" in out.out and out.err == LIMIT_LINE
    assert po.reports[0]["status"] == "halted"
    saved = state_mod.load(rt.config.run_dir)
    assert (saved.status, saved.status_reason) == (RunStatus.BLOCKED, LIMIT_REASON)
    assert [m.kind for m in notes(rt)] == ["blocked"]


def test_role_limit_then_po_limit_posts_one_note(make_runtime, capsys) -> None:
    holder: list = []
    po = PoCallingRole(holder, then=limit_error())
    rt = make_runtime(Router(po, RaisingQuery(limit_error())))
    holder.append(rt)
    assert run_cli(rt) == 75
    assert [m.kind for m in notes(rt)] == ["blocked"]
    assert capsys.readouterr().err == LIMIT_LINE
    assert state_mod.load(rt.config.run_dir).status is RunStatus.BLOCKED


def test_first_halt_wins(make_runtime) -> None:
    rt = make_runtime()
    first = halt.Halt(halt.HaltKind.LIMIT, LIMIT_REASON)
    assert rt.halt_run(first) is first
    rt.state.status = RunStatus.IDLE
    again = rt.halt_run(halt.Halt(halt.HaltKind.CRASH, "crashed: X"))
    assert again is first and rt.halted_by is first
    assert (rt.state.status, rt.state.status_reason) == (RunStatus.BLOCKED, LIMIT_REASON)
    assert len(notes(rt)) == 1


# ----- resume (AC4) ------------------------------------------------------------


@pytest.mark.parametrize("status", [RunStatus.BLOCKED, RunStatus.FAILED, RunStatus.STOPPED])
def test_resume_clears_status_and_is_not_refused(make_runtime, status: RunStatus) -> None:
    holder: list = []
    po = PoCallingRole(holder)
    rt = make_runtime(Router(po, FakeQuery()))
    holder.append(rt)
    rt.state.po_session = "po-sess"
    rt.state.mark(status, "some reason")
    asyncio.run(po_tools.run_po(rt, Start("", StartMode.RESUME)))
    assert po.reports[0].get("status") != "refused" and "reason" not in po.reports[0]
    assert (rt.state.status, rt.state.status_reason) == (RunStatus.IDLE, None)
    saved = state_mod.load(rt.config.run_dir)
    assert (saved.status, saved.status_reason) == (RunStatus.IDLE, None)


def test_resume_after_cli_limit_stop(make_runtime) -> None:
    rt = make_runtime(RaisingQuery(limit_error()))
    assert run_cli(rt) == 75
    rt.query_fn = FakeQuery("back")
    assert run_cli(rt, Start("", StartMode.RESUME)) == 0
    assert rt.query_fn.calls[0]["options"].resume == "po-sess"
    saved = state_mod.load(rt.config.run_dir)
    assert (saved.status, saved.status_reason) == (RunStatus.IDLE, None)


def test_po_halt_during_run_survives_record(make_runtime) -> None:
    """A status set by a halt while the PO runs is not overwritten with idle."""
    holder: list = []
    po = PoCallingRole(holder)
    rt = make_runtime(Router(po, RaisingQuery(limit_error())))
    holder.append(rt)
    asyncio.run(po_tools.run_po(rt, Start("t")))
    assert (rt.state.status, rt.state.status_reason) == (RunStatus.BLOCKED, LIMIT_REASON)


# ----- state and status (AC5) ----------------------------------------------------


def test_status_reason_defaults_and_round_trips() -> None:
    old = json.loads(RunState().to_json())
    del old["status_reason"]
    assert RunState.from_json(json.dumps(old)).status_reason is None
    st = RunState()
    st.mark(RunStatus.BLOCKED, LIMIT_REASON)
    back = RunState.from_json(st.to_json())
    assert (back.status, back.status_reason) == (RunStatus.BLOCKED, LIMIT_REASON)


def test_mark_without_reason_clears_it() -> None:
    st = RunState()
    st.mark(RunStatus.FAILED, "why")
    st.mark(RunStatus.RUNNING)
    assert (st.status, st.status_reason) == (RunStatus.RUNNING, None)


def test_new_statuses_and_note_kinds() -> None:
    assert RunStatus("failed") is RunStatus.FAILED and RunStatus("stopped") is RunStatus.STOPPED
    from agile_team.relay import KINDS

    assert KINDS[-2:] == ("failed", "stopped")
    assert not RunState(status=RunStatus.FAILED).halted()


def test_status_command_shows_reason(configured: Path, capsys) -> None:
    st = RunState()
    st.mark(RunStatus.BLOCKED, LIMIT_REASON)
    state_mod.save(configured / ".team/run", st)
    assert cli.main(["--repo", str(configured), "status"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status_reason"] == LIMIT_REASON
    keys = list(report)
    assert keys[keys.index("status") + 1] == "status_reason"


def test_status_reason_is_null_when_none(configured: Path, capsys) -> None:
    assert cli.main(["--repo", str(configured), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["status_reason"] is None
