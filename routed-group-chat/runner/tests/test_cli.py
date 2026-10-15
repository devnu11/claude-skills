"""Unit tests for ``cli``: argument handling and output, with a scripted backend."""

from __future__ import annotations

import io
import signal
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from claude_agent_sdk import CLINotFoundError
from group_chat.backend import BackendError, ClaudeBackend
from group_chat.cli import Io, exit_on_sigterm, main, parse_non_negative, run
from group_chat.state import Store

from .conftest import FailingBackend, FakeBackend

pytestmark = pytest.mark.unit


@pytest.fixture
def chat_io(backend: FakeBackend) -> Io:
    return Io(io.StringIO(), io.StringIO(), io.StringIO(), lambda: backend)


def args(roster_file: Path, *rest: str) -> list[str]:
    return ["--roster", str(roster_file), "--dir", str(roster_file.parent / "chat"), *rest]


def out(chat_io: Io) -> str:
    return chat_io.stdout.getvalue()  # type: ignore[attr-defined]


def err(chat_io: Io) -> str:
    return chat_io.stderr.getvalue()  # type: ignore[attr-defined]


def test_say_prints_replies(roster_file: Path, chat_io: Io) -> None:
    assert run(args(roster_file, "say", "@po", "scope?"), chat_io) == 0
    assert out(chat_io) == "@po: po reply\n\n"


def test_say_unaddressed_is_a_usage_error(roster_file: Path, chat_io: Io) -> None:
    assert run(args(roster_file, "say", "hello"), chat_io) == 2
    assert "address someone first" in err(chat_io)


def test_bad_roster_is_a_usage_error(tmp_path: Path, chat_io: Io) -> None:
    assert run(args(tmp_path / "none.toml", "say", "@po hi"), chat_io) == 2
    assert "none.toml" in err(chat_io)


def test_chat_reads_until_quit(roster_file: Path, backend: FakeBackend) -> None:
    stdin = io.StringIO("@manager hi\n\nwho?\n/quit\n@po never\n")
    chat_io = Io(stdin, io.StringIO(), io.StringIO(), lambda: backend)
    assert run(args(roster_file, "chat"), chat_io) == 0
    assert out(chat_io) == "@manager: manager reply\n\n@manager: manager reply\n\n"


def test_chat_warns_and_continues(roster_file: Path, backend: FakeBackend) -> None:
    stdin = io.StringIO("nobody\n@cto hi\n@po hi\n")
    chat_io = Io(stdin, io.StringIO(), io.StringIO(), lambda: backend)
    assert run(args(roster_file, "chat"), chat_io) == 0
    assert err(chat_io).count("group-chat:") == 2
    assert out(chat_io) == "@po: po reply\n\n"


def test_log_and_show(roster_file: Path, chat_io: Io) -> None:
    run(args(roster_file, "say", "@po DECISION: go"), chat_io)
    run(args(roster_file, "log"), chat_io)
    run(args(roster_file, "show"), chat_io)
    text = out(chat_io)
    assert "- [D1] go (by human)" in text
    assert "--- summary ---\n(none)" in text
    assert "@human: @po DECISION: go" in text


def test_limits_flags(roster_file: Path, chat_io: Io, backend: FakeBackend) -> None:
    backend.replies = {"po": ["HANDOFF: @manager"]}
    run(args(roster_file, "--max-handoffs", "0", "say", "@po x"), chat_io)
    assert "dropped" in out(chat_io)


def test_main_uses_sys_streams(
    roster_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(args(roster_file, "log")) == 0
    assert "## Decisions" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["group-chat", *args(roster_file, "show")])
    assert main() == 0


def test_say_joins_words(roster_file: Path, chat_io: Io, backend: FakeBackend) -> None:
    run(args(roster_file, "say", "@po", "two", "words"), chat_io)
    assert '<turn speaker="human">\n@po two words\n</turn>' in backend.calls[0].prompt


def test_backend_error_exits_1(roster_file: Path) -> None:
    class Failing:
        def complete(self, system: str, prompt: str, model: str | None) -> str:
            raise BackendError("rate limited")

    chat_io = Io(io.StringIO(), io.StringIO(), io.StringIO(), Failing)
    assert run(args(roster_file, "say", "@po hi"), chat_io) == 1
    assert "group-chat: model call failed: rate limited" in err(chat_io)
    assert out(chat_io) == "@orchestrator: @po could not answer: rate limited\n\n"


def test_recent_tokens_flag(roster_file: Path, chat_io: Io, backend: FakeBackend) -> None:
    for word in ("a", "b", "c"):
        run(args(roster_file, "--recent-tokens", "1", "say", f"@po {word}"), chat_io)
    assert backend.calls[-1].prompt.startswith("--- EARLIER SUMMARY ---")


def test_missing_subcommand_exits_2(roster_file: Path, chat_io: Io) -> None:
    with pytest.raises(SystemExit) as exc:
        run(args(roster_file), chat_io)
    assert exc.value.code == 2


def test_log_and_show_on_new_chat(roster_file: Path, chat_io: Io) -> None:
    assert run(args(roster_file, "log"), chat_io) == 0
    assert run(args(roster_file, "show"), chat_io) == 0
    assert out(chat_io).endswith("--- summary ---\n(none)\n\n")
    assert not (roster_file.parent / "chat").exists()


