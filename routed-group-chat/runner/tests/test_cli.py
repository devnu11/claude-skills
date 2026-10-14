"""Unit tests for ``cli``: argument handling and output, with a scripted backend."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from group_chat.backend import BackendError
from group_chat.cli import Io, main, run

from .conftest import FakeBackend

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
    assert "@human: @po two words" in backend.calls[0].prompt


def test_backend_error_is_a_usage_error(roster_file: Path) -> None:
    class Failing:
        def complete(self, system: str, prompt: str, model: str | None) -> str:
            raise BackendError("rate limited")

    chat_io = Io(io.StringIO(), io.StringIO(), io.StringIO(), Failing)
    assert run(args(roster_file, "say", "@po hi"), chat_io) == 2
    assert "group-chat: rate limited" in err(chat_io)


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


@pytest.mark.xfail(strict=True, reason="BUG: corrupt state.json crashes with a traceback")
def test_corrupt_state_is_a_usage_error(roster_file: Path, chat_io: Io) -> None:
    chat_dir = roster_file.parent / "chat"
    chat_dir.mkdir()
    (chat_dir / "state.json").write_text("{oops")
    assert run(args(roster_file, "log"), chat_io) == 2
