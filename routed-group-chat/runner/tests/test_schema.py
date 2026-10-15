"""Unit tests for ``schema``: field-table checks shared by roster and state."""

from __future__ import annotations

from typing import Any

import pytest
from group_chat.schema import ListSchema, TableSchema, fits

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
    TableSchema(FIELDS, "thing", Bad).check({"name": "a", "count": 1, "tags": []})
    TableSchema(FIELDS, "thing", Bad).check({})


@pytest.mark.parametrize("table", [[], "x", None, 3])
def test_check_refuses_non_table(table: Any) -> None:
    with pytest.raises(Bad, match="thing must be a table"):
        TableSchema(FIELDS, "thing", Bad).check(table)


def test_check_refuses_unknown_keys_sorted() -> None:
    with pytest.raises(Bad, match=r"thing has unknown key\(s\): a, z"):
        TableSchema(FIELDS, "thing", Bad).check({"z": 1, "a": 2, "name": "x"})


def test_check_refuses_missing_required_keys() -> None:
    with pytest.raises(Bad, match=r"thing is missing key\(s\): count, name"):
        TableSchema(FIELDS, "thing", Bad, ("name", "count")).check({"tags": []})


@pytest.mark.parametrize(
    ("table", "message"),
    [({"name": 1}, "name must be a str"), ({"count": True}, "count must be a int")],
)
def test_check_refuses_wrong_types(table: dict[str, Any], message: str) -> None:
    with pytest.raises(Bad, match=f"thing: {message}"):
        TableSchema(FIELDS, "thing", Bad).check(table)


def test_check_uses_the_given_error_type() -> None:
    with pytest.raises(KeyError):
        TableSchema(FIELDS, "thing", KeyError).check([])


def test_check_items() -> None:
    ListSchema(str, "names", Bad).check(["a", "b"])
    ListSchema(str, "names", Bad).check([])
    with pytest.raises(Bad, match="names must hold only str values"):
        ListSchema(str, "names", Bad).check(["a", 1])
    with pytest.raises(Bad, match="ids must hold only int values"):
        ListSchema(int, "ids", Bad).check([1, True])
