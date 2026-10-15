"""Who answers a human message: the roles it @mentions at its start.

``@manager, when?`` goes to the manager; ``@po @manager ...`` to both, in that
order; ``@all`` to every role in roster order. Mentions are case-insensitive.
A message with no leading mention goes to whoever was addressed last (sticky).
With no one addressed yet, or any unknown name (even beside ``@all``), the
message is refused and nothing is recorded.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

BROADCAST = "all"
MENTION = r"@[a-z][a-z0-9-]*"
# Mentions at the start, separated by spaces, commas or other punctuation.
LEADING_RE = re.compile(rf"^\s*((?:{MENTION}[\s,;:!]*)+)", re.IGNORECASE)
MENTION_RE = re.compile(rf"{MENTION}", re.IGNORECASE)


class AddressError(ValueError):
    """The message names an unknown role, or no one and there is no one to fall back to."""


def resolve(message: str, names: Sequence[str], last: Sequence[str]) -> tuple[str, ...]:
    """The roles that answer ``message``, in order."""
    mentioned = find_leading_mentions(message)
    if not mentioned:
        return _resolve_sticky(last, names)
    return _expand(mentioned, names)


def find_leading_mentions(message: str) -> list[str]:
    """The @names at the start of ``message``, lowercased, in order."""
    match = LEADING_RE.match(message)
    if not match:
        return []
    return [mention[1:].lower() for mention in MENTION_RE.findall(match.group(1))]


def _resolve_sticky(last: Sequence[str], names: Sequence[str]) -> tuple[str, ...]:
    current = tuple(name for name in last if name in names)
    if not current:
        raise AddressError(f"address someone first: {_format_choices(names)}")
    return current


def _expand(mentioned: list[str], names: Sequence[str]) -> tuple[str, ...]:
    unknown = [name for name in mentioned if name not in names and name != BROADCAST]
    if unknown:
        raise AddressError(f"unknown @{', @'.join(unknown)}; choose from {_format_choices(names)}")
    if BROADCAST in mentioned:
        return tuple(names)
    return tuple(dict.fromkeys(mentioned))


def _format_choices(names: Sequence[str]) -> str:
    return " ".join(f"@{name}" for name in [*names, BROADCAST])
