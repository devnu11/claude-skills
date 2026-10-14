"""Unit tests for ``schema``: field-table checks shared by roster and state."""

from __future__ import annotations

from typing import Any

import pytest
from group_chat.schema import check, check_items, fits

pytestmark = pytest.mark.unit

FIELDS = {"name": str, "count": int, "tags": list}


class Bad(ValueError):
    pass


def test_fits_plain_types() -> None:
    assert fits("x", str)
    assert fits(3, int)
    assert not fits("3", int)


@pytest.mark.parametrize("value", [True, False])
def test_bool_is_not_an_int(value: bool) -> None:
    assert not fits(value, int)
    assert fits(value, bool)


def test_check_accepts_valid_and_partial_tables() -> None:
    check({"name": "a", "count": 1, "tags": []}, FIELDS, "thing", Bad)
    check({}, FIELDS, "thing", Bad)


@pytest.mark.parametrize("table", [[], "x", None, 3])
def test_check_refuses_non_table(table: Any) -> None:
    with pytest.raises(Bad, match="thing must be a table"):
        check(table, FIELDS, "thing", Bad)


def test_check_refuses_unknown_keys_sorted() -> None:
    with pytest.raises(Bad, match=r"thing has unknown key\(s\): a, z"):
        check({"z": 1, "a": 2, "name": "x"}, FIELDS, "thing", Bad)


def test_check_refuses_missing_required_keys() -> None:
    with pytest.raises(Bad, match=r"thing is missing key\(s\): count, name"):
        check({"tags": []}, FIELDS, "thing", Bad, required=("name", "count"))


@pytest.mark.parametrize(
    ("table", "message"),
    [({"name": 1}, "name must be a str"), ({"count": True}, "count must be a int")],
)
def test_check_refuses_wrong_types(table: dict[str, Any], message: str) -> None:
    with pytest.raises(Bad, match=f"thing: {message}"):
        check(table, FIELDS, "thing", Bad)


def test_check_uses_the_given_error_type() -> None:
    with pytest.raises(KeyError):
        check([], FIELDS, "thing", KeyError)


def test_check_items() -> None:
    check_items(["a", "b"], str, "names", Bad)
    check_items([], str, "names", Bad)
    with pytest.raises(Bad, match="names must hold only str values"):
        check_items(["a", 1], str, "names", Bad)
    with pytest.raises(Bad, match="ids must hold only int values"):
        check_items([1, True], int, "ids", Bad)
