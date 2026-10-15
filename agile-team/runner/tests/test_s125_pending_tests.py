"""s125: pending tests through the gates, the runtime, the guard, the CLI and the docs."""

from __future__ import annotations

import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import tomli_w
from agile_team import (
    cli,
    fullcheck,
    gates,
    guard,
    onboard,
    pending_tests,
    runner_tools,
    system,
    test_reports,
    test_tally,
)
from agile_team import config as cfg
from agile_team.gates import Serving, Verdict
from agile_team.pending_tests import PendingSet, Registry
from agile_team.roles import Handoff, TestClaim

from .conftest import PY_CONFIG, FakeRunner
from .fake_system import SKILL_DIR, Done, FakeSystem
from .s125_helpers import (
    FAIL,
    FOLDER,
    NEW_FAIL,
    OLD_FAIL,
    OLD_PASS,
    OPTIONS,
    ROOT,
    Writer,
    case,
    report,
)

TEST_CMD = f"pytest {{report:{ROOT}}}"
COV_CMD = f"pytest --cov {{report:{ROOT}}}"
CHANGED = {f"{ROOT}/tests/test_new.py": (range(1, 50),)}
DONE = Handoff("done")


def story(step: str = "tests") -> gates.StoryState:
    return gates.StoryState("s1", "Add todo", step, sprint=1)


def new_file(*extra: str) -> str:
    """A report: a new failing test, a new passing test and an old passing one, plus ``extra``."""
    return report(
        case("tests/test_new.py", "tests.test_new", "test_fresh", 0, FAIL),
        case("tests/test_new.py", "tests.test_new", "test_fine", 5),
        case("tests/test_old.py", "tests.test_old", "test_stable", 0),
        *extra,
    )


def checks(
    run: Callable[[str], tuple[int, str]],
    entries: dict[str, tuple[str, ...]] | None = None,
    changed: dict | None = None,
    serving: Serving | None = None,
) -> gates.Checks:
    serving = serving or Serving("s1", "base")
    reg = Registry(entries or {})
    reporting = test_reports.Reporting(OPTIONS, FOLDER, lambda: reg, lambda base: changed or {})
    commands = {"test": TEST_CMD, "coverage": COV_CMD}
    return gates.Checks(commands, 95.0, run, reporting=reporting, serving=serving)


def red(code: int, xml: str | None, **kw: Any) -> gates.Outcome:
    return checks(Writer([xml], code=code), changed=CHANGED, **kw).tests_red()


def covered(
    xml: str | None, code: int = 0, entries: dict | None = None, out: str = "TOTAL 97%"
) -> gates.Outcome:
    run = Writer([xml], code=code, out=out)
    return checks(run, entries or {"s1": (OLD_PASS,)}).tests_green_and_covered()


# ---- tests gate ----------------------------------------------------------------------------


def test_the_tests_gate_makes_new_failing_ids_pending(fake: FakeSystem) -> None:
    got = red(1, new_file())
    assert got.verdict is Verdict.PASS
    assert got.pending == PendingSet("s1", (NEW_FAIL,))
    assert gates.PENDING_SET.format(count=1, story="s1") in got.reason


def test_an_old_failing_test_is_not_pending_and_fails_the_gate(fake: FakeSystem) -> None:
    old = case("tests/test_old.py", "tests.test_old", "test_broken", 5, FAIL)
    got = red(1, new_file(old))
    assert got.verdict is Verdict.BOUNCE and got.bounce_to == "tests"
    assert gates.NOT_PENDING.split("{")[0] in got.reason
    assert OLD_FAIL in got.reason and NEW_FAIL not in got.reason
    assert got.pending is None


def test_a_failure_in_the_storys_own_registry_entry_stays_pending(fake: FakeSystem) -> None:
    old = case("tests/test_old.py", "tests.test_old", "test_broken", 5, FAIL)
    run = Writer([new_file(old)], code=1)
    got = checks(run, {"s1": (OLD_FAIL,)}, CHANGED).tests_red()
    assert got.verdict is Verdict.PASS
    assert sorted(got.pending.ids) == sorted([NEW_FAIL, OLD_FAIL])


def test_no_report_bounces_as_report_missing(fake: FakeSystem) -> None:
    got = red(1, None)
    assert got.verdict is Verdict.BOUNCE
    assert got.reason.startswith("the test command wrote no report in")
    assert got.pending is None


