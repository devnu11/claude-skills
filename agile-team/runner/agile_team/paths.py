"""Glob matching and repo-relative path helpers shared by the guard and sandbox.

Globs use gitignore-like semantics: ``*`` stays inside one path segment, ``**``
crosses segments, and a leading ``!`` excludes. Paths are always POSIX,
relative to the repo root.
"""

from __future__ import annotations

import posixpath
import re
from fnmatch import fnmatchcase
from functools import cache
from itertools import takewhile
from pathlib import Path

GLOB_TOKENS = {"**/": "(?:.*/)?", "**": ".*", "*": "[^/]*", "?": "[^/]"}
GLOB_CHARS = "*?["
GROUP_CHARS = "{("
ANY_SEGMENT = "[{("
TOKEN_WILDCARDS = GLOB_CHARS + "{"
_TOKEN = re.compile(r"\*\*/|\*\*|\*|\?|[^*?]+")


@cache
def glob_to_regex(glob: str) -> re.Pattern[str]:
    """Compile one glob (without a leading ``!``) to an anchored regex."""
    parts = (GLOB_TOKENS.get(t) or re.escape(t) for t in _TOKEN.findall(glob))
    return re.compile("".join(parts) + r"\Z")


def matches(path: str, globs: list[str]) -> bool:
    """True when ``path`` matches a positive glob and no ``!`` glob."""
    included = any(glob_to_regex(g).match(path) for g in globs if not g.startswith("!"))
    excluded = any(glob_to_regex(g[1:]).match(path) for g in globs if g.startswith("!"))
    return included and not excluded


def literal_root(glob: str) -> str:
    """The wildcard-free leading path of a positive glob; ``""`` for a ``!`` glob
    or one that starts with a wildcard."""
    if glob.startswith("!"):
        return ""
    return "/".join(takewhile(_is_literal, glob.split("/"))).rstrip("/")


def _is_literal(segment: str) -> bool:
    return not any(c in segment for c in TOKEN_WILDCARDS)


def normalise_token(token: str) -> str:
    """A shell word as a repo-relative path: leading ``.``/``/`` stripped, ``//``
    and ``/./`` collapsed."""
    return posixpath.normpath(token.lstrip("./"))


def could_climb(token: str) -> bool:
    """True when a segment of the word could expand to ``..`` or span a ``/``."""
    *inner, _last = segments = token.split("/")
    return ".." in segments or any(_may_span(segment) for segment in inner)


def _may_span(segment: str) -> bool:
    dot_glob = segment.startswith(".") and any(c in segment for c in GLOB_CHARS)
    return dot_glob or any(c in segment for c in GROUP_CHARS)


def reaches(token: str, root: str) -> bool:
    """True when the shell could expand the word to ``root`` or a path under it."""
    word = normalise_token(token).casefold()
    if re.fullmatch(r"[*?]+", word):
        return False
    return _walk(word.split("/"), root.casefold().split("/"))


def _walk(word: list[str], root: list[str]) -> bool:
    if not root:
        return True
    if not word:
        return False
    if "**" in word[0]:
        return True
    return _segment_matches(word[0], root[0]) and _walk(word[1:], root[1:])


def _segment_matches(segment: str, root_segment: str) -> bool:
    if any(c in segment for c in ANY_SEGMENT):
        return True
    return fnmatchcase(root_segment, segment.replace("?", "*"))


def under_root(path: str, root: str) -> bool:
    """True when ``path`` is ``root`` or lies inside it."""
    return path == root or path.startswith(f"{root}/")


def resolve_in(base: Path, raw: str) -> Path:
    """``raw`` (absolute, ``~``-relative or relative to ``base``) as a resolved path."""
    candidate = Path(raw).expanduser()
    return (candidate if candidate.is_absolute() else base / candidate).resolve()


def repo_relative(repo: Path, path: Path) -> str | None:
    """``path`` relative to ``repo`` as POSIX, or ``None`` when outside the repo."""
    try:
        return path.relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None
