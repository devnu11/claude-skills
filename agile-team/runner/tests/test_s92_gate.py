"""s92 checklist 12-15 and 17: the gate routes items to the roles that own the files."""

import pytest
from agile_team import gates
from agile_team.gates import ALSO_ROUTED, ROUTED, Outcome, StoryStatus, Verdict
from agile_team.owners import Fix, Item, Source, Split

from .conftest import FakeRunner
from .test_gates import story
from .test_s92_owners import owners_at

E2E_FAIL = "FAILED tests/e2e/test_git.py::test_keep - AssertionError\n1 failed in 0.4s"
LINT_UNIT = "tests/test_limits.py:8:1: I001 unsorted imports"
LISTING = "src/a.py\ntests/test_limits.py\ntests/test_x.py\ntests/e2e/test_git.py\n"
E2E_FIX = Fix(
    "integration-tester", [Item("tests/e2e/test_git.py", Source.TEST, ["tests/e2e/test_git.py"])]
)
UNIT_FIX = Fix("unit-tester", [Item("tests/test_limits.py", Source.LINT, ["tests/test_limits.py"])])


def pipeline(results=None, commands=None) -> gates.Pipeline:
    commands = commands or {"test": "T", "coverage": "C", "lint": "L"}
    runner = FakeRunner({gates.LS_ALL_COMMAND: (0, LISTING), **(results or {})})
    return gates.Pipeline(["design", "tests", "implement"], 3, gates.Checks(commands, 95.0, runner))


def passed(output: str = "TOTAL 100%") -> Outcome:
    return Outcome(Verdict.PASS, output=output)


def bounced(reason: str = "tests fail") -> Outcome:
    return Outcome(Verdict.BOUNCE, reason, "implement")


def own_test() -> Item:
    return Item("tests/test_x.py", Source.TEST, ["tests/test_x.py"])


# ---- 12: _routed truth table (R9, R10) -------------------------------------


def test_pass_with_a_fix_becomes_a_route() -> None:
    out = gates._routed(passed(), Split([], [UNIT_FIX]))
    owners = "unit-tester (tests/test_limits.py)"
    assert (out.verdict, out.reason) == (Verdict.ROUTE, ROUTED.format(owners=owners))
    assert out.fixes == [UNIT_FIX]


def test_bounce_with_only_foreign_test_items_becomes_a_route() -> None:
    split = Split([], [E2E_FIX])
    out = gates._routed(bounced(), split)
    assert out.verdict is Verdict.ROUTE and out.fixes == [E2E_FIX]
    assert out.reason == ROUTED.format(owners="integration-tester (tests/e2e/test_git.py)")


def test_bounce_with_an_own_test_item_stays_a_bounce_and_notes_the_route() -> None:
    out = gates._routed(bounced("tests fail"), Split([own_test()], [E2E_FIX]))
    owners = "integration-tester (tests/e2e/test_git.py)"
    assert out.verdict is Verdict.BOUNCE and out.bounce_to == "implement"
    assert out.reason == f"tests fail\n{ALSO_ROUTED.format(owners=owners)}"
    assert out.fixes == [E2E_FIX]


def test_a_coverage_shortfall_with_a_lint_fix_stays_a_bounce() -> None:
    out = gates._routed(bounced("coverage 90% is below 95%"), Split([], [UNIT_FIX]))
    assert out.verdict is Verdict.BOUNCE and out.fixes == [UNIT_FIX]
    assert out.reason.startswith("coverage 90% is below 95%\n")


def test_no_fixes_returns_the_base_unchanged() -> None:
    base = bounced()
    assert gates._routed(base, Split([own_test()], [])) is base


# ---- 13: route leaves other outcomes alone ----------------------------------


def test_an_outcome_without_output_passes_through() -> None:
    base = Outcome(Verdict.PASS)
    assert pipeline().route(base, owners_at()) is base


def test_a_timed_out_run_has_no_output_so_it_is_not_routed() -> None:
    p = pipeline({"C": (124, "tests/e2e/test_git.py")})
    out = p.checks.tests_green_and_covered()
    assert out.output == ""
    assert p.route(out, owners_at()) is out


def test_a_finished_run_keeps_its_output_in_memory() -> None:
    p = pipeline({"C": (1, E2E_FAIL)})
    assert p.checks.tests_green_and_covered().output == E2E_FAIL


