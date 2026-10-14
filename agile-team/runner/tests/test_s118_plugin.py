"""s118 R9: the pytest tally plugin, loaded by file path and driven with stubs.

The runner that runs this suite has already loaded its pinned copy of the plugin under
the name ``agile_team_tally``, so these tests load the file again under their own name.
Nothing here touches the OS: the environment is a plain dict, the tally file a stub path
and ``os.replace`` a stub.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import agile_team
import pytest

PLUGIN_FILE = Path(agile_team.__file__).parent / "pytest_plugin" / "agile_team_tally.py"
# Read at collection, before the OS guard is on.
PLUGIN_SOURCE = PLUGIN_FILE.read_text()
PLUGIN_NAMES = sorted(n for n in os.listdir(PLUGIN_FILE.parent) if n != "__pycache__")
PLUGIN_NAME = "agile_team_tally"


@pytest.fixture
def mod() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tally_plugin_under_test", PLUGIN_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Target:
    """A stand-in for the tally file's Path: every write lands in ``store`` by name."""

    def __init__(self, name: str, store: dict[str, str], writes: list[str]) -> None:
        self.name, self.store, self.writes = name, store, writes

    def with_name(self, name: str) -> Target:
        return Target(name, self.store, self.writes)

    def write_text(self, text: str, *args: Any, **kwargs: Any) -> int:
        self.store[self.name] = text
        self.writes.append(text)
        return len(text)

    def __fspath__(self) -> str:
        return self.name

    __str__ = __fspath__


@pytest.fixture
def target(mod: ModuleType, monkeypatch: pytest.MonkeyPatch) -> Target:
    store: dict[str, str] = {}

    def replace(src: Any, dst: Any) -> None:
        store[os.fspath(dst)] = store.pop(os.fspath(src))

    monkeypatch.setattr(mod.os, "replace", replace)
    return Target("tally.json", store, [])


class Manager:
    def __init__(self) -> None:
        self.registered: list[tuple[Any, str]] = []

    def register(self, plugin: Any, name: str) -> None:
        self.registered.append((plugin, name))


def stub_config() -> Any:
    def status(report: Any, config: Any) -> tuple[str, str, str]:
        return (report.category, "", "")

    return SimpleNamespace(
        hook=SimpleNamespace(pytest_report_teststatus=status), pluginmanager=Manager()
    )


def report(nodeid: str, when: str, category: str) -> Any:
    return SimpleNamespace(nodeid=nodeid, when=when, category=category)


@pytest.fixture
def rec(mod: ModuleType, target: Target) -> Any:
    recorder = mod.Recorder(target, stub_config(), session_id="s1")
    recorder.written_at = -math.inf
    return recorder


def whole_test(recorder: Any, node: str, call: str = "passed", setup: str = "") -> None:
    recorder.pytest_runtest_logreport(report(node, "setup", setup))
    recorder.pytest_runtest_logreport(report(node, "call", call))
    recorder.pytest_runtest_logreport(report(node, "teardown", ""))


def counts(recorder: Any) -> tuple[int, int, int, int]:
    r = recorder.record()
    return (r["passed"], r["warned"], r["skipped"], r["failed"])


# ----- the module itself -----


def test_the_constants(mod: ModuleType) -> None:
    assert mod.ENV == "AGILE_TEAM_TALLY" and mod.WRITE_EVERY_S == 0.5
    assert mod.RANKS == {
        "passed": 1, "skipped": 2, "xfailed": 2, "xpassed": 2, "failed": 3, "error": 3,
    }  # fmt: skip


def test_the_plugin_imports_nothing_from_agile_team() -> None:
    assert not re.search(r"^\s*(from|import)\s+agile_team\b", PLUGIN_SOURCE, re.M)


def test_the_directory_holds_only_the_plugin() -> None:
    assert PLUGIN_NAMES == ["agile_team_tally.py"]


# ----- P1: pytest_configure and unlisted -----


@pytest.mark.parametrize(
    ("value", "left"),
    [
        ("x,agile_team_tally", "x"),
        ("agile_team_tally", ""),
        ("a,agile_team_tally,b", "a,b"),
        ("x", "x"),
        ("", ""),
    ],
)
def test_unlisted(mod: ModuleType, value: str, left: str) -> None:
    assert mod.unlisted(value) == left


def test_configure_with_no_file_registers_nothing(
    mod: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mod.os, "environ", {"PYTEST_PLUGINS": "x,agile_team_tally"})
    config = stub_config()
    mod.pytest_configure(config)
    assert config.pluginmanager.registered == []
    assert mod.os.environ == {"PYTEST_PLUGINS": "x"}


def test_configure_with_an_empty_path_registers_nothing(
    mod: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mod.os, "environ", {"AGILE_TEAM_TALLY": ""})
    config = stub_config()
    mod.pytest_configure(config)
    assert config.pluginmanager.registered == []


