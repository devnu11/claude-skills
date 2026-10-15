"""s130 (ADR-0067): no test writes module-level mutable state; helpers take the config."""

import inspect

import pytest

from . import state_scan, test_presentation, test_service_presentation
from .clock_scan import Tree

SOURCES = state_scan.py_sources(Tree.UNIT)
HITS = state_scan.state_hits(SOURCES)


def test_no_test_writes_module_state() -> None:
    assert HITS == [], "module-level state written by tests:\n" + "\n".join(HITS)


def test_the_unit_tree_is_scanned() -> None:
    expected = {"conftest.py", "clock.py", "fake_system.py", "test_presentation.py"}
    assert expected <= set(SOURCES)
    assert not [k for k in SOURCES if k.startswith("e2e/")]


@pytest.mark.parametrize("module", [test_presentation, test_service_presentation])
def test_presentation_helpers_take_the_config(module) -> None:
    first = next(iter(inspect.signature(module.story_of).parameters))
    assert first == "config"
    assert not hasattr(module, "CURRENT")


CAUGHT = [
    ("X = []\ndef f():\n    X.append(1)\n", (3, "X")),
    ("X: list[int] = []\ndef f():\n    X[:] = [1]\n", (3, "X")),
    ("X = {}\ndef f():\n    X['k'] = 1\n", (3, "X")),
    ("X = {}\ndef f():\n    del X['k']\n", (3, "X")),
    ("X = {}\ndef f():\n    X['k'] += 1\n", (3, "X")),
    ("X = {'a': {}}\ndef f():\n    X['a']['b'] = 1\n", (3, "X")),
    ("X = set()\ndef f():\n    X.add(1)\n", (3, "X")),
    ("X = defaultdict(list)\ndef f():\n    X['k'].append(1)\n", (3, "X")),
    ("X = [1] + [2]\ndef f():\n    X.pop()\n", (3, "X")),
    ("X = []\nclass C:\n    def m(self):\n        X.append(1)\n", (4, "X")),
    ("X = []\nasync def f():\n    X.append(1)\n", (3, "X")),
    ("X = []\ndef f():\n    def g():\n        X.append(1)\n", (4, "X")),
    ("X = {}\ndef f():\n    X.a = 1\n", (3, "X")),
    ("Y = 0\ndef f():\n    global Y\n    Y = 1\n", (3, "Y")),
]


@pytest.mark.parametrize(("source", "hit"), CAUGHT)
def test_writes_to_module_state_are_caught(source: str, hit: tuple[int, str]) -> None:
    assert state_scan.write_lines(source) == [hit]


PASSED = [
    "X = (1,)\ndef f():\n    X.count(1)\n",
    "X = frozenset()\ndef f():\n    X.union({1})\n",
    "def f():\n    X = []\n    X.append(1)\n",
    "X = []\ndef f():\n    X = []\n    X.append(1)\n",
    "X = []\ndef f(X):\n    X.append(1)\n",
    "X = []\nX.append(1)\n",
    "X = []\ndef f():\n    len(X)\n    dict(X)\n    X.copy()\n    X.get('k')\n",
    "X = []\ndef pytest_configure(config):\n    X.append(1)\n",
]


@pytest.mark.parametrize("source", PASSED)
def test_safe_code_is_passed(source: str) -> None:
    assert state_scan.write_lines(source) == []


def test_state_hits_name_file_line_and_name() -> None:
    sources = {"a.py": "X = []\ndef f():\n    X.append(1)\n", "b.js": "X.push(1)"}
    assert state_scan.state_hits(sources) == ["a.py:3: X"]


def test_pytest_randomly_is_installed_so_random_order_is_the_default() -> None:
    """AC3 / R3: the dev group carries pytest-randomly (devops adds it after this step)."""
    import importlib.util

    assert importlib.util.find_spec("pytest_randomly") is not None


def test_mutable_value_shapes() -> None:
    import ast

    def parsed(text: str) -> ast.expr:
        return ast.parse(text, mode="eval").body

    assert state_scan.mutable_value(parsed("collections.deque()"))
    assert state_scan.mutable_value(parsed("[i for i in y]"))
    assert not state_scan.mutable_value(parsed("(1, 2)"))
    assert not state_scan.mutable_value(parsed("1"))
    assert not state_scan.mutable_value(parsed("make()"))
