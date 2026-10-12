"""s62: ``agile-team tell`` queues a message for the PO; the router delivers it once (T1-T7)."""

import asyncio
import io
import json
from pathlib import Path

import pytest
from agile_team import cli, system
from agile_team import state as state_mod
from agile_team.git_ops import Git
from agile_team.po_tools import PoRun, Start, StartMode
from agile_team.router import Router
from agile_team.salvage import Interruption
from agile_team.state import RunState, RunStatus

from .conftest import FakeQuery
from .fake_system import FakeSystem
from .pipeline_helpers import Script, build
from .test_cli import any_tool, start_args
from .test_s47 import q
from .test_s61 import commit_file, detach, git, stored

LINE = "The human sent you a message ({id}): read .team/run/liaison/messages/{id}.md."


def messages_dir(run_dir: Path) -> Path:
    return run_dir / "liaison" / "messages"


# ----- RunState (T4, R1, legacy) -----------------------------------------------------


def test_state_round_trips_told_and_unsaved() -> None:
    from agile_team.salvage import Cause

    st = RunState(told=["t1"], unsaved=Cause.CHECKOUT)
    back = RunState.from_json(st.to_json())
    assert back.told == ["t1"] and back.unsaved is Cause.CHECKOUT


def test_legacy_state_loads_without_told_or_unsaved() -> None:
    data = json.loads(RunState().to_json())
    data.pop("told", None)
    data.pop("unsaved", None)
    back = RunState.from_json(json.dumps(data))
    assert back.told == [] and back.unsaved is None


# ----- cmd_tell (T1, T3) -------------------------------------------------------------


def tell(repo: Path, source: str) -> int:
    return cli.main(["--repo", str(repo), "tell", source])


def test_tell_from_a_file(configured: Path, scratch: Path, capsys) -> None:
    note = scratch / "note.md"
    system.write_text(note, "hello\n")
    assert tell(configured, str(note)) == 0
    assert capsys.readouterr().out.strip() == (
        "queued t1 for the PO: .team/run/liaison/messages/t1.md"
    )
    assert system.read_text(messages_dir(configured / ".team" / "run") / "t1.md") == "hello\n"


def test_tell_from_stdin(configured: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("from stdin\n"))
    assert tell(configured, "-") == 0
    assert "queued t1 for the PO" in capsys.readouterr().out
    assert system.read_text(messages_dir(configured / ".team" / "run") / "t1.md") == "from stdin\n"


@pytest.mark.parametrize("text", ["", "   \n\t\n"])
def test_tell_refuses_an_empty_message(configured: Path, scratch: Path, capsys, text) -> None:
    note = scratch / "note.md"
    system.write_text(note, text)
    assert tell(configured, str(note)) == 1
    assert capsys.readouterr().err.strip() == "agile-team tell: the message is empty"
    assert not system.exists(messages_dir(configured / ".team" / "run"))


def test_tell_refuses_an_unreadable_file(configured: Path, scratch: Path, capsys) -> None:
    missing = scratch / "nope.md"
    assert tell(configured, str(missing)) == 1
    err = capsys.readouterr().err.strip()
    assert err.startswith(f"agile-team tell: cannot read {missing}: ")


def test_tell_never_creates_or_changes_state(configured: Path, scratch: Path) -> None:
    run_dir = configured / ".team" / "run"
    note = scratch / "n.md"
    system.write_text(note, "x")
    assert tell(configured, str(note)) == 0
    assert not system.exists(run_dir / state_mod.STATE_FILE)
    state_mod.save(run_dir, RunState(status=RunStatus.RUNNING))
    before = system.read_text(run_dir / state_mod.STATE_FILE)
    assert tell(configured, str(note)) == 0
    assert system.read_text(run_dir / state_mod.STATE_FILE) == before


def test_tell_works_on_a_checkout_halt(configured: Path, scratch: Path) -> None:
    run_dir = stored(configured, status=RunStatus.CHECKOUT_CHANGED)
    note = scratch / "n.md"
    system.write_text(note, "x")
    assert tell(configured, str(note)) == 0
    assert state_mod.load(run_dir).status is RunStatus.CHECKOUT_CHANGED


def test_tell_is_a_registered_command() -> None:
    assert "tell" in [c.name for c in cli.COMMANDS]


# ----- delivery (T5) -----------------------------------------------------------------


def ready(make_runtime):
    rt = make_runtime()
    rt.state.delivered = []
    rt.record_checkout()
    return rt


def test_an_unread_message_ends_the_pass_once(make_runtime) -> None:
    rt = ready(make_runtime)
    rt.relay.tell("please change the plan")
    found = asyncio.run(Router(rt).advance())
    assert [k.value for k in found.kinds] == ["human_message"]
    assert found.lines == [LINE.format(id="t1")] and found.stories == []
    assert state_mod.load(rt.config.run_dir).told == ["t1"]
    again = asyncio.run(Router(rt).advance())
    assert "human_message" not in [k.value for k in again.kinds]
    assert LINE.format(id="t1") not in again.lines


def test_the_text_is_not_in_the_pass(make_runtime) -> None:
    rt = ready(make_runtime)
    rt.relay.tell("SECRET-WORDS")
    found = asyncio.run(Router(rt).advance())
    assert "SECRET-WORDS" not in "\n".join(found.lines)


