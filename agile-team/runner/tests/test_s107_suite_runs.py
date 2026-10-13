"""s107 SR1-SR7: the runner runs the test command N times in a row after the suite step."""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from agile_team import cli, gates, results, stages, suite_runs, system
from agile_team import config as cfg
from agile_team.commands import TIMED_OUT
from agile_team.dispatch import Runtime
from agile_team.gates import Outcome, Verdict
from agile_team.roles import Handoff

from .conftest import FakeRunner
from .test_gates import story

PASS_LINE = "412 passed in 3.2s"
FAIL_LINE = "1 failed, 3 passed in 1.0s"
STEPS = ["design", "tests", "implement", "e2e", "acceptance"]


class Scripted:
    """A test-command runner returning scripted (code, output) in turn."""

    def __init__(self, *results: tuple[int, str]) -> None:
        self.results = list(results)
        self.calls: list[str] = []

    def __call__(self, command: str) -> tuple[int, str]:
        self.calls.append(command)
        return self.results.pop(0) if self.results else (0, PASS_LINE)


@pytest.fixture(autouse=True)
def ticking(monkeypatch: pytest.MonkeyPatch) -> None:
    """The awake clock moves 10 s per reading."""
    now = iter(range(0, 10_000, 10))
    monkeypatch.setattr(system, "monotonic", lambda: float(next(now)))


def build(runner, count=5, steps=STEPS, opened=None) -> gates.Pipeline:
    """A pipeline whose story asks for ``count`` suite runs (count may be a Wanted)."""
    wanted = count if isinstance(count, suite_runs.Wanted) else suite_runs.Wanted(count)
    checks = gates.Checks(
        {"test": "T", "coverage": "C"}, 95.0, runner, suite_runs=lambda _s: wanted
    )
    if opened is not None:
        checks.stages = opened
    return gates.Pipeline(list(steps), 3, checks)


def done() -> Handoff:
    return Handoff(status="done", summary="ok")


# ---- SR1/SR6 wanted ---------------------------------------------------------


def test_no_key_means_no_runs() -> None:
    assert suite_runs.wanted(None, "s1") == suite_runs.Wanted()
    assert suite_runs.wanted({"depends_on": []}, "s1") == suite_runs.Wanted()


@pytest.mark.parametrize("n", [1, 5, 10])
def test_a_whole_number_in_range_is_wanted(n) -> None:
    assert suite_runs.wanted({"suite_runs": n}, "s1") == suite_runs.Wanted(n)


@pytest.mark.parametrize("bad", [0, 11, "5", True, 2.5, -1, None])
def test_a_bad_value_gives_the_exact_refusal(bad) -> None:
    got = suite_runs.wanted({"suite_runs": bad}, "s107")
    text = suite_runs.BAD_SUITE_RUNS.format(story="s107", most=10, value=bad)
    assert got.refusal == text and got.count == 0
    assert text.startswith("story s107's suite_runs must be a whole number from 1 to 10, not ")


def test_constants_are_pinned() -> None:
    assert (suite_runs.KEY, suite_runs.MOST_SUITE_RUNS) == ("suite_runs", 10)
    assert suite_runs.SUITE_RUNS == "suite-runs"
    assert suite_runs.SUITE_STEPS == ("e2e", "implement")


# ---- declared ---------------------------------------------------------------


def read_returning(monkeypatch, text: str | None) -> list[Path]:
    seen: list[Path] = []

    def read(path: Path) -> str:
        seen.append(path)
        if text is None:
            raise FileNotFoundError(path)
        return text

    monkeypatch.setattr(system, "read_text", read)
    return seen


def test_declared_missing_file_is_no_key(monkeypatch) -> None:
    seen = read_returning(monkeypatch, None)
    assert suite_runs.declared(Path("/st"), "s1") == suite_runs.Wanted()
    assert seen == [Path("/st/s1.md")]


def test_declared_reads_the_count_next_to_other_keys(monkeypatch) -> None:
    read_returning(monkeypatch, "---\ndepends_on: [s2]\nsuite_runs: 3\n---\nbody\n")
    assert suite_runs.declared(Path("/st"), "s1") == suite_runs.Wanted(3)


def test_declared_without_frontmatter_is_no_key(monkeypatch) -> None:
    read_returning(monkeypatch, "just a story\n")
    assert suite_runs.declared(Path("/st"), "s1") == suite_runs.Wanted()


