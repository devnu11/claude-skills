"""Acceptance: exit codes, the chat lock and model failures, through the CLI.

Rules quoted from the ``cli``, ``chat`` and ``state`` module docs; the model is scripted.
"""

from __future__ import annotations

import json

import pytest

from ..conftest import Cli, FailingBackend, FakeBackend

pytestmark = pytest.mark.acceptance


def failing(cli: Cli, fail_roles: frozenset[str] = frozenset(), fail_summary: bool = False) -> Cli:
    """The same chat, with a model that fails for ``fail_roles`` or the summary."""
    backend = FailingBackend(fail_roles=set(fail_roles), fail_summary=fail_summary)
    return Cli(cli.roster, cli.directory, backend)


def test_held_lock_exits_2_and_records_nothing(cli: Cli, backend: FakeBackend) -> None:
    """state: "two `say` calls cannot interleave; the second is refused, not queued."
    cli: "2 a usage problem (bad roster, bad address, bad or locked state)"."""
    # Given another group-chat holds the lock
    cli.directory.mkdir(parents=True)
    (cli.directory / "lock").write_text("")
    # When the human says something
    result = cli.say("@po hi")
    # Then it is refused and nothing is recorded or called
    assert result.code == 2
    assert "lock exists: another group-chat is using this chat" in result.err
    assert not cli.state_file.exists()
    assert backend.calls == []


def test_lock_released_after_success(cli: Cli) -> None:
    """state: `Store.locked` holds `<dir>/lock` for a whole message."""
    assert cli.say("@po hi").code == 0
    assert not (cli.directory / "lock").exists()
    assert cli.say("@po again").code == 0


def test_lock_released_after_failure(cli: Cli) -> None:
    """The lock is released after a failed message too."""
    assert failing(cli, fail_roles=frozenset({"po"})).say("@po hi").code == 1
    assert not (cli.directory / "lock").exists()
    assert cli.say("@po again").code == 0


def test_partial_failure_exits_1_and_keeps_work(cli: Cli) -> None:
    """cli: "1 a model call failed (replies that arrived are printed first)".
    chat: "a model failure never loses work already paid for"."""
    # Given the PO's model call will fail
    broken = failing(cli, fail_roles=frozenset({"po"}))
    # When the human addresses manager then po
    result = broken.say("@manager @po plan?")
    # Then the manager's reply is printed, the failure noted, and exit is 1
    assert result.code == 1
    assert result.out == (
        "@manager: manager reply\n\n@orchestrator: @po could not answer: overloaded\n\n"
    )
    assert result.err == "group-chat: model call failed: overloaded\n"
    # And the human turn and the manager's reply are on disk
    turns = json.loads(cli.state_file.read_text())["turns"]
    assert [t["speaker"] for t in turns] == ["human", "manager", "orchestrator"]


def test_summary_failure_keeps_turns_verbatim(cli: Cli) -> None:
    """chat: "Compaction is best-effort; if the summary call fails, the turns stay verbatim
    and the next message tries again"."""
    broken = failing(cli, fail_summary=True)
    for word in ("one", "two", "three"):
        result = broken.say(f"@po {word}", flags=["--recent-tokens", "1"])
    assert result.code == 0
    assert "@orchestrator: summary skipped, turns kept verbatim: overloaded" in result.out
    shown = cli.run("show").out
    assert shown.startswith("--- summary ---\n(none)\n")
    assert "@human: @po one" in shown
    cli.say("@po four", flags=["--recent-tokens", "1"])
    assert cli.run("show").out.startswith("--- summary ---\nSUMMARY\n")


def test_corrupt_state_exits_2(cli: Cli) -> None:
    """cli: exit 2 for "bad or locked state"."""
    cli.directory.mkdir(parents=True)
    cli.state_file.write_text("{oops")
    for command in (["log"], ["show"], ["say", "@po hi"]):
        result = cli.run(*command)
        assert result.code == 2
        assert "state.json is unreadable or malformed" in result.err


def test_chat_keeps_going_after_failures(cli: Cli) -> None:
    """cli: `chat` reads messages from stdin; errors are reported and skipped."""
    broken = failing(cli, fail_roles=frozenset({"po"}))
    result = broken.run("chat", stdin="@po hi\nnobody?\n@cto x\n@manager hi\n/quit\n")
    assert result.code == 0
    assert result.err.count("group-chat:") == 3
    assert result.out.endswith("@manager: manager reply\n\n")
