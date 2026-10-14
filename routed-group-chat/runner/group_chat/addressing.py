"""Who answers a human message: the roles it @mentions at its start.

``@manager, when?`` goes to the manager; ``@po @manager ...`` to both, in that
order; ``@all`` to every role in roster order. A message with no leading mention
goes to whoever was addressed last (sticky). With no one addressed yet, or an
unknown name, the message is refused and nothing is recorded.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

BROADCAST = "all"
# Mentions at the start, separated by spaces or commas.
LEADING_RE = re.compile(r"^\s*((?:@[a-z][a-z0-9-]*[\s,]*)+)")
MENTION_RE = re.compile(r"@([a-z][a-z0-9-]*)")


class AddressError(ValueError):
    """The message names no known role and there is no one to fall back to."""


def resolve(message: str, names: Sequence[str], last: Sequence[str]) -> tuple[str, ...]:
    """The roles that answer ``message``, in order."""
    mentioned = leading_mentions(message)
    if not mentioned:
        return _sticky(last, names)
    return _expand(mentioned, names)


def leading_mentions(message: str) -> list[str]:
    """The @names at the start of ``message``, in order."""
    match = LEADING_RE.match(message)
    return MENTION_RE.findall(match.group(1)) if match else []


def _sticky(last: Sequence[str], names: Sequence[str]) -> tuple[str, ...]:
    if not last:
        raise AddressError(f"address someone first: {_choices(names)}")
    return tuple(last)


def _expand(mentioned: list[str], names: Sequence[str]) -> tuple[str, ...]:
    if BROADCAST in mentioned:
        return tuple(names)
    unknown = [name for name in mentioned if name not in names]
    if unknown:
        raise AddressError(f"unknown @{', @'.join(unknown)}; choose from {_choices(names)}")
    return tuple(dict.fromkeys(mentioned))


def _choices(names: Sequence[str]) -> str:
    return " ".join(f"@{name}" for name in [*names, BROADCAST])
