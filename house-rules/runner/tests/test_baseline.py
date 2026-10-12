"""The ratchet."""

from pathlib import Path

import pytest
from house_rules.baseline import Baseline, BaselineError
from house_rules.model import Finding, Level


def make_finding(value: int, level: Level = Level.FAIL) -> Finding:
    return Finding("parameters", level, "a.py", 1, "f", value, 3, "")


def test_missing_file_is_empty(tmp_path: Path) -> None:
    assert Baseline.from_file(tmp_path / "none.json").entries == {}


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    Baseline({"b::x::r": 2, "a::x::r": 1}).write(path)
    assert Baseline.from_file(path).entries == {"a::x::r": 1, "b::x::r": 2}
    assert path.read_text().index("a::x::r") < path.read_text().index("b::x::r")


def test_garbage_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    path.write_text("[1]")
    with pytest.raises(BaselineError):
        Baseline.from_file(path)


def test_covers_known_values_that_did_not_grow() -> None:
    baseline = Baseline({"a.py::f::parameters": 4})
    assert baseline.covers(make_finding(4)) and baseline.covers(make_finding(3))
    assert not baseline.covers(make_finding(5))
    assert not Baseline().covers(make_finding(4))


def test_from_findings_keeps_failures_only() -> None:
    baseline = Baseline.from_findings(
        [make_finding(4), make_finding(5), make_finding(9, Level.WARN)]
    )
    assert baseline.entries == {"a.py::f::parameters": 5}


def test_growth_and_stale() -> None:
    older = Baseline({"a.py::f::parameters": 4, "a.py::g::parameters": 4, "b.py::h::parameters": 4})
    newer = Baseline({"a.py::f::parameters": 5, "c.py::k::parameters": 4})
    assert older.list_growth(newer) == [
        "a.py::f::parameters: 4 -> 5",
        "c.py::k::parameters: new -> 4",
    ]
    assert older.list_stale([make_finding(4)], ["a.py"]) == ["a.py::g::parameters"]
