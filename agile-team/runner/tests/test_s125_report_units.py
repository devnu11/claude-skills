"""s125: pure parts of pending tests: report options, JUnit, the registry, report runs."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest
import tomli_w
from agile_team import config as cfg
from agile_team import junit, pending_tests, stages, system, test_reports
from agile_team.junit import Case, Report, Result
from agile_team.pending_tests import PendingSet, Registry

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


# ---- P10: the step's changed lines from a real git diff -----------------------------------

DIFF = """\
diff --git a/agile-team/runner/tests/test_new.py b/agile-team/runner/tests/test_new.py
new file mode 100644
--- /dev/null
+++ b/agile-team/runner/tests/test_new.py
@@ -0,0 +1,3 @@
+def test_a():
+    pass
+
diff --git a/agile-team/runner/tests/test_old.py b/agile-team/runner/tests/test_old.py
--- a/agile-team/runner/tests/test_old.py
+++ b/agile-team/runner/tests/test_old.py
@@ -10,2 +10,2 @@ def test_b():
-    x = 1
+    x = 2
@@ -30,2 +29,0 @@ def test_c():
-    gone = 1
@@ -40 +40 @@ def test_d():
-    y = 1
+    y = 2
"""


def test_changed_lines_reads_the_new_side_of_every_hunk() -> None:
    got = pending_tests.changed_lines(DIFF, [])
    assert got["agile-team/runner/tests/test_new.py"] == (range(1, 4),)
    old = got["agile-team/runner/tests/test_old.py"]
    assert old == (range(10, 12), range(29, 31), range(40, 41))


def test_an_untracked_file_counts_whole() -> None:
    got = pending_tests.changed_lines("", ["tests/new.py"])
    assert got == {"tests/new.py": (pending_tests.WHOLE,)}


def test_no_diff_and_no_untracked_files_change_nothing() -> None:
    assert pending_tests.changed_lines("", []) == {}


# ---- P11: touched --------------------------------------------------------------------------

F = f"{ROOT}/tests/t.py"


def three_tests() -> Report:
    starts = (("a", 1), ("b", 10), ("c", 20))
    cases = [case("tests/t.py", "tests.t", f"test_{n}", line - 1) for n, line in starts]
    return Report(parsed(*cases))


def is_touched(name: str, changed: dict) -> bool:
    got = three_tests()
    (target,) = [c for c in got.cases if c.id.endswith(f"::test_{name}")]
    return pending_tests.touched(target, pending_tests.Touch(got, changed))


def test_a_test_whose_body_line_changed_is_touched() -> None:
    changed = {F: (range(12, 13),)}
    assert is_touched("b", changed)


def test_a_neighbour_in_the_same_file_is_not_touched() -> None:
    changed = {F: (range(12, 13),)}
    assert not is_touched("a", changed) and not is_touched("c", changed)


def test_the_last_test_extends_to_the_end_of_the_file() -> None:
    assert is_touched("c", {F: (range(500, 501),)})


def test_a_test_in_an_unchanged_file_is_not_touched() -> None:
    assert not is_touched("b", {"other.py": (pending_tests.WHOLE,)})


def test_a_file_id_is_touched_when_its_file_changed() -> None:
    (bad,) = parsed(case("tests/bad.py", "", "tests.bad", None, FAIL))
    ctx = pending_tests.Touch(Report((bad,)), {bad.file: (range(1, 2),)})
    assert pending_tests.touched(bad, ctx)
    assert not pending_tests.touched(bad, pending_tests.Touch(Report((bad,)), {}))


# ---- P8 (3): split_red, P12 (b): leaving, P17: counts --------------------------------------

NEW = f"{ROOT}/tests/test_new.py"
OLD = f"{ROOT}/tests/test_old.py"


def two_files() -> Report:
    return Report(
        parsed(
            case("tests/test_new.py", "tests.test_new", "test_fresh", 0, FAIL),
            case("tests/test_new.py", "tests.test_new", "test_fine", 5),
            case("tests/test_old.py", "tests.test_old", "test_stable", 0),
            case("tests/test_old.py", "tests.test_old", "test_broken", 5, FAIL),
        )
    )


def test_split_red_makes_changed_failures_pending_and_the_rest_real() -> None:
    ask = pending_tests.RedAsk({NEW: (range(1, 3),)}, ())
    got = pending_tests.split_red(two_files(), ask)
    assert got.pending == (f"{NEW}::test_fresh",)
    assert got.real == (f"{OLD}::test_broken",)


def test_split_red_keeps_the_storys_own_ids_pending_though_unchanged() -> None:
    ask = pending_tests.RedAsk({NEW: (range(1, 3),)}, (f"{OLD}::test_broken",))
    got = pending_tests.split_red(two_files(), ask)
    assert sorted(got.pending) == [f"{NEW}::test_fresh", f"{OLD}::test_broken"]
    assert got.real == ()


def test_split_red_with_no_failures_is_empty() -> None:
    got = pending_tests.split_red(Report(), pending_tests.RedAsk({}, ()))
    assert (got.pending, got.real) == ((), ())


def test_leaving_names_own_ids_that_did_not_pass_and_those_gone() -> None:
    own = (f"{NEW}::test_fresh", f"{NEW}::test_fine", f"{OLD}::test_gone")
    got = pending_tests.leaving(two_files(), own)
    assert got.failing == (f"{NEW}::test_fresh",)
    assert got.missing == (f"{OLD}::test_gone",)


def test_leaving_treats_a_skipped_own_id_as_failing() -> None:
    got = Report(parsed(case("tests/t.py", "tests.t", "test_a", 0, "<skipped/>")))
    assert pending_tests.leaving(got, (f"{F}::test_a",)).failing == (f"{F}::test_a",)


def test_counts_text_counts_skipped_ids_the_report_does_not_hold() -> None:
    skipped = {"s125": ("a::1", "a::2", "a::3"), "s130": ("b::1",)}
    assert pending_tests.counts_text(skipped, Report()) == "pending (s125): 3, pending (s130): 1"


def test_counts_text_leaves_out_ids_that_ran_anyway() -> None:
    got = Report(parsed(case("tests/t.py", "tests.t", "test_a", 0)))
    assert pending_tests.counts_text({"s1": (f"{F}::test_a", "x::y")}, got) == "pending (s1): 1"


def test_counts_text_is_empty_with_nothing_skipped() -> None:
    assert pending_tests.counts_text({}, Report()) == ""


# ---- the registry --------------------------------------------------------------------------


def test_registry_of_and_others() -> None:
    reg = Registry({"s1": ("a",), "s2": ("b", "c")})
    assert reg.of("s1") == ("a",) and reg.of("zz") == ()
    assert reg.others("s1") == {"s2": ("b", "c")}
    assert reg.others("") == {"s1": ("a",), "s2": ("b", "c")}


def test_with_ids_sets_and_drops_a_story() -> None:
    reg = Registry({"s1": ("a",)})
    assert reg.with_ids(PendingSet("s2", ("z",))).entries == {"s1": ("a",), "s2": ("z",)}
    assert reg.with_ids(PendingSet("s1", ())).entries == {}


def test_text_is_sorted_indented_json_with_a_newline() -> None:
    text = Registry({"s2": ("b", "a"), "s1": ("c",)}).text()
    assert text == json.dumps({"s1": ["c"], "s2": ["a", "b"]}, indent=2) + "\n"


def test_parse_round_trips() -> None:
    reg = Registry({"s1": ("a", "b")})
    assert pending_tests.parse(reg.text()) == reg


@pytest.mark.parametrize("bad", ["[]", '{"s1": "x"}', '{"s1": [1]}', "not json", '"x"'])
def test_parse_refuses_a_malformed_registry(bad: str) -> None:
    with pytest.raises(pending_tests.RegistryError):
        pending_tests.parse(bad)


def test_read_of_a_missing_file_is_an_empty_registry(repo: Path) -> None:
    assert pending_tests.read(repo) == Registry()


def test_write_then_read(repo: Path) -> None:
    reg = Registry({"s1": ("a",)})
    pending_tests.write(repo, reg)
    assert system.read_text(repo / pending_tests.REGISTRY) == reg.text()
    assert pending_tests.read(repo) == reg


def test_read_of_a_bad_file_raises(repo: Path) -> None:
    system.make_dirs(repo / ".team")
    system.write_text(repo / pending_tests.REGISTRY, "{")
    with pytest.raises(pending_tests.RegistryError):
        pending_tests.read(repo)


# ---- P2 / P5: building the command ---------------------------------------------------------


def build(template: str, skipped: dict, options: cfg.ReportOptions = OPTIONS) -> test_reports.Built:
    reporting = test_reports.Reporting(options, FOLDER)
    return test_reports.build(template, test_reports.Ask(reporting, skipped))


def words(command: str) -> list[str]:
    return shlex.split(command)


def test_a_command_without_placeholder_gets_one_appended() -> None:
    built = build("uv run pytest -q", {})
    assert words(built.command) == [
        *["uv", "run", "pytest", "-q"],
        f"--junitxml={FOLDER}/1.xml",
        *["-o", "junit_family=xunit1"],
    ]
    assert built.files == (("", FOLDER / "1.xml"),)


def test_a_literal_brace_in_the_command_is_untouched() -> None:
    built = build("echo {x} && pytest {report}", {})
    assert "{x}" in built.command and "{report}" not in built.command


def test_skip_options_follow_the_report_option() -> None:
    skipped = {"s2": ("tests/x.py::t[a]", "tests/y.py")}
    built = build("pytest {report}", skipped)
    assert words(built.command)[-2:] == ["--deselect=tests/x.py::t[a]", "--ignore=tests/y.py"]
    assert built.skipped == skipped


def test_each_root_in_a_chain_has_its_own_file_and_ids() -> None:
    skipped = {"s2": ("a/tests/x.py::t", "b/tests/y.py::u", "b/tests/z.py")}
    built = build("pytest {report:a} && pytest {report:b}", skipped)
    first, second = built.command.split("&&")
    assert f"{FOLDER}/1.xml" in first and f"{FOLDER}/2.xml" in second
    assert "--deselect=tests/x.py::t" in first and "tests/y.py" not in first
    assert "--deselect=tests/y.py::u" in second and "--ignore=tests/z.py" in second
    assert "tests/x.py" not in second
    assert built.files == (("a", FOLDER / "1.xml"), ("b", FOLDER / "2.xml"))


def test_an_empty_template_skips_nothing() -> None:
    options = cfg.ReportOptions(OPTIONS.option, "", "")
    assert "x.py" not in build("pytest {report}", {"s2": ("x.py::t", "x.py")}, options).command


def test_skip_options_make_ids_root_relative_and_choose_the_template() -> None:
    under = test_reports.Under("a", ("a/tests/x.py::t", "a/tests/y.py", "b/tests/q.py::t"))
    assert test_reports.skip_options(OPTIONS, under) == [
        "--deselect=tests/x.py::t",
        "--ignore=tests/y.py",
    ]


def test_skip_line_is_the_options_joined() -> None:
    under = test_reports.Under(ROOT, (f"{ROOT}/tests/x.py::t", f"{ROOT}/tests/y.py"))
    assert test_reports.skip_line(OPTIONS, under) == "--deselect=tests/x.py::t --ignore=tests/y.py"
    assert test_reports.skip_line(OPTIONS, test_reports.Under(ROOT, ())) == ""


# ---- P3 / P4 / P18: running a built command ------------------------------------------------


def xml_for(name: str) -> str:
    return report(case("tests/t.py", "tests.t", name, 0))


def test_run_reads_every_report_file_and_prefixes_the_root(fake: FakeSystem) -> None:
    built = build("pytest {report:a} && pytest {report:b}", {})
    got = test_reports.run(built, Writer([xml_for("test_a"), xml_for("test_b")]))
    assert [c.id for c in got.report.cases] == ["a/tests/t.py::test_a", "b/tests/t.py::test_b"]


def test_run_reads_the_files_that_exist_when_a_link_did_not_run(fake: FakeSystem) -> None:
    built = build("pytest {report:a} && pytest {report:b}", {})
    got = test_reports.run(built, Writer([xml_for("test_a"), None], code=1))
    assert [c.id for c in got.report.cases] == ["a/tests/t.py::test_a"]
    assert got.code == 1


def test_run_with_no_report_file_has_no_report(fake: FakeSystem) -> None:
    got = test_reports.run(build("pytest {report}", {}), Writer([None], code=1, out="boom"))
    assert got.report is None and got.out == "boom"


def test_run_treats_a_bad_report_as_missing(fake: FakeSystem) -> None:
    got = test_reports.run(build("pytest {report}", {}), Writer(["<oops"]))
    assert got.report is None


def test_run_empties_the_folder_first(fake: FakeSystem) -> None:
    system.make_dirs(FOLDER)
    system.write_text(FOLDER / "1.xml", xml_for("test_stale"))
    got = test_reports.run(build("pytest {report}", {}), Writer([None]))
    assert got.report is None


def test_run_tells_the_tally_how_many_ids_it_skipped_before_the_command(
    fake: FakeSystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    monkeypatch.setattr(stages, "hear", lambda text: events.append(f"heard {text}"))
    writer = Writer([xml_for("test_a")])

    def runner(command: str) -> tuple[int, str]:
        events.append("ran")
        return writer(command)

    test_reports.run(build("pytest {report}", {"s2": ("x::a", "x::b")}), runner)
    assert events == ['heard {"pending": 2}', "ran"]
