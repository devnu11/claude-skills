"""s8 end to end: limits, crashes and SIGTERM through ``cli.cmd_start`` with a fake query."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from collections.abc import AsyncIterator
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from agile_team import cli, halt, preflight
from agile_team import state as state_mod
from agile_team.dispatch import Runtime, StepRequest
from agile_team.events import EventKind
from agile_team.po_tools import Tools
from agile_team.relay import Relay
from claude_agent_sdk import AssistantMessage, ResultError, TextBlock

from ..conftest import FakeQuery, git, result_message

LIMIT_TEXT = "You\u2019ve hit your session limit \u00b7 resets 2:20pm (America/Edmonton)"
REASON = "session limit, resets 2:20pm (America/Edmonton)"
ADVICE = "run `agile-team start --resume` after the reset"


def sdk_limit_error(text: str = LIMIT_TEXT) -> ResultError:
    """Built the way the SDK builds it (query.py), including the exit code."""
    data = {"subtype": "success", "is_error": True, "session_id": "po-sess", "result": text}
    return ResultError(f"Claude Code returned an error result: {text}", data=data, exit_code=1)


class Raiser:
    """A query that yields one message, then raises."""

    def __init__(self, exc: BaseException):
        self.exc = exc

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        yield AssistantMessage(content=[TextBlock(text="working")], model="m")
        raise self.exc


class RoleWritesThenLimit:
    """A role step that edits one in-scope and one out-of-scope file, then hits the limit."""

    def __init__(self, repo: Path):
        self.repo = repo

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        (self.repo / "docs").mkdir(exist_ok=True)
        (self.repo / "docs" / "design.md").write_text("partial design\n")
        (self.repo / "src" / "oops.py").write_text("y = 2\n")
        yield AssistantMessage(content=[TextBlock(text="working")], model="m")
        raise sdk_limit_error()


class PoRunsRole:
    """A PO turn: open a story, start a sprint, run one role step, end normally."""

    def __init__(self, holder: list[Runtime]):
        self.holder, self.reports = holder, []

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        rt = self.holder[0]
        tools = Tools(rt)
        await tools.open_story({"id": "s1", "title": "S1"})
        await tools.start_sprint({"goal": "g", "stories": ["s1"]})
        rt.state.manager_due.clear()  # skip the sprint-start manager review
        self.reports.append(await rt.run_role(StepRequest("architect", "design it", "s1")))
        yield result_message("PO text", session="po-sess")


class Router:
    """PO calls (carrying MCP servers) go to ``po``; role calls to ``role``."""

    def __init__(self, po: Any, role: Any):
        self.po, self.role = po, role

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        return (self.po if options.mcp_servers else self.role)(prompt=prompt, options=options)


@pytest.fixture
def harness(configured: Path, key_home: Path, monkeypatch: pytest.MonkeyPatch):
    """Run ``cmd_start`` for real; capture the Runtime it builds."""
    monkeypatch.setattr(cli, "Preflight", partial(preflight.Preflight, which=lambda e: e))
    holder: list[Runtime] = []
    real = cli.make_runtime

    def capture(place, query_fn) -> Runtime:
        holder.append(real(place, query_fn))
        return holder[0]

    monkeypatch.setattr(cli, "make_runtime", capture)

    def start(query_fn, *extra: str) -> int:
        holder.clear()
        argv = ["--repo", str(configured), "--home", str(key_home), "start", *extra]
        return cli.cmd_start(cli.build_parser().parse_args(argv), query_fn)

    return start, holder


def run_dir(repo: Path) -> Path:
    return repo / ".team" / "run"


def saved(repo: Path) -> state_mod.RunState:
    return state_mod.load(run_dir(repo))


def notes(repo: Path) -> list:
    return Relay(run_dir(repo)).messages()


# (1) exact limit reason through the real entry point


def test_po_limit_exact_reason_everywhere(harness, configured: Path, capsys) -> None:
    start, _ = harness
    assert start(Raiser(sdk_limit_error()), "--task", "t") == 75
    st = saved(configured)
    assert (st.status, st.status_reason) == (state_mod.RunStatus.BLOCKED, REASON)
    assert st.po_session == "po-sess"
    note = notes(configured)[-1]
    assert (note.kind, note.text) == ("blocked", f"{REASON}; {ADVICE}")
    out = capsys.readouterr()
    assert out.err == f"agile-team start: {REASON}; {ADVICE}\n"
    assert "Traceback" not in out.out + out.err
    assert not (run_dir(configured) / state_mod.PID_FILE).exists()


# (2) reason extraction with SDK suffixes


@pytest.mark.parametrize(
    "message",
    [
        f"{LIMIT_TEXT} (exit code: 1)",
        f"{LIMIT_TEXT}; other error",
        f"other error; {LIMIT_TEXT}",
        f"{LIMIT_TEXT}; other error (exit code: 1)",
    ],
)
def test_reason_extraction_with_suffixes(message: str) -> None:
    found = halt.classify(RuntimeError(message))
    assert (found.kind, found.reason) == (halt.HaltKind.LIMIT, REASON)


def test_real_sdk_error_str_ends_with_exit_code_but_reason_does_not() -> None:
    exc = sdk_limit_error()
    assert str(exc).endswith("(exit code: 1)")
    assert halt.classify(exc).reason == REASON


# (3) a halted role step leaves its partial edits alone


def test_halted_role_step_leaves_tree_untouched(harness, configured: Path, capsys) -> None:
    start, holder = harness
    po = PoRunsRole(holder)
    head = git(configured, "rev-parse", "HEAD")
    assert start(Router(po, RoleWritesThenLimit(configured)), "--task", "t") == 75
    assert po.reports[0]["status"] == "halted"
    assert git(configured, "rev-parse", "HEAD") == head
    porcelain = git(configured, "status", "--porcelain")
    assert "docs/" in porcelain and "src/oops.py" in porcelain
    assert (configured / "docs" / "design.md").read_text() == "partial design\n"
    events = holder[0].events.events()
    assert not [e for e in events if e.kind == EventKind.QUARANTINE]
    story = saved(configured).stories["s1"]
    assert (story.step, story.rounds) == (holder[0].pipeline.first(), 0)
    st = saved(configured)
    assert (st.status, st.status_reason) == (state_mod.RunStatus.BLOCKED, REASON)
    assert [n.kind for n in notes(configured)] == ["blocked"]
    assert capsys.readouterr().err == f"agile-team start: {REASON}; {ADVICE}\n"


# (4) resume after a limit


def test_resume_after_limit_clears_status_and_is_not_refused(harness, configured: Path) -> None:
    start, holder = harness
    assert start(Raiser(sdk_limit_error()), "--task", "t") == 75
    assert saved(configured).status is state_mod.RunStatus.BLOCKED
    seen: dict[str, Any] = {}

    class ResumedPo:
        def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
            seen["resume"] = options.resume
            return self._gen()

        async def _gen(self) -> AsyncIterator[Any]:
            rt = holder[0]
            seen["status_during"] = (rt.state.status, rt.state.status_reason)
            seen["refusal"] = rt.refusal(StepRequest("manager", "b"))
            yield result_message("back", session="po-sess")

    assert start(ResumedPo(), "--resume") == 0
    assert seen["resume"] == "po-sess"
    assert seen["status_during"] == (state_mod.RunStatus.RUNNING, None)
    assert seen["refusal"] is None
    st = saved(configured)
    assert (st.status, st.status_reason) == (state_mod.RunStatus.IDLE, None)


# (5) crash and SIGTERM


def test_crash_exit_70_log_and_note(harness, configured: Path, capsys) -> None:
    start, _ = harness
    assert start(Raiser(RuntimeError("boom")), "--task", "t") == 70
    st = saved(configured)
    assert (st.status, st.status_reason) == (
        state_mod.RunStatus.FAILED,
        "crashed: RuntimeError: boom",
    )
    log = (run_dir(configured) / "crash.log").read_text()
    assert "Traceback" in log and "RuntimeError: boom" in log
    note = notes(configured)[-1]
    assert note.kind == "failed" and "boom" in note.text
    err = capsys.readouterr().err
    assert (
        err.startswith("agile-team start: crashed: RuntimeError: boom") and "Traceback" not in err
    )
    assert not (run_dir(configured) / state_mod.PID_FILE).exists()


def test_sigterm_exit_143_and_stopped(harness, configured: Path, capsys) -> None:
    start, _ = harness

    class KillSelf:
        def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
            return self._gen()

        async def _gen(self) -> AsyncIterator[Any]:
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.sleep(10)
            yield  # pragma: no cover

    assert start(KillSelf(), "--task", "t") == 143
    st = saved(configured)
    assert (st.status, st.status_reason) == (state_mod.RunStatus.STOPPED, "stopped by stop --now")
    assert [n.kind for n in notes(configured)] == ["stopped"]
    assert capsys.readouterr().err.startswith("agile-team start: stopped by stop --now")
    assert not (run_dir(configured) / state_mod.PID_FILE).exists()


def test_clean_run_still_exits_zero(harness, capsys) -> None:
    start, _ = harness
    assert start(FakeQuery("fine"), "--task", "t") == 0
    assert "fine" in capsys.readouterr().out


# (6) status shows the reason


def test_status_shows_reason_after_limit(harness, configured: Path, capsys) -> None:
    start, _ = harness
    assert start(Raiser(sdk_limit_error()), "--task", "t") == 75
    capsys.readouterr()
    assert cli.main(["--repo", str(configured), "status"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["status"], report["status_reason"]) == ("blocked", REASON)
    assert report["running"] is False