def test_a_failed_coverage_run_with_an_e2e_failure_routes() -> None:
    p = pipeline({"C": (1, E2E_FAIL)})
    out = p.route(p.checks.tests_green_and_covered(), owners_at())
    assert out.verdict is Verdict.ROUTE
    assert [f.role for f in out.fixes] == ["integration-tester"]
    assert out.fixes[0].items[0].lines[0] == E2E_FAIL.splitlines()[0]


def test_lint_in_an_untouched_file_is_not_routed() -> None:
    p = pipeline({"L": (1, LINT_UNIT)})
    out = p.route(passed(), owners_at())
    assert out.verdict is Verdict.PASS and out.fixes == []


def test_lint_in_a_touched_file_is_routed_to_its_owner() -> None:
    p = pipeline({"L": (1, LINT_UNIT)})
    out = p.route(passed(), owners_at(touched=frozenset({"tests/test_limits.py"})))
    assert out.verdict is Verdict.ROUTE and [f.role for f in out.fixes] == ["unit-tester"]


# ---- 14: _route_dispute (R11) ------------------------------------------------


def disputed(file: str) -> Outcome:
    d = gates.OpenDispute(
        f"{file}::test_k", "s65 G9", "lay_out never wipes", file, "base", output="l1\nl2"
    )
    return Outcome(Verdict.DISPUTE, "contradicts", dispute=d)


def test_a_dispute_on_an_e2e_test_routes_to_the_integration_tester() -> None:
    out = pipeline().route(disputed("tests/e2e/test_git.py"), owners_at())
    [fix] = out.fixes
    assert out.verdict is Verdict.ROUTE and out.author is gates.Author.ROLE
    assert (fix.role, fix.rule, fix.why) == ("integration-tester", "s65 G9", "lay_out never wipes")
    assert fix.items[0].lines == ["l1", "l2"] and fix.items[0].files == ["tests/e2e/test_git.py"]


def test_a_routed_dispute_opens_no_dispute() -> None:
    s, p = story("implement"), pipeline()
    p.advance(s, p.route(disputed("tests/e2e/test_git.py"), owners_at()))
    assert (s.disputes, s.dispute, s.rounds, s.step) == (0, None, 0, "implement")
    assert [f.role for f in s.fixes] == ["integration-tester"]


def test_a_dispute_on_a_unit_test_keeps_the_dispute() -> None:
    base = disputed("tests/test_x.py")
    assert pipeline().route(base, owners_at()) is base


# ---- 15: advance sets and clears the queue (R12) -----------------------------


def test_a_route_leaves_rounds_and_step_alone() -> None:
    s, p = story("implement"), pipeline()
    p.advance(s, Outcome(Verdict.ROUTE, "r", fixes=[E2E_FIX]))
    assert (s.rounds, s.step, s.status, s.fixes) == (0, "implement", StoryStatus.ACTIVE, [E2E_FIX])


def test_every_gate_result_replaces_the_queue() -> None:
    s, p = story("implement", fixes=[E2E_FIX]), pipeline()
    p.advance(s, Outcome(Verdict.PASS))
    assert s.fixes == []


def test_a_bounce_with_fixes_queues_them_and_counts_a_round() -> None:
    s, p = story("implement"), pipeline()
    p.advance(s, Outcome(Verdict.BOUNCE, "x", "implement", fixes=[UNIT_FIX]))
    assert (s.rounds, s.fixes) == (1, [UNIT_FIX])


def test_clear_empties_the_queue() -> None:
    s, p = story("implement", fixes=[E2E_FIX]), pipeline()
    p._clear(s)
    assert s.fixes == []


# ---- 17: Checks.lint_outputs and Checks.listing ------------------------------


def test_lint_outputs_keeps_failed_lint_and_static_runs() -> None:
    cmds = {"test": "T", "coverage": "C", "lint": "L", "static": "S"}
    p = pipeline({"L": (1, "a"), "S": (2, "b")}, cmds)
    assert p.checks.lint_outputs() == ["a", "b"]


@pytest.mark.parametrize("code", [0, 124])
def test_lint_outputs_skips_clean_and_timed_out_runs(code: int) -> None:
    assert pipeline({"L": (code, "x")}).checks.lint_outputs() == []


def test_lint_outputs_skips_unconfigured_commands() -> None:
    p = pipeline({}, {"test": "T", "coverage": "C"})
    assert p.checks.lint_outputs() == [] and "L" not in p.checks.run.calls


def test_listing_is_the_git_output_or_empty_on_failure() -> None:
    assert pipeline().checks.listing() == LISTING
    assert pipeline({gates.LS_ALL_COMMAND: (128, "fatal")}).checks.listing() == ""
