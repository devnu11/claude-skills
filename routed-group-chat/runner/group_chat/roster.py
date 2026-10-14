"""Load and validate a roster: the roles that share one chat thread.

A roster is TOML data, checked on load against ``TOP_FIELDS`` and
``ROLE_FIELDS``: unknown keys and wrong types are refused, so a typo such as
``modle`` fails loudly instead of being dropped. Each ``[[role]]`` has a
``name`` (the @mention), an optional ``title`` and ``model``, and exactly one of
``prompt`` (inline) or ``prompt_file`` (relative to the roster file).
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,31}")
# ``all`` is the broadcast mention; ``human`` and ``orchestrator`` are speakers.
RESERVED = frozenset({"all", "human", "orchestrator"})
TOP_FIELDS: dict[str, type] = {"team": str, "role": list}
ROLE_FIELDS: dict[str, type] = {
    "name": str,
    "title": str,
    "model": str,
    "prompt": str,
    "prompt_file": str,
}


class RosterError(ValueError):
    """The roster file is missing, malformed or breaks a rule."""


@dataclass(frozen=True)
class Role:
    """One agent in the chat."""

    name: str
    title: str
    prompt: str
    model: str | None = None


@dataclass(frozen=True)
class Roster:
    """The team's roles, in the order a broadcast answers."""

    team: str
    roles: tuple[Role, ...]

    def names(self) -> tuple[str, ...]:
        """Every role's @mention name, in roster order."""
        return tuple(role.name for role in self.roles)

    def get(self, name: str) -> Role:
        """The role called ``name``; ``RosterError`` if there is none."""
        for role in self.roles:
            if role.name == name:
                return role
        raise RosterError(f"no role named {name!r} in the roster")


def load(path: Path) -> Roster:
    """Read and validate the roster at ``path``."""
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RosterError(f"{path}: {exc}") from exc
    return parse(data, path.parent)


def parse(data: Mapping[str, Any], base: Path) -> Roster:
    """Validate roster data; ``base`` resolves ``prompt_file`` paths."""
    check_fields(data, TOP_FIELDS, "roster")
    raw = data.get("role")
    if not raw:
        raise RosterError("roster needs at least one [[role]]")
    roles = tuple(_role(item, base) for item in raw)
    _check_unique(roles)
    return Roster(data.get("team", "group chat"), roles)


def check_fields(table: Any, fields: Mapping[str, type], where: str) -> None:
    """Refuse a non-table, unknown keys and values of the wrong type."""
    if not isinstance(table, Mapping):
        raise RosterError(f"{where} must be a table")
    unknown = sorted(set(table) - set(fields))
    if unknown:
        raise RosterError(f"{where} has unknown key(s): {', '.join(unknown)}")
    for key, value in table.items():
        if not isinstance(value, fields[key]):
            raise RosterError(f"{where}: {key} must be a {fields[key].__name__}")


def _role(item: Any, base: Path) -> Role:
    check_fields(item, ROLE_FIELDS, "each [[role]]")
    name = _name(item.get("name"))
    return Role(name, item.get("title", name), _prompt(name, item, base), item.get("model"))


def _name(value: Any) -> str:
    if not isinstance(value, str) or not NAME_RE.fullmatch(value):
        raise RosterError(f"role name {value!r} must match {NAME_RE.pattern}")
    if value in RESERVED:
        raise RosterError(f"role name {value!r} is reserved")
    return value


def _prompt(name: str, item: Mapping[str, Any], base: Path) -> str:
    inline, file = item.get("prompt"), item.get("prompt_file")
    if (inline is None) == (file is None):
        raise RosterError(f"role {name!r} needs exactly one of prompt or prompt_file")
    text = inline if inline is not None else _read_prompt(base / str(file))
    if not text.strip():
        raise RosterError(f"role {name!r} has an empty prompt")
    return text.strip()


def _read_prompt(path: Path) -> str:
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        raise RosterError(f"prompt_file {path}: {exc}") from exc


def _check_unique(roles: tuple[Role, ...]) -> None:
    seen: set[str] = set()
    for role in roles:
        if role.name in seen:
            raise RosterError(f"role {role.name!r} appears twice")
        seen.add(role.name)