def test_an_answer_and_a_message_share_one_pass(make_runtime) -> None:
    rt = ready(make_runtime)
    q(rt, "Which DB?", ["s1"])
    rt.relay.answer("m1", "sqlite")
    rt.relay.tell("also this")
    found = asyncio.run(Router(rt).advance())
    assert found.lines == ['The human answered m1 ("Which DB?"): sqlite', LINE.format(id="t1")]
    assert found.stories == ["s1"]


def test_two_messages_come_in_number_order(make_runtime) -> None:
    rt = ready(make_runtime)
    rt.relay.tell("a")
    rt.relay.tell("b")
    found = asyncio.run(Router(rt).advance())
    assert found.lines == [LINE.format(id="t1"), LINE.format(id="t2")]
    assert rt.state.told == ["t1", "t2"]


@pytest.fixture(autouse=True)
def tracked(configured: Path, fake: FakeSystem) -> None:
    """Model the repo: branch, HEAD, commits and the reflog follow git commands."""
    fake.track()


def test_a_message_wakes_a_waiting_run(make_runtime, fake: FakeSystem) -> None:
    rt = ready(make_runtime)
    q(rt, "Which DB?", ["s1"])
    slept = []

    def sleep() -> None:
        slept.append(rt.state.status_reason)
        rt.relay.tell("go on without it")

    fake.on_sleep = [sleep]
    found = asyncio.run(Router(rt).advance())
    assert slept == ["waiting on answers: s1 waits on m1"]
    assert [k.value for k in found.kinds] == ["human_message"]
    assert found.lines == [LINE.format(id="t1")]
    assert rt.state.status_reason is None


# ----- driver level (T5, T6, AC6) ----------------------------------------------------


def test_a_resumed_run_hands_the_message_to_the_pos_first_prompt(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script, steps=["design"])
    rt.state.po_session = "po-sess"
    rt.relay.tell("SECRET-WORDS")
    asyncio.run(PoRun(rt, Start("", StartMode.RESUME)).run())
    first = script.po_prompts[0]
    assert LINE.format(id="t1") in first and "SECRET-WORDS" not in first
    assert rt.state.told == ["t1"]


def test_a_message_waits_for_a_busy_po_turn(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script, steps=["design"])
    rt.state.po_session = "po-sess"
    rt.state.interrupted = [Interruption("developer-cli", "s1", "build it", "limit", "abc")]
    rt.relay.tell("later")
    asyncio.run(PoRun(rt, Start("", StartMode.RESUME)).run())
    first, second = script.po_prompts[:2]
    assert "## Interrupted steps" in first and LINE.format(id="t1") not in first
    assert LINE.format(id="t1") in second


def with_session(repo: Path, **kw) -> Path:
    run_dir = stored(repo, po_session="po-sess", **kw)
    return run_dir


def test_message_told_during_a_checkout_halt_arrives_after_accept(
    configured: Path, key_home: Path, scratch: Path, fake: FakeSystem
) -> None:
    any_tool(fake)
    with_session(configured, status=RunStatus.IDLE)
    commit_file(configured)
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery()) == 78
    note = scratch / "n.md"
    system.write_text(note, "while halted")
    assert tell(configured, str(note)) == 0
    assert cli.main(["--repo", str(configured), "--home", str(key_home), "accept-checkout"]) == 0
    fake = FakeQuery()
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), fake) == 0
    assert LINE.format(id="t1") in fake.calls[0]["prompt"]


def test_message_told_during_a_halt_arrives_after_restoring(
    configured: Path, key_home: Path, scratch: Path, fake: FakeSystem
) -> None:
    any_tool(fake)
    with_session(configured)
    detach(configured)
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery()) == 78
    note = scratch / "n.md"
    system.write_text(note, "while halted")
    assert tell(configured, str(note)) == 0
    git(configured, "checkout", "-q", "main")
    fake = FakeQuery()
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), fake) == 0
    assert LINE.format(id="t1") in fake.calls[0]["prompt"]


def test_the_line_follows_the_interrupted_turn_after_a_halt(
    configured: Path, key_home: Path, scratch: Path, fake: FakeSystem
) -> None:
    any_tool(fake)
    step = Interruption("developer-cli", "s1", "build it", "limit", "abc")
    with_session(configured, status=RunStatus.IDLE, interrupted=[step])
    commit_file(configured)
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery()) == 78
    note = scratch / "n.md"
    system.write_text(note, "x")
    tell(configured, str(note))
    cli.main(["--repo", str(configured), "--home", str(key_home), "accept-checkout"])
    fake = FakeQuery()
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), fake) == 0
    first, second = fake.calls[0]["prompt"], fake.calls[1]["prompt"]
    assert "## Interrupted steps" in first and LINE.format(id="t1") not in first
    assert LINE.format(id="t1") in second
    assert Git(configured).is_clean()


# ----- status (T7) -------------------------------------------------------------------


def test_status_lists_the_queued_messages(configured: Path, capsys, make_runtime) -> None:
    rt = ready(make_runtime)
    rt.relay.tell("x")
    rt.save()
    assert cli.main(["--repo", str(configured), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["queued_messages"] == ["t1"]
    asyncio.run(Router(rt).advance())
    assert cli.main(["--repo", str(configured), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["queued_messages"] == []


def test_status_has_no_queue_by_default(configured: Path, capsys) -> None:
    assert cli.main(["--repo", str(configured), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["queued_messages"] == []
