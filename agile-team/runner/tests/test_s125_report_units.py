"""s125: pure parts of test reports: report options, JUnit, building and running."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest
import tomli_w
from agile_team import config as cfg
from agile_team import junit, system, test_reports
from agile_team.junit import Case, Report, Result

from .conftest import PY_CONFIG
from .fake_system import FakeSystem
from .s125_helpers import FAIL, FOLDER, OPTIONS, ROOT, Writer, case, report

# ---- P1 / P20: report options from the preset and the config ------------------------------


def load_with(repo: Path, **toolchain: object) -> cfg.Config:
    raw = {**PY_CONFIG, "toolchain": {**PY_CONFIG["toolchain"], **toolchain}}
    system.write_text(repo / cfg.CONFIG_NAME, tomli_w.dumps(raw))
    return cfg.load(repo)


def test_python_preset_gives_the_report_options(configured: Path) -> None:
    assert cfg.load(configured).toolchain.report == OPTIONS
    assert OPTIONS.on


def test_config_report_keys_override_one_option(configured: Path) -> None:
    report_keys = {"option": "--junit={file}", "bogus": "dropped"}
    got = load_with(configured, report=report_keys).toolchain.report
    assert got == cfg.ReportOptions("--junit={file}", OPTIONS.deselect, OPTIONS.ignore)


def test_no_report_table_means_reporting_off() -> None:
    assert not cfg.ReportOptions().on


def test_report_placeholder_only_in_test_commands(configured: Path) -> None:
    with pytest.raises(cfg.ConfigError, match=r"\{report\} only works in the test and coverage"):
        load_with(configured, lint="ruff check {report}")


def test_report_placeholder_needs_an_option(configured: Path) -> None:
    with pytest.raises(cfg.ConfigError, match="option is not set"):
        load_with(configured, test="pytest {report}", report={"option": ""})


# ---- P6: JUnit parsing ---------------------------------------------------------------------


def parsed(*cases: str, root: str = ROOT) -> tuple[Case, ...]:
    return junit.parse(report(*cases), root)


def test_a_class_case_gets_a_repo_relative_node_id() -> None:
    (got,) = parsed(case("tests/test_g.py", "tests.test_g.TestX", "test_y[a]", 9))
    assert got.id == f"{ROOT}/tests/test_g.py::TestX::test_y[a]"
    assert (got.file, got.line, got.result) == (f"{ROOT}/tests/test_g.py", 10, Result.PASSED)


def test_a_module_level_case_has_no_class_part() -> None:
    (got,) = parsed(case("tests/test_g.py", "tests.test_g", "test_y", 0))
    assert got.id == f"{ROOT}/tests/test_g.py::test_y"
    assert got.line == 1


def test_a_nested_class_uses_double_colons() -> None:
    (got,) = parsed(case("tests/test_g.py", "tests.test_g.TestX.TestIn", "test_y", 3))
    assert got.id.endswith("test_g.py::TestX::TestIn::test_y")


def test_an_empty_classname_is_a_file_that_failed_to_collect() -> None:
    (got,) = parsed(case("tests/test_bad.py", "", "tests.test_bad", None, FAIL))
    assert got.id == f"{ROOT}/tests/test_bad.py"
    assert got.line is None
    assert got.result is Result.FAILED


def test_an_empty_root_leaves_ids_unprefixed() -> None:
    (got,) = parsed(case("tests/test_g.py", "tests.test_g", "test_y", 0), root="")
    assert got.id == "tests/test_g.py::test_y"


@pytest.mark.parametrize(
    ("child", "result"),
    [
        (FAIL, Result.FAILED),
        ('<error message="e">t</error>', Result.FAILED),
        ('<skipped message="s"/>', Result.SKIPPED),
        ("", Result.PASSED),
    ],
)
def test_the_child_element_gives_the_result(child: str, result: Result) -> None:
    (got,) = parsed(case("tests/t.py", "tests.t", "test_a", 0, child))
    assert got.result is result


def test_a_failure_keeps_the_first_line_of_its_message() -> None:
    (got,) = parsed(case("tests/t.py", "tests.t", "test_a", 0, FAIL))
    assert got.message == "boom"


def test_bad_xml_raises_report_error() -> None:
    with pytest.raises(junit.ReportError):
        junit.parse("<testsuites><oops", ROOT)


def test_report_asks_by_id_and_by_file() -> None:
    cases = parsed(
        case("tests/a.py", "tests.a", "test_ok", 0),
        case("tests/a.py", "tests.a", "test_bad", 4, FAIL),
        case("tests/b.py", "tests.b", "test_ok", 0),
        case("tests/c.py", "tests.c", "test_skip", 0, "<skipped/>"),
    )
    got = Report(cases)
    a, b, c = (f"{ROOT}/tests/{n}.py" for n in "abc")
    assert [x.id for x in got.failed()] == [f"{a}::test_bad"]
    assert got.holds(f"{a}::test_ok") and got.holds(b) and not got.holds(f"{ROOT}/tests/z.py")
    assert got.passed(f"{a}::test_ok") and not got.passed(f"{a}::test_bad")
    assert got.passed(b)
    assert not got.passed(a)  # one case of the file failed
    assert not got.passed(c) and not got.passed(f"{c}::test_skip")
    assert not got.passed(f"{ROOT}/tests/z.py")  # a file the report does not hold


# ---- P2 / P5: building the command ---------------------------------------------------------


def build(template: str) -> test_reports.Built:
    return test_reports.build(template, test_reports.Reporting(OPTIONS, FOLDER))


def words(command: str) -> list[str]:
    return shlex.split(command)


def test_a_command_without_placeholder_gets_one_appended() -> None:
    built = build("uv run pytest -q")
    assert words(built.command) == [
        *["uv", "run", "pytest", "-q"],
        f"--junitxml={FOLDER}/1.xml",
        *["-o", "junit_family=xunit1"],
    ]
    assert built.files == (("", FOLDER / "1.xml"),)


def test_a_literal_brace_in_the_command_is_untouched() -> None:
    built = build("echo {x} && pytest {report}")
    assert "{x}" in built.command and "{report}" not in built.command


def test_each_root_in_a_chain_has_its_own_file_and_ids() -> None:
    built = build("pytest {report:a} && pytest {report:b}")
    first, second = built.command.split("&&")
    assert f"{FOLDER}/1.xml" in first and f"{FOLDER}/2.xml" in second
    assert built.files == (("a", FOLDER / "1.xml"), ("b", FOLDER / "2.xml"))


# ---- P3 / P4 / P18: running a built command ------------------------------------------------


def xml_for(name: str) -> str:
    return report(case("tests/t.py", "tests.t", name, 0))


def test_run_reads_every_report_file_and_prefixes_the_root(fake: FakeSystem) -> None:
    built = build("pytest {report:a} && pytest {report:b}")
    got = test_reports.run(built, Writer([xml_for("test_a"), xml_for("test_b")]))
    assert [c.id for c in got.report.cases] == ["a/tests/t.py::test_a", "b/tests/t.py::test_b"]


def test_run_reads_the_files_that_exist_when_a_link_did_not_run(fake: FakeSystem) -> None:
    built = build("pytest {report:a} && pytest {report:b}")
    got = test_reports.run(built, Writer([xml_for("test_a"), None], code=1))
    assert [c.id for c in got.report.cases] == ["a/tests/t.py::test_a"]
    assert got.code == 1


def test_run_with_no_report_file_has_no_report(fake: FakeSystem) -> None:
    got = test_reports.run(build("pytest {report}"), Writer([None], code=1, out="boom"))
    assert got.report is None and got.out == "boom"


def test_run_treats_a_bad_report_as_missing(fake: FakeSystem) -> None:
    got = test_reports.run(build("pytest {report}"), Writer(["<oops"]))
    assert got.report is None


def test_run_empties_the_folder_first(fake: FakeSystem) -> None:
    system.make_dirs(FOLDER)
    system.write_text(FOLDER / "1.xml", xml_for("test_stale"))
    got = test_reports.run(build("pytest {report}"), Writer([None]))
    assert got.report is None
