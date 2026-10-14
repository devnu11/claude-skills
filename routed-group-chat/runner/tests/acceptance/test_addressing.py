"""Acceptance: the addressing table in reference/protocol.md, through the CLI.

Each scenario drives ``group_chat.cli.run`` with a scripted model only.
"""

from __future__ import annotations

import json

import pytest

from ..conftest import Cli, FakeBackend

pytestmark = pytest.mark.acceptance


def speakers(out: str) -> list[str]:
    return [line.split(":", 1)[0][1:] for line in out.split("\n\n") if line]


def test_single_mention(cli: Cli) -> None:
    """`@manager, timeline?` -> manager."""
    # Given a new chat
    # When the human addresses the manager
    result = cli.say("@manager, timeline?")
    # Then only the manager answers
    assert result.code == 0
    assert speakers(result.out) == ["manager"]


def test_ordered_multi_mention_each_sees_the_other(cli: Cli, backend: FakeBackend) -> None:
    """`@po @manager thoughts?` -> po, then manager (each sees the other's reply)."""
    # Given a PO with a scripted view
    backend.replies = {"po": ["Cut search."]}
    # When the human addresses po then manager
    result = cli.say("@po @manager thoughts?")
    # Then po answers first and the manager's context holds po's reply
    assert speakers(result.out) == ["po", "manager"]
    assert '<turn speaker="po">\nCut search.\n</turn>' in backend.calls[1].prompt


def test_all_answers_in_roster_order(cli: Cli) -> None:
    """`@all status?` -> every role, roster order."""
    result = cli.say("@all status?")
    assert speakers(result.out) == ["manager", "po", "liaison"]


def test_unaddressed_message_is_sticky(cli: Cli) -> None:
    """`and the risks?` (no leading mention) -> whoever was addressed last."""
    # Given the human last addressed po and manager
    cli.say("@po @manager plan?")
    # When the next message has no leading mention
    result = cli.say("and the risks?")
    # Then the same roles answer, in the same order
    assert speakers(result.out) == ["po", "manager"]


def test_unaddressed_first_message_is_refused(cli: Cli, backend: FakeBackend) -> None:
    """First message has no mention -> refused, exit 2, nothing recorded."""
    result = cli.say("hello team")
    assert result.code == 2
    assert "@manager @po @liaison @all" in result.err
    assert result.out == ""
    assert backend.calls == []
    assert not cli.state_file.exists()


def test_unknown_name_is_refused(cli: Cli, backend: FakeBackend) -> None:
    """`@cto` is unknown -> refused, exit 2, nothing recorded."""
    # Given a chat with one exchange
    cli.say("@po hi")
    before = cli.state_file.read_text()
    calls = len(backend.calls)
    # When the human addresses an unknown role
    result = cli.say("@cto budget?")
    # Then it is refused with the valid names and the state is unchanged
    assert result.code == 2
    assert "unknown @cto" in result.err
    assert "@manager @po @liaison @all" in result.err
    assert cli.state_file.read_text() == before
    assert len(backend.calls) == calls


def test_mid_sentence_mention_does_not_route(cli: Cli) -> None:
    """Only mentions at the start of the message route. `ask @manager later` does not."""
    cli.say("@po hi")
    result = cli.say("ask @manager later")
    assert speakers(result.out) == ["po"]
    assert json.loads(cli.state_file.read_text())["last_addressed"] == ["po"]


def test_human_message_is_recorded_as_written(cli: Cli, backend: FakeBackend) -> None:
    """Routing is the human's: never add or change an @mention in their message."""
    cli.say("@po, @manager what now?")
    turns = json.loads(cli.state_file.read_text())["turns"]
    assert turns[0] == {"speaker": "human", "text": "@po, @manager what now?"}


def test_unknown_name_with_all_is_refused(cli: Cli, backend: FakeBackend) -> None:
    """`@cto` is unknown -> refused, exit 2, nothing recorded (even beside `@all`)."""
    result = cli.say("@all @cto status?")
    assert result.code == 2
    assert "unknown @cto" in result.err
    assert backend.calls == []
    assert not cli.state_file.exists()


def test_mentions_are_case_insensitive(cli: Cli) -> None:
    """addressing: "Mentions are case-insensitive." (`@Manager` routes to manager)."""
    result = cli.say("@Manager, timeline?")
    assert speakers(result.out) == ["manager"]


def test_punctuation_after_mention_routes(cli: Cli) -> None:
    """addressing: mentions are separated by spaces, commas or other punctuation."""
    assert speakers(cli.say("@po; @manager! plan?").out) == ["po", "manager"]


def test_sticky_role_removed_from_roster_is_refused(cli: Cli, backend: FakeBackend) -> None:
    """addressing: a sticky addressee no longer in the roster is dropped; if none remain the
    message is refused."""
    # Given liaison was addressed last
    cli.say("@liaison status?")
    # When the roster drops liaison
    text = cli.roster.read_text()
    cli.roster.write_text(text[: text.index('[[role]]\nname = "liaison"')])
    calls = len(backend.calls)
    # Then an unaddressed follow-up is refused with the valid names
    result = cli.say("and then?")
    assert result.code == 2
    assert "address someone first: @manager @po @all" in result.err
    assert len(backend.calls) == calls
