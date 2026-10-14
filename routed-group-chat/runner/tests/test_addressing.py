from __future__ import annotations

import pytest
from group_chat.addressing import AddressError, leading_mentions, resolve

NAMES = ("manager", "po", "liaison")


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("@manager, what's the timeline?", ("manager",)),
        ("  @po @manager thoughts?", ("po", "manager")),
        ("@po,@po again", ("po",)),
        ("@all status?", NAMES),
        ("@po @all status?", NAMES),
    ],
)
def test_resolve_mentions(message: str, expected: tuple[str, ...]) -> None:
    assert resolve(message, NAMES, ()) == expected


def test_unaddressed_message_is_sticky() -> None:
    assert resolve("and the risks?", NAMES, ("po",)) == ("po",)


def test_mid_message_mention_does_not_route() -> None:
    assert resolve("ask @manager later", NAMES, ("po",)) == ("po",)


def test_no_one_to_answer() -> None:
    with pytest.raises(AddressError, match="@manager @po @liaison @all"):
        resolve("hello", NAMES, ())


def test_unknown_mention() -> None:
    with pytest.raises(AddressError, match="unknown @cto, @cfo"):
        resolve("@cto @cfo hi", NAMES, ("po",))


def test_leading_mentions_none() -> None:
    assert leading_mentions("no mentions") == []
