from __future__ import annotations

import io
from pathlib import Path

import pytest
from group_chat.cli import Io, main, run

from .conftest import FakeBackend


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
