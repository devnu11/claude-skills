"""Limits and findings."""

from house_rules.model import Finding, Level, Limits


def test_limits_classify_against_both_thresholds() -> None:
    limits = Limits(2, 3)
    assert [limits.classify(value) for value in (2, 3, 4)] == [None, Level.WARN, Level.FAIL]


def test_finding_key_is_path_symbol_rule() -> None:
    finding = Finding("parameters", Level.FAIL, "a.py", 3, "Shape.scale", 4, 3, "")
    assert finding.key == "a.py::Shape.scale::parameters"