def test_chat_quit_with_spaces(roster_file: Path, backend: FakeBackend) -> None:
    chat_io = Io(io.StringIO("  /quit  \n@po x\n"), io.StringIO(), io.StringIO(), lambda: backend)
    assert run(args(roster_file, "chat"), chat_io) == 0
    assert backend.calls == []


def test_corrupt_state_is_a_usage_error(roster_file: Path, chat_io: Io) -> None:
    chat_dir = roster_file.parent / "chat"
    chat_dir.mkdir()
    (chat_dir / "state.json").write_text("{oops")
    assert run(args(roster_file, "log"), chat_io) == 2


def test_partial_reply_prints_earlier_replies_and_exits_1(roster_file: Path) -> None:
    chat_io = Io(
        io.StringIO(), io.StringIO(), io.StringIO(), lambda: FailingBackend(fail_roles={"po"})
    )
    assert run(args(roster_file, "say", "@manager @po hi"), chat_io) == 1
    assert out(chat_io) == (
        "@manager: manager reply\n\n@orchestrator: @po could not answer: overloaded\n\n"
    )
    assert err(chat_io) == "group-chat: model call failed: overloaded\n"


def test_held_lock_exits_2(roster_file: Path, chat_io: Io, backend: FakeBackend) -> None:
    chat_dir = roster_file.parent / "chat"
    chat_dir.mkdir()
    (chat_dir / "lock").write_text("")
    assert run(args(roster_file, "say", "@po hi"), chat_io) == 2
    assert "held by another process" in err(chat_io)
    assert backend.calls == []


@pytest.mark.parametrize("flag", ["--max-handoffs", "--recent-tokens"])
def test_negative_limit_is_refused(
    roster_file: Path, chat_io: Io, flag: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        run(args(roster_file, flag, "-1", "say", "@po hi"), chat_io)
    assert exc.value.code == 2
    assert "must be >= 0, got -1" in capsys.readouterr().err


def test_non_integer_limit_is_refused(roster_file: Path, chat_io: Io) -> None:
    with pytest.raises(SystemExit):
        run(args(roster_file, "--max-handoffs", "two", "say", "@po hi"), chat_io)


@pytest.mark.parametrize("text", ["0", "7"])
def test_non_negative_accepts(text: str) -> None:
    assert parse_non_negative(text) == int(text)


@pytest.mark.parametrize("command", ["log", "show"])
def test_log_and_show_validate_roster(tmp_path: Path, chat_io: Io, command: str) -> None:
    assert run(args(tmp_path / "missing.toml", command), chat_io) == 2
    assert "missing.toml" in err(chat_io)


def test_log_on_corrupt_state_names_the_file(roster_file: Path, chat_io: Io) -> None:
    chat_dir = roster_file.parent / "chat"
    chat_dir.mkdir()
    (chat_dir / "state.json").write_text("[]")
    assert run(args(roster_file, "show"), chat_io) == 2
    assert "state.json is malformed: state must be a table" in err(chat_io)


def test_chat_continues_after_partial_failure_and_lock(roster_file: Path) -> None:
    backend = FailingBackend(fail_roles={"po"})
    stdin = io.StringIO("@po hi\n@manager hi\n")
    chat_io = Io(stdin, io.StringIO(), io.StringIO(), lambda: backend)
    assert run(args(roster_file, "chat"), chat_io) == 0
    assert "model call failed: overloaded" in err(chat_io)
    assert out(chat_io).endswith("@manager: manager reply\n\n")


def test_chat_warns_on_held_lock(roster_file: Path, backend: FakeBackend) -> None:
    chat_dir = roster_file.parent / "chat"
    chat_dir.mkdir()
    (chat_dir / "lock").write_text("")
    chat_io = Io(io.StringIO("@po a\n@po b\n"), io.StringIO(), io.StringIO(), lambda: backend)
    assert run(args(roster_file, "chat"), chat_io) == 0
    assert err(chat_io).count("held by another process") == 2


@pytest.mark.parametrize(("signum", "code"), [(signal.SIGTERM, 128 + 15), (2, 130)])
def test_exit_on_sigterm_raises_system_exit(signum: int, code: int) -> None:
    with pytest.raises(SystemExit) as exc:
        exit_on_sigterm(signum, None)
    assert exc.value.code == code


def test_main_installs_sigterm_handler(roster_file: Path) -> None:
    previous = signal.getsignal(signal.SIGTERM)
    try:
        main(args(roster_file, "log"))
        assert signal.getsignal(signal.SIGTERM) is exit_on_sigterm
    finally:
        signal.signal(signal.SIGTERM, previous)


def test_sigterm_handler_releases_lock(roster_file: Path) -> None:
    store = Store(roster_file.parent / "chat")
    with pytest.raises(SystemExit), store.hold_lock():
        exit_on_sigterm(signal.SIGTERM, None)
    assert not store.lockfile.exists()


def test_sdk_error_exits_1_end_to_end(roster_file: Path) -> None:
    async def query_fn(**_kwargs: object) -> AsyncIterator[object]:
        raise CLINotFoundError("Claude Code not found")
        yield  # pragma: no cover

    chat_io = Io(io.StringIO(), io.StringIO(), io.StringIO(), lambda: ClaudeBackend(query_fn))
    assert run(args(roster_file, "say", "@po hi"), chat_io) == 1
    assert out(chat_io) == (
        "@orchestrator: @po could not answer: CLINotFoundError: Claude Code not found\n\n"
    )
    assert "model call failed: CLINotFoundError" in err(chat_io)
