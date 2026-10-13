"""The snapshot's ``tools`` section: grouping and gathering (s98, TC15-TC17)."""

from __future__ import annotations

from typing import Any

import pytest
from agile_team.dashboard import tool_groups as tg


def row(seconds: Any, at: float = 0.0, tool: str = "Read", **keys: Any) -> dict[str, Any]:
    base = {"role": "developer", "story": "s1", "step": "implement", "opened_at": 1.0}
    return {**base, **keys, "tool": tool, "seconds": seconds, "at": at}


SECONDS = [0.01, 0.02, 0.03, 0.05, 2.0]


def five() -> list[dict[str, Any]]:
    # file order is not time order; `at` runs 5, 4, 3, 2, 1 (longest first)
    return [
        row(s, at=float(5 - i), tool="Bash" if s == 0.02 else "Read") for i, s in enumerate(SECONDS)
    ]


def test_the_shortest_calls_are_gathered_up_to_the_limit_and_the_next_stays_out() -> None:
    gathered, shipped = tg.gather(five(), 0.1)
    assert [r["seconds"] for r in sorted(gathered, key=lambda r: r["seconds"])] == [
        0.01,
        0.02,
        0.03,
    ]
    assert [r["seconds"] for r in shipped] == [2.0, 0.05]  # by `at`: 2.0 has at=1, 0.05 at=2
    assert [r["at"] for r in shipped] == [1.0, 2.0]


def test_misc_has_count_seconds_and_tools_in_first_gathered_order() -> None:
    gathered, _ = tg.gather(five(), 0.1)
    assert tg.misc(gathered) == {"count": 3, "seconds": 0.06, "tools": {"Read": 2, "Bash": 1}}


def test_a_group_has_calls_and_misc() -> None:
    out = tg.group(five(), 0.1)
    assert out["role"] == "developer" and out["story"] == "s1"
    assert out["step"] == "implement" and out["opened_at"] == 1.0
    assert [c["seconds"] for c in out["calls"]] == [2.0, 0.05]
    assert out["misc"]["count"] == 3


def test_shipped_rows_are_as_read_from_the_file() -> None:
    rows = [row(5.0, extra="kept")]
    assert tg.group(rows, 0.1)["calls"] == rows


def test_totals_match_the_file() -> None:
    rows = five()
    out = tg.group(rows, 0.1)
    total = out["misc"]["seconds"] + sum(c["seconds"] for c in out["calls"])
    assert total == pytest.approx(sum(SECONDS))


def test_a_call_that_reaches_the_limit_exactly_is_not_gathered() -> None:
    gathered, shipped = tg.gather([row(0.05, 1.0), row(0.05, 2.0)], 0.1)
    assert len(gathered) == 1 and len(shipped) == 1


def test_a_limit_of_zero_gathers_nothing() -> None:
    gathered, shipped = tg.gather([row(0.0), row(0.01)], 0.0)
    assert gathered == [] and len(shipped) == 2


def test_an_empty_group_has_an_empty_misc() -> None:
    assert tg.misc([]) == {"count": 0, "seconds": 0.0, "tools": {}}
    assert tg.group([], 0.1)["misc"] == {"count": 0, "seconds": 0.0, "tools": {}}


def test_ties_in_seconds_gather_the_earlier_call_first() -> None:
    gathered, shipped = tg.gather([row(0.06, at=2.0), row(0.06, at=1.0)], 0.1)
    assert [r["at"] for r in gathered] == [1.0] and [r["at"] for r in shipped] == [2.0]


def test_groups_split_by_role_story_step_and_opened_at_in_first_seen_order() -> None:
    rows = [
        row(1.0, role="b"), row(1.0, role="a"), row(1.0, role="b"),
        row(1.0, opened_at=2.0), row(1.0, story=None), row(1.0, step="design"),
    ]  # fmt: skip
    out = tg.groups(rows, 0.0)
    assert [g["role"] for g in out[:2]] == ["b", "a"]
    assert len(out) == 5 and len(out[0]["calls"]) == 2
    assert tg.key_of(rows[0]) == ("b", "s1", "implement", 1.0)


def test_groups_of_nothing_is_empty() -> None:
    assert tg.groups([], 0.1) == []


@pytest.mark.parametrize(
    "bad",
    [
        row(True),
        row("1"),
        row(None),
        row(-0.5),
        row(1.0, role=None),
        row(1.0, role=3),
        {**row(1.0), "at": True},
        {**row(1.0), "at": "x"},
        {k: v for k, v in row(1.0).items() if k != "role"},
        {k: v for k, v in row(1.0).items() if k != "seconds"},
    ],
)
def test_invalid_rows_are_skipped(bad: dict[str, Any]) -> None:
    assert tg.valid(bad) is False
    assert tg.groups([bad], 0.1) == []


def test_valid_rows_include_zero_and_integer_seconds() -> None:
    assert tg.valid(row(0)) and tg.valid(row(0.0)) and tg.valid(row(3))
    (only,) = tg.groups([row(0), {"junk": 1}], 0.1)
    assert only["misc"]["count"] == 1 and only["calls"] == []
