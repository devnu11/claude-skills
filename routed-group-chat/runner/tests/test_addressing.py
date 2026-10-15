"""Unit tests for ``addressing``: who answers a human message."""

from __future__ import annotations

import pytest
from group_chat.addressing import AddressError, find_leading_mentions, resolve

pytestmark = pytest.mark.unit

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
    assert find_leading_mentions("no mentions") == []


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("@manager: hi", ("manager",)),
        ("@manager; hi", ("manager",)),
        ("@manager! hi", ("manager",)),
        ("@po@manager hi", ("po", "manager")),
        ("@po\n@manager hi", ("po", "manager")),
        ("\t@liaison hi", ("liaison",)),
    ],
)
def test_leading_mention_with_punctuation_and_whitespace(
    message: str, expected: tuple[str, ...]
) -> None:
    assert resolve(message, NAMES, ()) == expected


def test_email_address_is_not_a_mention() -> None:
    assert find_leading_mentions("a@b.com is the contact") == []
    assert resolve("a@b.com is the contact", NAMES, ("po",)) == ("po",)


def test_leading_dotted_name_is_refused_as_unknown() -> None:
    with pytest.raises(AddressError, match="unknown @b;"):
        resolve("@b.com hi", NAMES, ("po",))


def test_mentions_stop_at_first_word() -> None:
    assert find_leading_mentions("@po hi @manager") == ["po"]


def test_broadcast_dedupes_to_roster_order() -> None:
    assert resolve("@liaison @all @po", NAMES, ()) == NAMES


def test_sticky_returns_last_in_order() -> None:
    assert resolve("go on", NAMES, ("liaison", "po")) == ("liaison", "po")


def test_unknown_error_lists_valid_names() -> None:
    with pytest.raises(AddressError, match="choose from @manager @po @liaison @all"):
        resolve("@cto hi", NAMES, ())


def test_unknown_reported_even_with_known_names() -> None:
    with pytest.raises(AddressError, match="unknown @cto;"):
        resolve("@po @cto hi", NAMES, ())


def test_broadcast_with_unknown_name_is_refused() -> None:
    with pytest.raises(AddressError, match="@cto"):
        resolve("@all @cto hi", NAMES, ())


def test_capitalised_mention_routes_case_insensitively() -> None:
    assert resolve("@Manager @PO hi", NAMES, ("liaison",)) == ("manager", "po")


@pytest.mark.parametrize("message", ["@all @cto hi", "@cto @all hi", "@ALL @Cto hi"])
def test_unknown_beside_all_is_refused(message: str) -> None:
    with pytest.raises(AddressError, match="unknown @cto;"):
        resolve(message, NAMES, ("po",))


def test_uppercase_all_broadcasts() -> None:
    assert resolve("@ALL status", NAMES, ()) == NAMES


def test_leading_mentions_are_lowercased() -> None:
    assert find_leading_mentions("@PO, @Manager! hi") == ["po", "manager"]


def test_sticky_drops_roles_no_longer_in_roster() -> None:
    assert resolve("and?", NAMES, ("cto", "po")) == ("po",)


def test_sticky_refused_when_no_roles_remain() -> None:
    with pytest.raises(AddressError, match="address someone first"):
        resolve("and?", NAMES, ("cto",))
