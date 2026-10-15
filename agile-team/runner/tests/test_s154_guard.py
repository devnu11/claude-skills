"""s154: a guard hit in fixture setup is a pytest outcome; temp dirs refused; failures kept."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agile_team import gates, junit, results, suite_runs, system
from agile_team.results import Ran
from agile_team.test_reports import TestRun

from . import os_guard

# ---------- AC1: RealOsCall is a pytest outcome ----------


def test_s154_round2_ac1_real_os_call_is_a_pytest_failed_but_not_an_exception() -> None:
    assert issubclass(os_guard.RealOsCall, pytest.fail.Exception)
    assert issubclass(os_guard.RealOsCall, BaseException)
    assert not issubclass(os_guard.RealOsCall, Exception)


# ---------- AC2: temp-dir fixtures refused at collection ----------


def stub(names: tuple[str, ...] | None, folder: str = "tests") -> Any:
    """A collected item: a path under ``folder`` and a fixture closure."""
    item = SimpleNamespace(path=Path("/r/agile-team/runner") / folder / "test_x.py", stash={})
    if names is not None:
        item.fixturenames = names
    return item


def test_s154_round2_ac2_os_fixtures_names_the_four_temp_dir_fixtures() -> None:
    assert set(os_guard.OS_FIXTURES) == {
        "tmp_path",
        "tmp_path_factory",
        "tmpdir",
        "tmpdir_factory",
    }


@pytest.mark.parametrize("name", ["tmp_path", "tmp_path_factory", "tmpdir", "tmpdir_factory"])
def test_s154_round2_ac2_each_temp_dir_fixture_is_found(name: str) -> None:
    assert os_guard.os_fixtures(stub(("fake", name))) == (name,)


def test_s154_round2_ac2_names_are_sorted() -> None:
    assert os_guard.os_fixtures(stub(("tmpdir", "tmp_path"))) == ("tmp_path", "tmpdir")


def test_s154_round2_ac2_e2e_items_and_items_without_a_closure_are_not_refused() -> None:
    assert os_guard.os_fixtures(stub(("tmp_path",), "tests/e2e")) == ()
    assert os_guard.os_fixtures(stub(None)) == ()
    assert os_guard.os_fixtures(stub(("fake",))) == ()
    assert os_guard.os_fixtures(stub(())) == ()


def test_s154_round2_ac2_mark_refusals_stashes_the_text_only_on_requesting_items() -> None:
    bad, clean = stub(("tmpdir", "tmp_path")), stub(("fake",))
    e2e = stub(("tmp_path",), "tests/e2e")
    os_guard.mark_refusals([bad, clean, e2e])
    text = os_guard.OS_FIXTURE_REFUSED.format(names="tmp_path, tmpdir")
    assert bad.stash[os_guard.REFUSAL] == text
    assert os_guard.REFUSAL not in clean.stash
    assert os_guard.REFUSAL not in e2e.stash


def test_s154_round2_ac2_the_refusal_text_gives_the_advice() -> None:
    text = os_guard.OS_FIXTURE_REFUSED
    assert "{names}" in text
    assert "fake world" in text
    assert "tests/e2e/" in text


def test_s154_round2_ac2_refuse_marked_fails_with_the_stashed_text() -> None:
    item = stub(("tmp_path",))
    os_guard.mark_refusals([item])
    with pytest.raises(pytest.fail.Exception) as raised:
        os_guard.refuse_marked(item)
    assert "tmp_path" in str(raised.value)
    assert "reach the real OS" in str(raised.value)


def test_s154_round2_ac2_refuse_marked_does_nothing_for_an_unmarked_item() -> None:
    os_guard.refuse_marked(stub(("fake",)))


# ---------- AC3: first error lines from the JUnit report ----------


def report_xml(*cases: str) -> str:
    return f"<testsuite>{''.join(cases)}</testsuite>"


def case(name: str, inner: str = "") -> str:
    head = f'<testcase classname="tests.test_a" name="{name}" file="tests/test_a.py">'
    return f"{head}{inner}</testcase>"


def parsed(inner: str) -> junit.Case:
    return junit.parse(report_xml(case("t", inner)), "")[0]


def test_s154_round2_ac3_detail_holds_the_marked_error_lines_without_the_marker() -> None:
    text = "def t():\n>   assert 1 == 2\nE   AssertionError: no\nE   where 1 = x\n"
    got = parsed(f'<failure message="m">{text}</failure>')
    assert got.detail == "AssertionError: no\nwhere 1 = x"


def test_s154_round2_ac3_detail_is_capped() -> None:
    text = "\n".join(f"E   line {n}" for n in range(9))
    got = parsed(f"<error>{text}</error>")
    assert got.detail.splitlines() == [f"line {n}" for n in range(junit.ERROR_LINES)]


def test_s154_round2_ac3_without_marked_lines_the_first_lines_of_the_text() -> None:
    text = "\n\nfirst\n\nsecond\nthird\nfourth\nfifth\nsixth\n"
    got = parsed(f"<error>{text}</error>")
    assert got.detail.splitlines() == ["first", "second", "third", "fourth", "fifth"]


def test_s154_round2_ac3_empty_text_gives_the_message_attribute() -> None:
    assert parsed('<failure message="boom"></failure>').detail == "boom"


def test_s154_round2_ac3_a_passing_case_has_no_detail() -> None:
    assert parsed("").detail == ""
    assert parsed("<skipped/>").detail == ""


def test_s154_round2_ac3_message_keeps_its_first_line_meaning() -> None:
    assert parsed('<failure message="one&#10;two">E   x</failure>').message == "one"


def test_s154_round2_ac3_report_failures_maps_failed_and_errored_ids_in_order() -> None:
    xml = report_xml(
        case("a", "<failure>E   bad a</failure>"),
        case("b"),
        case("c", "<error>E   bad c</error>"),
        case("d", "<skipped/>"),
    )
    got = junit.Report(junit.parse(xml, "")).failures
    assert list(got.items()) == [
        ("tests/test_a.py::a", "bad a"),
        ("tests/test_a.py::c", "bad c"),
    ]
    assert junit.Report().failures == {}


# ---------- AC3: what the gate keeps ----------


def red_run(report: junit.Report | None) -> TestRun:
    return TestRun(1, "out", report, {})


def two_failures() -> junit.Report:
    xml = report_xml(case("a", "<failure>E   x</failure>"), case("b", "<error>E   y</error>"))
    return junit.Report(junit.parse(xml, ""))


def test_s154_round2_ac3_failures_of_a_run_come_from_its_report() -> None:
    assert gates._read_failures(red_run(two_failures())) == {
        "tests/test_a.py::a": "x",
        "tests/test_a.py::b": "y",
    }


def test_s154_round2_ac3_a_run_without_a_report_has_no_failures() -> None:
    assert gates._read_failures(red_run(None)) == {}


def test_s154_round2_ac3_test_ran_has_code_tail_and_failures() -> None:
    ran = gates._test_ran("test", red_run(two_failures()))
    assert (ran.name, ran.code, ran.tail) == ("test", 1, "out")
    assert set(ran.failures) == {"tests/test_a.py::a", "tests/test_a.py::b"}


def test_s154_round2_ac3_a_suite_run_carries_failures_and_the_summary_ran_keeps_the_last() -> None:
    runs = [
        suite_runs.SuiteRun(1, 2, 0, 1.0, "ok"),
        suite_runs.SuiteRun(2, 2, 1, 1.0, "bad", failures={"t::x": "boom"}),
    ]
    assert runs[0].failures == {}
    outcome = gates._suite_outcome(gates.Outcome(gates.Verdict.PASS), runs)
    assert outcome.extra_ran[-1].failures == {"t::x": "boom"}


# ---------- AC3: results store and brief ----------


def ran(**kw: Any) -> Ran:
    return Ran("test", 1, "tail", "1234567890", "tests gate", **kw)


def test_s154_round2_ac3_failures_round_trip_through_the_store(scratch: Path) -> None:
    store = results.Results(scratch)
    store.keep("s1", ran(failures={"a::b": "E1\nE2"}))
    assert store.latest("s1", "test").failures == {"a::b": "E1\nE2"}


def test_s154_round2_ac3_an_old_file_without_the_key_loads_with_no_failures(scratch: Path) -> None:
    path = scratch / "results" / "s1" / "test.json"
    system.make_dirs(path.parent)
    old = {"name": "test", "code": 1, "tail": "t", "at": "", "where": ""}
    system.write_text(path, json.dumps(old))
    assert results.Results(scratch).latest("s1", "test").failures == {}


def many(count: int) -> dict[str, str]:
    return {f"t::n{n}": f"line a{n}\nline b{n}" for n in range(count)}


def test_s154_round2_ac3_section_lists_failures_after_the_fence() -> None:
    text = results.section([ran(failures=many(2))])
    head = results.FAILURES_HEAD.format(count=2)
    assert text.index("```text") < text.rindex("```") < text.index(head)
    assert f"- t::n0\n{results.INDENT}line a0\n{results.INDENT}line b0" in text
    assert results.FAILURES_MORE.split("{")[0] not in text


def test_s154_round2_ac3_section_caps_the_list_and_counts_the_rest() -> None:
    text = results.section([ran(failures=many(results.FAILURES_SHOWN + 3))])
    assert "t::n9" in text
    assert "t::n10" not in text
    assert results.FAILURES_MORE.format(count=3) in text


def test_s154_round2_ac3_section_without_failures_has_no_failure_list() -> None:
    assert "Failing tests" not in results.section([ran()])
    assert results.format_failures({}) == ""


# ---------- AC3: gate events ----------


def test_s154_round2_ac3_event_failures_merges_with_later_runs_winning() -> None:
    first = ran(failures={"a": "old", "b": "b"})
    later = Ran("suite-runs", 1, "t", failures={"a": "new"})
    assert results.collect_event_failures((first, later)) == {"failures": {"a": "new", "b": "b"}}


def test_s154_round2_ac3_event_failures_caps_and_counts_more() -> None:
    got = results.collect_event_failures((ran(failures=many(results.FAILURES_SHOWN + 4)),))
    assert len(got["failures"]) == results.FAILURES_SHOWN
    assert got["failures_more"] == 4


def test_s154_round2_ac3_event_failures_is_empty_without_failures() -> None:
    assert results.collect_event_failures((None, ran())) == {}
    assert results.collect_event_failures(()) == {}


# ---------- AC3: dashboard page and fixture ----------


def dashboard(*name: str) -> str:
    return system.read_text(resources.files("agile_team.dashboard").joinpath(*name))


def test_s154_round2_ac3_the_gate_entry_body_shows_the_failures() -> None:
    page = dashboard("index.html")
    assert "function failuresText" in page or "const failuresText" in page
    assert "failuresText(e.data)" in page
    assert "e.data.failures_more" in page or "data.failures_more" in page


def test_s154_round2_ac3_the_fixture_bounce_event_carries_failures() -> None:
    events = json.loads(dashboard("fixtures", "snapshot.json"))
    text = json.dumps(events)
    assert "tests/test_csv_export.py::test_quotes_fields" in text
