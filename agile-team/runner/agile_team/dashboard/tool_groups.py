"""The snapshot's `tools` section (s98): spans grouped by step, the shortest gathered into misc."""

from __future__ import annotations

import itertools
from typing import Any

from .step_times import number

Key = tuple[Any, Any, Any, Any]
GROUP_KEYS = ("role", "story", "step", "opened_at")


def valid(row: dict) -> bool:
    """A span row with numeric ``seconds`` >= 0 and ``at`` and a string ``role`` (TC16)."""
    seconds = number(row.get("seconds"))
    return (
        seconds is not None
        and seconds >= 0
        and number(row.get("at")) is not None
        and isinstance(row.get("role"), str)
    )


def key_of(row: dict) -> Key:
    """The step or PO turn a row belongs to."""
    return tuple(row.get(key) for key in GROUP_KEYS)  # type: ignore[return-value]


def gather(rows: list[dict], limit: float) -> tuple[list[dict], list[dict]]:
    """``(gathered, shipped)``: the shortest rows while their total stays under ``limit`` (TC17)."""
    ordered = sorted(rows, key=lambda r: (r["seconds"], r["at"]))
    totals = itertools.accumulate(r["seconds"] for r in ordered)
    count = sum(1 for total in totals if total < limit)
    return ordered[:count], sorted(ordered[count:], key=lambda r: r["at"])


def misc(gathered: list[dict]) -> dict[str, Any]:
    """The gathered calls' count, seconds and count per tool."""
    tools: dict[str, int] = {}
    for row in gathered:
        tools[row.get("tool")] = tools.get(row.get("tool"), 0) + 1  # type: ignore[index]
    return {
        "count": len(gathered),
        "seconds": round(sum(r["seconds"] for r in gathered), 3),
        "tools": tools,
    }


def group(rows: list[dict], limit: float) -> dict[str, Any]:
    """One group object for the rows of a step."""
    gathered, shipped = gather(rows, limit)
    key = key_of(rows[0]) if rows else (None,) * len(GROUP_KEYS)
    head = dict(zip(GROUP_KEYS, key, strict=True))
    return {**head, "calls": shipped, "misc": misc(gathered)}


def groups(rows: list[dict], limit: float) -> list[dict]:
    """The valid rows grouped by step in first-seen order (TC15)."""
    by_key: dict[Key, list[dict]] = {}
    for row in filter(valid, rows):
        by_key.setdefault(key_of(row), []).append(row)
    return [group(members, limit) for members in by_key.values()]
