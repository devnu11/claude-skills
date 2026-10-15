"""Check a parsed table against a ``{key: type}`` table: one rule for rosters and state.

Unknown keys and values of the wrong type are refused; ``bool`` never passes as
``int``. Keys in ``required`` must be present.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, TypeGuard

type Fields = Mapping[str, type]


@dataclass(frozen=True)
class TableSchema:
    """A ``{key: type}`` table, the name errors give it, their type and the required keys."""

    fields: Fields
    where: str
    error: type[Exception]
    required: Collection[str] = ()

    def check(self, table: Any) -> None:
        """Raise ``error`` naming ``where`` unless ``table`` fits ``fields``."""
        if not isinstance(table, Mapping):
            raise self.error(f"{self.where} must be a table")
        self._check_keys(table)
        for key, value in table.items():
            if not fits(value, self.fields[key]):
                raise self.error(f"{self.where}: {key} must be a {self.fields[key].__name__}")

    def _check_keys(self, table: Mapping[str, Any]) -> None:
        unknown = sorted(set(table) - set(self.fields))
        if unknown:
            raise self.error(f"{self.where} has unknown key(s): {', '.join(unknown)}")
        missing = sorted(set(self.required) - set(table))
        if missing:
            raise self.error(f"{self.where} is missing key(s): {', '.join(missing)}")


@dataclass(frozen=True)
class ListSchema:
    """A list whose items are all ``kind``, the name errors give it and their type."""

    kind: type
    where: str
    error: type[Exception]

    def check(self, items: list[Any]) -> None:
        """Raise ``error`` unless every item in ``items`` is a ``kind``."""
        if not all(fits(item, self.kind) for item in items):
            raise self.error(f"{self.where} must hold only {self.kind.__name__} values")


def fits[T](value: Any, kind: type[T]) -> TypeGuard[T]:
    """``isinstance``, except that a ``bool`` is not an ``int``."""
    if kind is int and isinstance(value, bool):
        return False
    return isinstance(value, kind)