def test_declared_frontmatter_that_is_not_a_mapping_is_refused(monkeypatch) -> None:
    read_returning(monkeypatch, "---\n- a\n- b\n---\nbody\n")
    got = suite_runs.declared(Path("/st"), "s1")
    assert got.count == 0 and got.refusal.startswith("story s1's frontmatter does not parse: ")


def test_declared_broken_yaml_is_refused(monkeypatch) -> None:
    read_returning(monkeypatch, "---\nkey: [unclosed\n---\nbody\n")
    got = suite_runs.declared(Path("/st"), "s1")
    assert got.refusal.startswith("story s1's frontmatter does not parse: ")


# ---- SR2 suite_step ---------------------------------------------------------


@pytest.mark.parametrize(
    ("steps", "want"),
    [
        (["design", "tests", "implement", "e2e", "acceptance"], "e2e"),
        (["design", "tests", "implement"], "implement"),
        (["design", "tests"], None),
        ([], None),
    ],
)
def test_suite_step(steps, want) -> None:
    assert suite_runs.suite_step(steps) == want


# ---- summary / report -------------------------------------------------------


def test_summary_joins_pytest_summary_lines() -> None:
    out = "noise\n===== 12 passed in 1s =====\nmore\n= 3 failed, 4 passed in 2s =\n"
    assert suite_runs.summary(out) == "12 passed in 1s | 3 failed, 4 passed in 2s"


def test_summary_without_a_match_is_the_last_non_blank_line() -> None:
    assert suite_runs.summary("first\nlast line\n\n") == "last line"


def test_summary_of_nothing() -> None:
    assert suite_runs.summary("") == "no output"
    assert suite_runs.summary("\n  \n") == "no output"


def test_run_line_text() -> None:
    run = suite_runs.SuiteRun(2, 5, 0, 398.4, PASS_LINE)
    assert run.line() == "run 2 of 5: exit 0 in 398 s: 412 passed in 3.2s"


def test_report_has_one_line_per_run_and_the_failed_tail() -> None:
    ok = suite_runs.SuiteRun(1, 3, 0, 5.0, PASS_LINE)
    bad = suite_runs.SuiteRun(2, 3, 1, 6.0, f"boom\n{FAIL_LINE}")
    text = suite_runs.report([ok, bad])
    assert text.splitlines()[:2] == [ok.line(), bad.line()]
    assert text == f"{ok.line()}\n{bad.line()}\n\n{results.result_tail(bad.out)}"


def test_report_of_passing_runs_has_no_tail() -> None:
    runs = [suite_runs.SuiteRun(i, 2, 0, 5.0, PASS_LINE) for i in (1, 2)]
    assert suite_runs.report(runs) == "\n".join(r.line() for r in runs)


def test_passed_text_lists_the_times() -> None:
    runs = [suite_runs.SuiteRun(1, 2, 0, 412.2, ""), suite_runs.SuiteRun(2, 2, 0, 398.0, "")]
    want = "the test command passed 2 runs in a row (412 s, 398 s)"
    assert suite_runs.passed_text(runs) == want


# ---- SR3 stop at first failure ----------------------------------------------


def test_a_failure_on_run_three_stops_and_bounces() -> None:
    runner = Scripted((0, PASS_LINE), (0, PASS_LINE), (1, FAIL_LINE))
    pipe = build(runner)
    out = pipe.checks.after_suite_runs("s1", Outcome(Verdict.PASS, "presentation ready"))
    assert runner.calls == ["T", "T", "T"]
    assert out.verdict is Verdict.BOUNCE and out.bounce_to is None
    assert out.reason.startswith("the test command failed on run 3 of 5:")
    assert out.output == FAIL_LINE
    (ran,) = out.extra_ran
    assert (ran.name, ran.code) == ("suite-runs", 1)
    assert ran.tail.count("exit ") == 3 and ran.tail.endswith(FAIL_LINE)
    assert "\n\n" in ran.tail


