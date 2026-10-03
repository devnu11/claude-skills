"""Glob matching and repo-relative path helpers shared by the guard and sandbox.

Globs use gitignore-like semantics: ``*`` stays inside one path segment, ``**``
crosses segments, and a leading ``!`` excludes. Paths are always POSIX,
relative to the repo root.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path


@cache
def glob_to_regex(glob: str) -> re.Pattern[str]:
    """Compile one glob (without a leading ``!``) to an anchored regex."""
    out: list[str] = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def matches(path: str, globs: list[str]) -> bool:
    """True when ``path`` matches a positive glob and no ``!`` glob."""
    included = any(glob_to_regex(g).match(path) for g in globs if not g.startswith("!"))
    excluded = any(glob_to_regex(g[1:]).match(path) for g in globs if g.startswith("!"))
    return included and not excluded


def literal_root(glob: str) -> str:
    """The leading path segment of a glob that holds no wildcard, or ``""``."""
    first = glob.lstrip("!").split("/", 1)[0]
    return "" if any(c in first for c in "*?[") else first


def repo_relative(repo: Path, raw: str, cwd: Path | None = None) -> str | None:
    """Resolve ``raw`` against ``cwd`` (default ``repo``) and express it relative
    to ``repo``. Returns ``None`` when the path lies outside the repo."""
    base = cwd or repo
    candidate = Path(raw).expanduser()
    resolved = (candidate if candidate.is_absolute() else base / candidate).resolve()
    try:
        return resolved.relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None
