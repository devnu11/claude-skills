"""Rendering."""

import json

from house_rules.baseline import Baseline
from house_rules.checker import Outcome
from house_rules.model import Finding, Level, Suppression
from house_rules.report import render_github, render_json, render_text

FAIL = Finding(
    "parameters", Level.FAIL, "a.py", 3, "add", 4, 3, "`add` takes 4 parameters (limit 3)"
)
WARN = Finding("verb-synonym", Level.WARN, "a.py", 9, "f", 1, 0, "prefer `remove`")
KNOWN = Finding("parameters", Level.FAIL, "b.py", 1, "g", 4, 3, "old")
OUTCOME = Outcome(
    (FAIL, WARN, KNOWN),
    (Suppression("c.py", 2, frozenset({"global-scope"}), ""),),
    Baseline({"b.py::g::parameters": 4, "a.py::gone::parameters": 5}),
    ("a.py", "b.py"),
)


def test_text() -> None:
    assert render_text(OUTCOME).splitlines() == [
        "a.py:3: fail parameters: `add` takes 4 parameters (limit 3)",
        "a.py:9: warn verb-synonym: prefer `remove`",
        "suppressed c.py:2 global-scope: (no reason)",
        "stale baseline entry: a.py::gone::parameters (run `house-rules baseline`)",
        "house-rules: 2 files, 1 failing, 1 warnings, 1 baselined, 1 suppressed",
    ]


def test_json() -> None:
    data = json.loads(render_json(OUTCOME))
    assert [item["symbol"] for item in data["failures"]] == ["add"]
    assert data["suppressions"][0]["rules"] == ["global-scope"]
    assert data["stale"] == ["a.py::gone::parameters"] and data["files"] == 2


def test_github() -> None:
    lines = render_github(OUTCOME).splitlines()
    expected = "::error file=a.py,line=3,title=house-rules parameters::" + FAIL.message
    assert lines[0] == expected
    assert lines[1].startswith("::warning file=a.py,line=9,")
