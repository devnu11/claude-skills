"""Validation of the JSON request files the liaison queues (shares, story drafts)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

BAD_REQUEST = "bad request file {file}: {problem}"
NOT_JSON = "not JSON ({error})"
NOT_OBJECT = "not a JSON object"
MISSING_FIELD = "missing field '{field}'"
WRONG_TYPE = "field '{field}' must be {word}"
UNREADABLE_REQUEST = "cannot read it ({error})"


@dataclass(frozen=True)
class FieldKind:
    """The types a request field accepts, and how a refusal names them."""

    types: tuple[type, ...]
    word: str


STRING = FieldKind((str,), "a string")
NUMBER = FieldKind((int, float), "a number")  # bool is refused explicitly


@dataclass(frozen=True)
class BadRequest:
    """A queued request file that failed validation; settled as refused, never applied."""

    id: str
    reason: str


def bad_request(rid: str, problem: str) -> BadRequest:
    """A ``BadRequest`` for file ``rid``.json with ``problem``."""
    reason = BAD_REQUEST.format(file=f"{rid}.json", problem=problem)
    return BadRequest(rid, reason)


@dataclass(frozen=True)
class Fields:
    """The fields a request file must have, each with its kind."""

    kinds: Mapping[str, FieldKind]

    def problem(self, raw: dict[str, Any], field: str) -> str | None:
        """What is wrong with ``field`` in ``raw``, or None."""
        if field not in raw:
            return MISSING_FIELD.format(field=field)
        kind, value = self.kinds[field], raw[field]
        if isinstance(value, kind.types) and type(value) is not bool:
            return None
        return WRONG_TYPE.format(field=field, word=kind.word)

    def loaded(self, text: str) -> dict[str, Any] | str:
        """The request as a dict, or the first problem as text."""
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as error:
            return NOT_JSON.format(error=error.msg)
        if not isinstance(raw, dict):
            return NOT_OBJECT
        problems = (self.problem(raw, f) for f in self.kinds)
        return next((p for p in problems if p), raw)