def test_a_failing_exit_with_no_failed_case_bounces(fake: FakeSystem) -> None:
    got = red(1, report(case("tests/test_old.py", "tests.test_old", "test_stable", 0)))
    assert got.verdict is Verdict.BOUNCE
    assert got.reason.startswith("the test command failed (exit 1) but its report names")


def test_a_green_run_is_too_early(fake: FakeSystem) -> None:
    got = red(0, report(case("tests/test_old.py", "tests.test_old", "test_stable", 0)))
    assert got.verdict is Verdict.BOUNCE and gates.GREEN_TOO_EARLY in got.reason


def test_a_run_over_two_roots_reads_the_report_that_exists(fake: FakeSystem) -> None:
    both = {"test": f"pytest {{report:{ROOT}}} && pytest {{report:other}}", "coverage": "c"}
    reporting = test_reports.Reporting(OPTIONS, FOLDER, Registry, lambda base: CHANGED)
    made = gates.Checks(both, 95.0, Writer([new_file(), None], code=1), reporting=reporting)
    made.serving = Serving("s1", "base")
    assert made.tests_red().pending == PendingSet("s1", (NEW_FAIL,))


def test_a_rework_with_a_green_suite_and_a_claim_clears_the_entry(fake: FakeSystem) -> None:
    green = report(case("tests/test_old.py", "tests.test_old", "test_stable", 0))
    got = checks(Writer([green]), {"s1": (OLD_PASS,)}).tests_reworked(TestClaim.CONFIRMED)
    assert got.verdict is Verdict.PASS
    assert got.pending == PendingSet("s1", ())


def test_a_rework_that_is_still_red_makes_the_failures_pending(fake: FakeSystem) -> None:
    got = checks(Writer([new_file()], code=1), {}, CHANGED).tests_reworked(None)
    assert got.pending == PendingSet("s1", (NEW_FAIL,))


# ---- skipping others' pending ids ----------------------------------------------------------

OTHERS = {"s1": (f"{ROOT}/tests/a.py::a",), "s2": (f"{ROOT}/tests/b.py::b", f"{ROOT}/tests/c.py")}


def test_the_implement_gate_skips_only_other_storys_ids(fake: FakeSystem) -> None:
    run = Writer([report()], out="TOTAL 97%")
    checks(run, OTHERS).tests_green_and_covered()
    command = shlex.split(run.calls[0])
    assert "--deselect=tests/b.py::b" in command and "--ignore=tests/c.py" in command
    assert not [w for w in command if w.endswith("a.py::a")]


def test_a_run_for_no_story_skips_every_pending_id(fake: FakeSystem) -> None:
    run = Writer([report()], out="TOTAL 97%")
    checks(run, OTHERS, serving=Serving()).tests_green_and_covered()
    command = shlex.split(run.calls[0])
    assert "--deselect=tests/a.py::a" in command and "--deselect=tests/b.py::b" in command


def test_skipped_ids_are_counted_in_the_reason(fake: FakeSystem) -> None:
    entries = {"s2": (f"{ROOT}/tests/b.py::b", f"{ROOT}/tests/c.py")}
    got = checks(Writer([report()], out="TOTAL 97%"), entries).tests_green_and_covered()
    assert got.verdict is Verdict.PASS
    assert "; skipped pending (s2): 2" in got.reason


def test_a_story_with_no_entry_runs_all_its_tests_and_fails_as_usual(fake: FakeSystem) -> None:
    failing = report(case("tests/test_new.py", "tests.test_new", "test_fresh", 0, FAIL))
    run = Writer([failing], code=1, out="1 failed")
    got = checks(run, {}).tests_green_and_covered()
    assert got.verdict is Verdict.BOUNCE and gates.TESTS_FAIL.split("{")[0] in got.reason
    assert got.pending is None
    assert "--deselect" not in run.calls[0] and "--ignore" not in run.calls[0]


def test_named_runs_never_skip_or_report() -> None:
    row = cfg.Targeted(ROOT, "pytest {tests}")
    (batch,) = runner_tools.batches([NEW_FAIL], cfg.Toolchain(targeted=(row,)))
    assert "--deselect" not in batch.command and "--junitxml" not in batch.command
    assert batch.command == "pytest tests/test_new.py::test_fresh"


# ---- the implement gate leaving pending ----------------------------------------------------


def test_the_implement_gate_passes_and_clears_when_every_own_id_passed(fake: FakeSystem) -> None:
    got = covered(report(case("tests/test_old.py", "tests.test_old", "test_stable", 0)))
    assert got.verdict is Verdict.PASS
    assert got.pending == PendingSet("s1", ())
    assert gates.PENDING_LEFT.format(count=1, story="s1") in got.reason


