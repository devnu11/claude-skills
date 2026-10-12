"""Suppression comments: ``# house-rules: allow <rule> -- <reason>`` and ruff ``noqa`` aliases."""

from __future__ import annotations

import io
import re
import tokenize

from .model import Suppression
from .rules import RUFF_ALIASES

ALLOW = re.compile(r"house-rules:\s*allow\s+(?P<names>[\w\-]+(?:\s*,\s*[\w\-]+)*)(?P<rest>.*)")
NOQA = re.compile(r"noqa:\s*(?P<names>[A-Z]+[0-9]+(?:\s*,\s*[A-Z]+[0-9]+)*)(?P<rest>.*)")
REASON = re.compile(r"^\s*--\s*(?P<reason>.*\S)")


def parse_suppressions(text: str, path: str) -> tuple[Suppression, ...]:
    """Every suppression comment in ``text`` that names one of these rules."""
    found = (parse_comment(comment, path) for comment in list_comments(text))
    return tuple(suppression for suppression in found if suppression)


def list_comments(text: str) -> list[tokenize.TokenInfo]:
    """The comment tokens of ``text``; none when it does not tokenize."""
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError):
        return []
    return [token for token in tokens if token.type == tokenize.COMMENT]


def parse_comment(comment: tokenize.TokenInfo, path: str) -> Suppression | None:
    """The suppression one comment makes, if any."""
    allow, noqa = ALLOW.search(comment.string), NOQA.search(comment.string)
    match = allow or noqa
    if match is None:
        return None
    rules = split_names(match["names"]) if allow else map_ruff_codes(match["names"])
    if not rules:
        return None
    return Suppression(path, comment.start[0], rules, read_reason(match["rest"]))


def split_names(names: str) -> frozenset[str]:
    """``a, b`` -> ``{"a", "b"}``."""
    return frozenset(name.strip() for name in names.split(",") if name.strip())


def map_ruff_codes(codes: str) -> frozenset[str]:
    """The house rules that the ruff codes stand for; other codes are ignored."""
    return frozenset(RUFF_ALIASES[code] for code in split_names(codes) if code in RUFF_ALIASES)


def read_reason(rest: str) -> str:
    """The text after ``--``, or ``""``."""
    match = REASON.match(rest)
    return match["reason"] if match else ""