def test_configure_with_a_file_registers_one_recorder_and_cleans_the_environment(
    mod: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = {"AGILE_TEAM_TALLY": "/t/tally.json", "PYTEST_PLUGINS": "agile_team_tally", "K": "v"}
    monkeypatch.setattr(mod.os, "environ", env)
    config = stub_config()
    mod.pytest_configure(config)
    ((plugin, name),) = config.pluginmanager.registered
    assert name == "agile-team-tally" and isinstance(plugin, mod.Recorder)
    assert str(plugin.path) == "/t/tally.json" and plugin.config is config
    assert env == {"K": "v"}  # the variable is popped, the plugin list emptied and deleted


def test_a_new_recorder_has_a_session_id_and_no_total(mod: ModuleType, target: Target) -> None:
    one = mod.Recorder(target, stub_config())
    assert one.session_id and one.total is None and one.written_at == -math.inf
    assert one.ranks == {} and one.done == set() and one.warned == set()


# ----- P2, P3, P4: outcomes -----


def test_a_passed_test_counts_at_its_teardown(rec: Any) -> None:
    whole_test(rec, "t::a")
    assert counts(rec) == (1, 0, 0, 0)


def test_a_test_without_its_teardown_report_is_not_counted(rec: Any) -> None:
    rec.pytest_runtest_logreport(report("t::a", "setup", ""))
    rec.pytest_runtest_logreport(report("t::a", "call", "passed"))
    assert counts(rec) == (0, 0, 0, 0)


def test_a_failed_setup_is_failed(rec: Any) -> None:
    whole_test(rec, "t::a", call="", setup="error")
    assert counts(rec) == (0, 0, 0, 1)


def test_a_failed_call_is_failed(rec: Any) -> None:
    whole_test(rec, "t::a", call="failed")
    assert counts(rec) == (0, 0, 0, 1)


def test_a_skipped_setup_is_skipped(rec: Any) -> None:
    whole_test(rec, "t::a", call="", setup="skipped")
    assert counts(rec) == (0, 0, 1, 0)


@pytest.mark.parametrize("category", ["skipped", "xfailed", "xpassed"])
def test_skip_xfail_and_xpass_are_all_skip(rec: Any, category: str) -> None:
    whole_test(rec, "t::a", call=category)
    assert counts(rec) == (0, 0, 1, 0)


def test_an_unknown_category_ranks_zero_and_counts_as_passed(rec: Any) -> None:
    whole_test(rec, "t::a", call="strange")
    assert counts(rec) == (1, 0, 0, 0)


def test_a_warning_moves_a_passed_test_to_warn(rec: Any) -> None:
    whole_test(rec, "t::a")
    rec.pytest_warning_recorded(when="runtest", nodeid="t::a")
    assert counts(rec) == (0, 1, 0, 0)


def test_a_warning_before_the_teardown_also_warns(rec: Any) -> None:
    rec.pytest_warning_recorded(when="runtest", nodeid="t::a")
    whole_test(rec, "t::a")
    assert counts(rec) == (0, 1, 0, 0)


def test_a_failed_test_with_a_warning_is_failed(rec: Any) -> None:
    whole_test(rec, "t::a", call="failed")
    rec.pytest_warning_recorded(when="runtest", nodeid="t::a")
    assert counts(rec) == (0, 0, 0, 1)


def test_a_skipped_test_with_a_warning_is_warned(rec: Any) -> None:
    whole_test(rec, "t::a", call="skipped")
    rec.pytest_warning_recorded(when="runtest", nodeid="t::a")
    assert counts(rec) == (0, 1, 0, 0)


@pytest.mark.parametrize(
    ("when", "nodeid"), [("collect", "t::a"), ("config", "t::a"), ("runtest", "")]
)
def test_a_warning_outside_a_test_counts_for_none(rec: Any, when: str, nodeid: str) -> None:
    whole_test(rec, "t::a")
    rec.pytest_warning_recorded(when=when, nodeid=nodeid)
    assert counts(rec) == (1, 0, 0, 0) and rec.warned == set()


def test_the_four_counts_are_disjoint(rec: Any) -> None:
    whole_test(rec, "t::p")
    whole_test(rec, "t::w")
    rec.pytest_warning_recorded(when="runtest", nodeid="t::w")
    whole_test(rec, "t::s", call="skipped")
    whole_test(rec, "t::x", call="xfailed")
    whole_test(rec, "t::f", call="failed")
    assert counts(rec) == (1, 1, 2, 1)


def test_a_test_is_counted_once_however_many_reports(rec: Any) -> None:
    whole_test(rec, "t::a")
    rec.pytest_runtest_logreport(report("t::a", "teardown", ""))
    assert counts(rec) == (1, 0, 0, 0)


# ----- P5: total -----


def test_collection_finish_sets_the_total_from_the_items(rec: Any) -> None:
    rec.pytest_collection_finish(SimpleNamespace(items=[1, 2, 3]))
    assert rec.total == 3 and rec.record()["total"] == 3


def test_collection_finish_with_no_items_keeps_none(rec: Any) -> None:
    rec.pytest_collection_finish(SimpleNamespace(items=[]))
    assert rec.total is None and rec.record()["total"] is None


def test_the_xdist_controller_keeps_the_largest_collection(rec: Any) -> None:
    rec.pytest_xdist_node_collection_finished(ids=["a", "b"])
    rec.pytest_xdist_node_collection_finished(ids=["a", "b", "c", "d"])
    rec.pytest_xdist_node_collection_finished(ids=["a"])
    assert rec.total == 4


def test_the_optional_hooks_are_marked_optional(mod: ModuleType) -> None:
    for name in ("pytest_xdist_node_collection_finished", "pytest_warning_recorded"):
        marker = getattr(getattr(mod.Recorder, name), "pytest_impl", None)
        assert marker is not None and marker["optionalhook"] is True, name


# ----- P6: writing -----


def test_the_record_keys_and_session(rec: Any) -> None:
    rec.total = 5
    whole_test(rec, "t::a")
    record = rec.record()
    assert list(record) == ["session", "total", "passed", "warned", "skipped", "failed"]
    assert record["session"] == "s1" and record["total"] == 5


def test_the_first_report_writes_one_json_object_through_a_temp_file(
    rec: Any, target: Target
) -> None:
    whole_test(rec, "t::a")
    rec.pytest_sessionfinish()
    assert "tally.json.tmp" not in target.store  # replaced onto the real name
    data = json.loads(target.store["tally.json"])
    assert data == {
        "session": "s1",
        "total": None,
        "passed": 1,
        "warned": 0,
        "skipped": 0,
        "failed": 0,
    }


def test_writes_are_throttled(rec: Any, target: Target) -> None:
    rec.pytest_runtest_logreport(report("t::a", "setup", ""))  # due: the first write
    rec.pytest_runtest_logreport(report("t::a", "call", "passed"))
    rec.pytest_runtest_logreport(report("t::a", "teardown", ""))
    rec.pytest_warning_recorded(when="runtest", nodeid="t::a")
    assert len(target.writes) == 1
    assert json.loads(target.store["tally.json"])["passed"] == 0  # the earlier, stale record
    rec.written_at = -math.inf
    rec.pytest_runtest_logreport(report("t::b", "setup", ""))
    assert len(target.writes) == 2


def test_a_warning_writes_when_due(rec: Any, target: Target) -> None:
    whole_test(rec, "t::a")
    rec.written_at = -math.inf
    rec.pytest_warning_recorded(when="runtest", nodeid="t::a")
    assert json.loads(target.store["tally.json"])["warned"] == 1


def test_session_finish_always_writes(rec: Any, target: Target) -> None:
    whole_test(rec, "t::a")
    before = len(target.writes)
    rec.pytest_sessionfinish()
    assert len(target.writes) == before + 1
    assert json.loads(target.store["tally.json"])["passed"] == 1


def test_write_every_is_half_a_second(rec: Any, target: Target) -> None:
    rec.pytest_runtest_logreport(report("t::a", "setup", ""))
    stamp = rec.written_at
    assert stamp != -math.inf
    rec.written_at = stamp - 0.6  # older than WRITE_EVERY_S
    before = len(target.writes)
    rec.pytest_runtest_logreport(report("t::a", "call", "passed"))
    assert len(target.writes) == before + 1


# ----- P7: never breaks a test run -----


def test_a_bad_report_does_not_propagate(rec: Any) -> None:
    rec.pytest_runtest_logreport(object())
    rec.pytest_warning_recorded(when=None, nodeid=None)
    rec.pytest_collection_finish(object())
    rec.pytest_xdist_node_collection_finished(ids=None)
    assert counts(rec) == (0, 0, 0, 0)


def test_a_failing_teststatus_hook_does_not_propagate(mod: ModuleType, target: Target) -> None:
    config = stub_config()

    def boom(report: Any, config: Any) -> Any:
        raise RuntimeError("hook")

    config.hook.pytest_report_teststatus = boom
    recorder = mod.Recorder(target, config, session_id="s")
    recorder.pytest_runtest_logreport(report("t::a", "call", "passed"))


def test_a_failing_write_does_not_propagate(
    mod: ModuleType, rec: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(src: Any, dst: Any) -> None:
        raise OSError("disk")

    monkeypatch.setattr(mod.os, "replace", boom)
    whole_test(rec, "t::a")
    rec.pytest_sessionfinish()