def test_a_failing_own_id_bounces_and_leaves_the_registry(fake: FakeSystem) -> None:
    bad = report(case("tests/test_old.py", "tests.test_old", "test_stable", 0, FAIL))
    got = covered(bad, code=0)
    assert got.verdict is Verdict.BOUNCE and got.pending is None
    assert gates.PENDING_FAIL.format(story="s1", ids=OLD_PASS) in got.reason


def test_a_failing_run_reports_both_reasons(fake: FakeSystem) -> None:
    bad = report(case("tests/test_old.py", "tests.test_old", "test_stable", 0, FAIL))
    got = covered(bad, code=1, out="1 failed")
    assert got.verdict is Verdict.BOUNCE and got.pending is None
    assert gates.TESTS_FAIL.split("{")[0] in got.reason
    assert gates.PENDING_FAIL.format(story="s1", ids=OLD_PASS) in got.reason


def test_a_skipped_own_id_bounces(fake: FakeSystem) -> None:
    skipped = report(case("tests/test_old.py", "tests.test_old", "test_stable", 0, "<skipped/>"))
    got = covered(skipped)
    assert got.verdict is Verdict.BOUNCE and "PENDING" not in got.reason
    assert gates.PENDING_FAIL.format(story="s1", ids=OLD_PASS) in got.reason


def test_an_own_id_gone_from_the_suite_is_dropped_with_a_note(fake: FakeSystem) -> None:
    ghost = f"{ROOT}/tests/test_old.py::test_renamed"
    entries = {"s1": (OLD_PASS, ghost)}
    got = covered(
        report(case("tests/test_old.py", "tests.test_old", "test_stable", 0)), entries=entries
    )
    assert got.verdict is Verdict.PASS and got.pending == PendingSet("s1", ())
    assert gates.PENDING_GONE.format(ids=ghost) in got.reason


def test_a_missing_report_on_a_pass_bounces_when_ids_are_pending(fake: FakeSystem) -> None:
    got = covered(None)
    assert got.verdict is Verdict.BOUNCE
    assert got.reason.startswith("the test command wrote no report in")


# ---- test findings, rejected registry, serving ----------------------------------------------


def test_failures_route_from_the_report_not_the_text(fake: FakeSystem) -> None:
    xml = report(case("tests/test_old.py", "tests.test_old", "test_broken", 0, FAIL))
    outcome = checks(Writer([xml], code=1, out="garbage"), {}, CHANGED).tests_red()
    found = gates.test_findings(outcome)
    assert [(f.path, f.lines) for f in found] == [
        (f"{ROOT}/tests/test_old.py", (f"FAILED {OLD_FAIL} - boom",))
    ]


def test_a_bad_registry_holds_the_gate_and_runs_nothing(fake: FakeSystem) -> None:
    def broken() -> Registry:
        raise pending_tests.RegistryError("x")

    run = FakeRunner()
    reporting = test_reports.Reporting(OPTIONS, FOLDER, broken)
    made = gates.Checks({"test": TEST_CMD, "coverage": COV_CMD}, 95.0, run, reporting=reporting)
    pipe = gates.Pipeline(["design", "tests", "implement"], 3, made)
    got = pipe.serving(Serving("s1", "base")).evaluate(story(), DONE)
    assert got.verdict is Verdict.HOLD
    assert gates.REGISTRY_BAD.split("{")[0] in got.reason
    assert run.calls == []


def test_pipeline_serving_returns_a_copy(fake: FakeSystem) -> None:
    pipe = gates.Pipeline(["tests"], 3, checks(FakeRunner()))
    served = pipe.serving(Serving("s9", "b"))
    assert served.checks.serving == Serving("s9", "b")
    assert pipe.checks.serving == Serving("s1", "base")


def test_reporting_is_off_by_default_and_commands_run_raw() -> None:
    run = FakeRunner({"T": (1, "boom")})
    got = gates.Checks({"test": "T", "coverage": "C"}, 95.0, run).tests_red()
    assert got.verdict is Verdict.PASS and got.pending is None
    assert run.calls == ["T"]


# ---- the full check at the boundary --------------------------------------------------------


def full_config(repo: Path) -> cfg.Config:
    raw = {**PY_CONFIG}
    raw["toolchain"] = {**raw["toolchain"], "test": TEST_CMD, "coverage": COV_CMD}
    system.write_text(repo / cfg.CONFIG_NAME, tomli_w.dumps(raw))
    return cfg.load(repo)