def test_a_timeout_on_run_two_gives_the_timed_out_outcome() -> None:
    runner = Scripted((0, PASS_LINE), (TIMED_OUT, "slow"))
    first = Outcome(Verdict.PASS, ran=results.Ran("coverage", 0, "x"))
    out = build(runner).checks.after_suite_runs("s1", first)
    assert runner.calls == ["T", "T"]
    assert out.verdict is Verdict.BOUNCE
    assert out.reason == gates.timed_out(TIMED_OUT, "slow").reason
    assert out.ran == first.ran
    assert [r.name for r in out.extra_ran] == ["suite-runs"]
    assert out.extra_ran[0].code == TIMED_OUT


# ---- SR4 pass text ----------------------------------------------------------


def test_all_runs_passing_keeps_the_verdict_and_adds_the_text() -> None:
    runner = Scripted()
    ran = results.Ran("coverage", 0, "t")
    first = Outcome(Verdict.PASS, "presentation ready", ran=ran)
    out = build(runner).checks.after_suite_runs("s1", first)
    assert runner.calls == ["T"] * 5
    assert out.verdict is Verdict.PASS and out.ran == ran
    assert out.reason.startswith("presentation ready; the test command passed 5 runs in a row (")
    assert out.reason.endswith("10 s, 10 s, 10 s, 10 s, 10 s)")
    assert [r.name for r in out.extra_ran] == ["suite-runs"]
    assert out.extra_ran[0].code == 0 and out.extra_ran[0].tail.count("exit 0") == 5


def test_an_empty_reason_is_just_the_text() -> None:
    out = build(Scripted()).checks.after_suite_runs(
        "s1",
        Outcome(Verdict.PASS),
    )
    assert out.reason.startswith("the test command passed 5 runs in a row (")


@pytest.mark.parametrize("verdict", [Verdict.BOUNCE, Verdict.HOLD])
def test_a_first_outcome_that_is_not_a_pass_is_returned_untouched(verdict) -> None:
    runner = Scripted()
    first = Outcome(verdict, "no")
    assert build(runner).checks.after_suite_runs("s1", first) is first
    assert runner.calls == []


def test_a_count_of_zero_returns_first() -> None:
    runner = Scripted()
    first = Outcome(Verdict.PASS, "x")
    assert build(runner, 0).checks.after_suite_runs("s1", first) is first
    assert runner.calls == []


def test_checks_default_asks_for_no_runs() -> None:
    runner = Scripted()
    first = Outcome(Verdict.PASS)
    assert gates.Checks({"test": "T"}, 95.0, runner).after_suite_runs("s1", first) is first


# ---- SR6 at the gate --------------------------------------------------------


def test_a_bad_value_holds_without_running_the_command() -> None:
    runner = Scripted()
    ran = results.Ran("coverage", 0, "t")
    wanted = suite_runs.Wanted(0, "bad value")
    out = build(runner, wanted).checks.after_suite_runs("s1", Outcome(Verdict.PASS, ran=ran))
    assert (out.verdict, out.reason, out.ran) == (Verdict.HOLD, "bad value", ran)
    assert runner.calls == []


# ---- SR2 gating through the pipeline ----------------------------------------


def test_e2e_done_runs_the_suite_even_without_a_gate_of_its_own() -> None:
    runner = Scripted()
    pipe = build(runner, steps=["design", "tests", "implement", "e2e"])
    out = pipe.evaluate(story("e2e"), done())
    assert out.verdict is Verdict.PASS and runner.calls == ["T"] * 5


def test_e2e_done_runs_after_the_presentation_gate() -> None:
    runner = Scripted()
    out = build(runner).evaluate(story("e2e"), done())
    assert out.reason.startswith("presentation ready; the test command passed 5 runs")


def test_changes_requested_runs_nothing() -> None:
    runner = Scripted()
    handoff = Handoff(status="changes_requested", summary="no", next_role="developer")
    out = build(runner).evaluate(story("e2e"), handoff)
    assert out.verdict is Verdict.BOUNCE and runner.calls == []


def test_implement_does_not_run_when_e2e_is_in_the_steps() -> None:
    runner = Scripted()
    build(runner).evaluate(story("implement"), done())
    assert runner.calls.count("T") == 1  # the implement gate's own run only


def test_implement_runs_the_suite_when_it_is_the_last_code_step() -> None:
    runner = Scripted()
    pipe = build(runner, steps=["design", "tests", "implement"])
    out = pipe.evaluate(story("implement"), done())
    assert out.verdict is Verdict.PASS and "passed 5 runs in a row" in out.reason
    assert runner.calls.count("T") == 1 + 5


