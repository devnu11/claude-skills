"""s72: per-test time limit picked by world (1 s unit, e2e_timeout for real)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from . import os_guard, time_limit


def _config(values: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(getini=lambda key: values[key])


def _stub(path: str, config) -> SimpleNamespace:
    return SimpleNamespace(path=Path(path), config=config)


def test_running_test_is_marked_with_the_unit_limit(request):
    assert request.node.get_closest_marker("timeout").args == (1.0,)


def test_ini_holds_both_limits(request):
    assert float(request.config.getini("timeout")) == 1.0
    assert float(request.config.getini("e2e_timeout")) == 30.0


def test_unit_file_gets_one_second(request):
    assert time_limit.limit_of(_stub("tests/test_x.py", request.config)) == 1.0


def test_e2e_file_gets_the_e2e_limit(request):
    assert time_limit.limit_of(_stub("tests/e2e/test_x.py", request.config)) == 30.0


def test_legacy_file_gets_the_e2e_limit(request, monkeypatch):
    monkeypatch.setattr(os_guard, "LEGACY", frozenset({"test_legacy.py"}))
    assert time_limit.limit_of(_stub("tests/test_legacy.py", request.config)) == 30.0


def test_limit_is_read_from_the_ini():
    config = _config({"timeout": "0.5", "e2e_timeout": "7"})
    assert time_limit.limit_of(_stub("tests/test_x.py", config)) == 0.5
    assert time_limit.limit_of(_stub("tests/e2e/test_x.py", config)) == 7.0


def test_mark_adds_one_timeout_marker_per_item(request):
    calls: list[tuple] = []

    def item(path: str) -> SimpleNamespace:
        stub = _stub(path, request.config)
        stub.add_marker = lambda marker: calls.append((marker.name, marker.args))
        return stub

    time_limit.mark([item("tests/test_x.py"), item("tests/e2e/test_y.py")])
    assert calls == [("timeout", (1.0,)), ("timeout", (30.0,))]


def test_mark_with_no_items_adds_nothing():
    assert time_limit.mark([]) is None


def test_limit_is_a_float_even_for_an_integer_ini_value():
    config = _config({"timeout": "2", "e2e_timeout": "9"})
    limit = time_limit.limit_of(_stub("tests/test_x.py", config))
    assert isinstance(limit, float) and limit == 2.0


def test_every_world_has_a_limit_key():
    assert set(time_limit.LIMIT_INI) == set(os_guard.World)
