"""Check a parsed table against a ``{key: type}`` table: one rule for rosters and state.

Unknown keys and values of the wrong type are refused; ``bool`` never passes as
``int``. Keys in ``required`` must be present.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any, TypeGuard

Fields = Mapping[str, type]


def check(
    table: Any,
    fields: Fields,
    where: str,
    error: type[Exception],
    required: Collection[str] = (),
) -> None:
    """Raise ``error`` naming ``where`` unless ``table`` fits ``fields``."""
    if not isinstance(table, Mapping):
        raise error(f"{where} must be a table")
    _check_keys(table, fields, where, error, required)
    for key, value in table.items():
        if not fits(value, fields[key]):
            raise error(f"{where}: {key} must be a {fields[key].__name__}")


def check_items(items: list[Any], kind: type, where: str, error: type[Exception]) -> None:
    """Raise ``error`` unless every item in ``items`` is a ``kind``."""
    if not all(fits(item, kind) for item in items):
        raise error(f"{where} must hold only {kind.__name__} values")


def fits[T](value: Any, kind: type[T]) -> TypeGuard[T]:
    """``isinstance``, except that a ``bool`` is not an ``int``."""
    if kind is int and isinstance(value, bool):
        return False
    return isinstance(value, kind)


def _check_keys(
    table: Mapping[str, Any],
    fields: Fields,
    where: str,
    error: type[Exception],
    required: Collection[str],
) -> None:
    unknown = sorted(set(table) - set(fields))
    if unknown:
        raise error(f"{where} has unknown key(s): {', '.join(unknown)}")
    missing = sorted(set(required) - set(table))
    if missing:
        raise error(f"{where} is missing key(s): {', '.join(missing)}")