def test_a_failed_step_gate_runs_no_suite() -> None:
    runner = Scripted((1, FAIL_LINE))
    pipe = build(runner, steps=["design", "tests", "implement"])
    out = pipe.evaluate(story("implement"), done())
    assert out.verdict is Verdict.BOUNCE
    assert runner.calls.count("T") == 1


def test_a_story_without_the_key_is_unchanged() -> None:
    runner = FakeRunner()
    pipe = gates.Pipeline(
        ["design", "tests", "implement"],
        3,
        gates.Checks({"test": "T", "coverage": "C"}, 95.0, runner),
    )
    out = pipe.evaluate(story("implement"), done())
    assert out.verdict is Verdict.PASS and "suite" not in out.reason
    assert out.extra_ran == ()


def test_the_bad_value_holds_through_the_pipeline() -> None:
    runner = Scripted()
    pipe = build(runner, suite_runs.Wanted(0, "bad"), steps=["design", "tests", "implement"])
    out = pipe.evaluate(story("implement"), done())
    assert out.verdict is Verdict.HOLD and out.reason == "bad"


# ---- SR7 stage --------------------------------------------------------------


def test_the_runs_happen_inside_one_gate_suite_runs_stage() -> None:
    opened: list[stages.Name] = []

    @contextmanager
    def opener(name):
        opened.append(name)
        yield None

    build(Scripted(), opened=opener).checks.after_suite_runs("s1", Outcome(Verdict.PASS))
    assert opened == [stages.Name.GATE_SUITE_RUNS]
    assert stages.Name.GATE_SUITE_RUNS.value == "gate.suite-runs"
    assert stages.reserved("gate.suite-runs")


def test_no_stage_when_nothing_runs() -> None:
    opened: list[stages.Name] = []

    @contextmanager
    def opener(name):
        opened.append(name)
        yield None

    build(Scripted(), 0, opened=opener).checks.after_suite_runs("s1", Outcome(Verdict.PASS))
    assert opened == []


# ---- SR5 briefs and keeping -------------------------------------------------


@pytest.mark.parametrize("step", ["implement", "e2e", "acceptance"])
def test_briefs_show_suite_runs(step) -> None:
    assert "suite-runs" in results.BRIEF_RESULTS[step]


def test_implement_still_shows_test_and_coverage_first() -> None:
    assert results.BRIEF_RESULTS["implement"] == ("test", "coverage", "suite-runs")
    assert results.BRIEF_RESULTS["e2e"] == ("suite-runs",)
    assert results.BRIEF_RESULTS["acceptance"] == ("suite-runs",)


def test_keep_runs_keeps_the_gate_run_and_the_extra_runs() -> None:
    kept: list[tuple] = []
    me = SimpleNamespace(_keep=lambda story, ran, where: kept.append((ran.name, where)))
    a, b = results.Ran("coverage", 0, "a"), results.Ran("suite-runs", 0, "b")
    Runtime._keep_runs(me, story("e2e"), Outcome(Verdict.PASS, ran=a, extra_ran=(b,)))
    assert kept == [("coverage", "e2e gate"), ("suite-runs", "e2e gate")]


def test_keep_runs_with_nothing_keeps_nothing() -> None:
    kept: list = []
    me = SimpleNamespace(_keep=lambda *a: kept.append(a))
    Runtime._keep_runs(me, story("e2e"), Outcome(Verdict.PASS))
    assert kept == []


def test_keep_runs_keeps_only_extra_when_there_is_no_ran() -> None:
    kept: list = []
    me = SimpleNamespace(_keep=lambda story, ran, where: kept.append(ran.name))
    extra = results.Ran("suite-runs", 1, "t")
    Runtime._keep_runs(me, story("e2e"), Outcome(Verdict.BOUNCE, extra_ran=(extra,)))
    assert kept == ["suite-runs"]


# ---- wiring -----------------------------------------------------------------


def test_make_pipeline_wires_declared_with_the_stories_dir(configured: Path, monkeypatch) -> None:
    config = cfg.load(configured)
    read_returning(monkeypatch, "---\nsuite_runs: 4\n---\n")
    wanted = cli.make_pipeline(config).checks.suite_runs("s7")
    assert wanted == suite_runs.Wanted(4)