def test_a_boundary_run_skips_pending_files_but_fails_on_another_red_test(
    configured: Path, fake: FakeSystem
) -> None:
    file_id = f"{ROOT}/tests/test_p.py"
    config = full_config(configured)
    checks_ = fullcheck.full_checks(config, Registry({"s1": (file_id,)}))
    (cov_check,) = [c for c in checks_ if c.name == "coverage"]
    assert "--ignore=tests/test_p.py" in shlex.split(cov_check.built.command)
    run = Writer([report(case("tests/test_o.py", "tests.test_o", "test_x", 0, FAIL))], code=1)
    result = fullcheck.run_checks([cov_check], fullcheck.Judging(run, 95.0)).results[0]
    assert not result.passed
    assert result.pending == "pending (s1): 1"
    assert result.check.command == COV_CMD


# ---- the guard: only the runner writes the registry ----------------------------------------


def test_a_hand_edit_of_the_registry_is_refused(repo: Path) -> None:
    scope = guard.Scope("developer", repo, ["**"])
    call = guard.ToolCall("Write", {"file_path": pending_tests.REGISTRY})
    assert guard.check_tool_use(scope, call) == guard.RUNNER_ONLY.format(
        role="developer", rel=pending_tests.REGISTRY
    )


def test_a_bash_edit_of_the_registry_is_out_of_scope(repo: Path, fake: FakeSystem) -> None:
    from agile_team.git_ops import Git

    fake.reply(("git", "status"), Done(0, " M .team/pending-tests.json\0"))
    audit = guard.audit_step(Git(repo), guard.Scope("developer", repo, ["**"]))
    assert audit.out_of_scope == [pending_tests.REGISTRY]


def test_the_registry_is_listed_as_runner_only() -> None:
    assert guard.RUNNER_FILES == (pending_tests.REGISTRY, guard.STORY_FILES)


# ---- onboarding, CLI, tally ----------------------------------------------------------------


def test_the_registry_is_not_gitignored() -> None:
    assert "!.team/pending-tests.json" in onboard.gitignore_lines("ignored")


def test_pending_tests_prints_skip_options_under_a_root(
    configured: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ids = {"s1": (f"{ROOT}/tests/x.py::t", f"{ROOT}/tests/y.py"), "s2": ("unattended/runner/t.py",)}
    pending_tests.write(configured, Registry(ids))
    assert cli.main(["--repo", str(configured), "pending-tests", "--root", ROOT]) == 0
    assert capsys.readouterr().out == "--deselect=tests/x.py::t --ignore=tests/y.py\n"


def test_pending_tests_with_an_empty_registry_prints_an_empty_line(
    configured: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--repo", str(configured), "pending-tests"]) == 0
    assert capsys.readouterr().out == "\n"


def test_the_tally_keeps_the_pending_count_across_sessions() -> None:
    heard = test_tally.read(test_tally.EMPTY, test_tally.pending_record(3))
    assert heard.pending == 3
    record = '{"session": "new", "passed": 1, "warned": 0, "skipped": 0, "failed": 0, "total": 5}'
    again = test_tally.read(heard, record)
    assert again.pending == 3 and again.session == "new"
    assert again.as_dict()["pending"] == 3
    assert test_tally.EMPTY.as_dict()["pending"] == 0


# ---- the docs and role files (AC8) and the page (AC6, static) ------------------------------


def docs(*parts: str) -> str:
    return system.read_text(SKILL_DIR.joinpath(*parts))


def test_role_files_explain_pending_tests() -> None:
    tester = docs("runner", "agile_team", "roles", "unit-tester.md")
    assert "## Pending tests" in tester and "never mark a test `skip` or `xfail`" in tester
    assert "pending tests" in docs("runner", "agile_team", "roles", "developer.md")
    assert "Never weaken, skip or delete a test" in docs(
        "runner", "agile_team", "roles", "_shared.md"
    )
    assert "### Pending tests (s125)" in docs("reference", "protocol.md")


def test_the_page_captions_the_pending_count() -> None:
    page = docs("runner", "agile_team", "dashboard", "index.html")
    assert "Pending" in page and "--pending" in page and "fc-sw.pending" in page
    fixture = docs("runner", "agile_team", "dashboard", "fixtures", "snapshot.json")
    assert '"pending": 3' in fixture
