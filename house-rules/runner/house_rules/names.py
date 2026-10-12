"""Splitting identifiers into words, and the name exemptions every naming rule shares."""

from __future__ import annotations

import fnmatch
import re

CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
ENTRY_POINTS = frozenset({"main", "just_do_it", "justDoIt", "JustDoIt"})


def split_words(name: str) -> list[str]:
    """``_load_ConfigFile`` -> ``["load", "config", "file"]``."""
    snake = CAMEL_BOUNDARY.sub("_", name.strip("_"))
    return [word.lower() for word in snake.split("_") if word]


def get_first_word(name: str) -> str:
    """The first word of ``name``, lower case, or ``""`` for a name of underscores."""
    words = split_words(name)
    return words[0] if words else ""


def is_dunder(name: str) -> bool:
    """``__init__``-style names, which the language defines."""
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def is_exempt(name: str, allowed: tuple[str, ...]) -> bool:
    """Names no naming rule applies to: dunders, entry points, tests and allowed patterns."""
    if is_dunder(name) or name in ENTRY_POINTS or name.startswith("test_"):
        return True
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in allowed)


def to_snake_case(name: str) -> str:
    """``CreateShape`` or ``createShape`` -> ``create_shape``."""
    return "_".join(split_words(name))
