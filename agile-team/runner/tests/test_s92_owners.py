"""s92: owners.py, the pure table that maps a failing item to the role owning its file."""

import json
from dataclasses import asdict

import pytest

from agile_team import gates, owners, roles
from agile_team.owners import Fix, FixRecord, Item, Owners, Source, Writer

UNIT = Writer("tests", "unit-tester", ("tests/**", "!tests/e2e/**"))
E2E = Writer("e2e", "integration-tester", ("tests/e2e/**",))
DEV = Writer("implement", "developer", ("agile_team/**",))
TABLE = (UNIT, DEV, E2E)


def owners_at(step: str = "implement", touched: frozenset[str] = frozenset()) -> Owners:
    return Owners(TABLE, step, touched)


def item(path: str, source: Source = Source.TEST) -> Item:
    return Item(path, source, [path])


# 1. findings


def test_pytest_summary_failed_line_gives_test_file() -> None:
    out = "FAILED tests/e2e/test_git.py::test_keep - AssertionError\n"
    found = owners.findings(out, Source.TEST)
    assert [f.path for f in found] == ["tests/e2e/test_git.py"]
    assert found[0].source == Source.TEST


def test_pytest_error_line_gives_test_file() -> None:
    found = owners.findings("ERROR tests/test_a.py - ImportError\n", Source.TEST)
    assert [f.path for f in found] == ["tests/test_a.py"]


def test_jest_fail_line_gives_test_file() -> None:
    found = owners.findings("FAIL src/a.test.js\n", Source.TEST)
    assert [f.path for f in found] == ["src/a.test.js"]


def test_traceback_line_is_not_a_test_finding() -> None:
    assert owners.findings("tests/test_a.py:12: AssertionError\n", Source.TEST) == []


def test_ruff_concise_is_a_lint_finding() -> None:
    found = owners.findings("tests/test_a.py:8:1: I001 unsorted\n", Source.LINT)
    assert [f.path for f in found] == ["tests/test_a.py"]


def test_flake8_without_column_is_a_lint_finding() -> None:
    found = owners.findings("a/b.py:8: E501 too long\n", Source.LINT)
    assert [f.path for f in found] == ["a/b.py"]


def test_ruff_full_keeps_both_lines() -> None:
    out = "I001 unsorted imports\n  --> tests/test_a.py:1:1\n"
    found = owners.findings(out, Source.LINT)
    assert [f.path for f in found] == ["tests/test_a.py"]
    assert len(found[0].lines) == 2


def test_would_reformat_is_a_lint_finding() -> None:
    found = owners.findings("Would reformat: tests/test_a.py\n", Source.LINT)
    assert [f.path for f in found] == ["tests/test_a.py"]


def test_no_findings_in_clean_output() -> None:
    assert owners.findings("", Source.LINT) == []
    assert owners.findings("all good", Source.TEST) == []


# 2. candidates


def test_candidates_exact_path() -> None:
    assert owners.candidates("a/b.py", "a/b.py\nx/a/b.py\n") == ["a/b.py"]


def test_candidates_unique_suffix() -> None:
    assert owners.candidates("b.py", "a/b.py\nc.py\n") == ["a/b.py"]


def test_candidates_two_suffix_matches() -> None:
    assert owners.candidates("b.py", "a/b.py\nx/b.py\n") == ["a/b.py", "x/b.py"]


def test_candidates_none() -> None:
    assert owners.candidates("zz.py", "a/b.py\n") == []


def test_candidates_suffix_needs_a_slash_boundary() -> None:
    assert owners.candidates("b.py", "ab.py\n") == []


# 3. placed


def test_placed_groups_by_path_and_source_in_first_seen_order() -> None:
    found = [
        owners.Finding("b.py", ("b1",), Source.LINT),
        owners.Finding("a.py", ("a1",), Source.LINT),
        owners.Finding("b.py", ("b2",), Source.LINT),
        owners.Finding("b.py", ("t",), Source.TEST),
    ]
    items = owners.placed(found, "a.py\nb.py\n")
    assert [(i.path, i.source) for i in items] == [
        ("b.py", Source.LINT),
        ("a.py", Source.LINT),
        ("b.py", Source.TEST),
    ]
    assert items[0].lines == ["b1", "b2"]
    assert items[0].files == ["b.py"]


def test_placed_caps_lines() -> None:
    found = [owners.Finding("a.py", tuple(f"l{n}" for n in range(60)), Source.TEST)]
    assert len(owners.placed(found, "a.py")[0].lines) == owners.ITEM_LINES == 40


def test_placed_unlisted_path_has_no_files() -> None:
    assert owners.placed([owners.Finding("q.py", ("x",), Source.TEST)], "")[0].files == []


def test_item_shown_is_the_single_file_else_the_printed_path() -> None:
    assert Item("b.py", Source.TEST, ["a/b.py"]).shown == "a/b.py"
    assert Item("b.py", Source.TEST, ["a/b.py", "x/b.py"]).shown == "b.py"
    assert Item("b.py", Source.TEST, []).shown == "b.py"


# 4. writer_of / owner_of


def test_own_writer_wins_when_its_globs_match() -> None:
    both = Owners((UNIT, Writer("implement", "developer", ("**",))), "implement")
    assert both.writer_of("tests/test_a.py").step == "tests"  # first in order
    assert both.own.step == "implement"
    assert both.writer_of("agile_team/x.py").step == "implement"


def test_own_writer_preferred_over_earlier_one() -> None:
    wide = Writer("implement", "developer", ("**",))
    assert Owners((UNIT, wide), "implement").writer_of("tests/t.py") == wide


def test_first_matching_writer_in_order() -> None:
    assert owners_at().writer_of("tests/test_a.py") == UNIT
    assert owners_at().writer_of("tests/e2e/test_a.py") == E2E


def test_no_writer_for_unowned_file() -> None:
    assert owners_at().writer_of("README.md") is None


def test_bang_glob_excludes() -> None:
    assert owners_at().writer_of("tests/e2e/x.py") != UNIT


def test_owner_of_shared_writer() -> None:
    assert owners_at().owner_of(["tests/a.py", "tests/b.py"]) == UNIT


def test_owner_of_different_writers_is_none() -> None:
    assert owners_at().owner_of(["tests/a.py", "tests/e2e/b.py"]) is None


def test_owner_of_nothing_is_none() -> None:
    assert owners_at().owner_of([]) is None


def test_own_is_none_when_step_has_no_writer() -> None:
    assert Owners(TABLE, "ship").own is None


# 5. fixer


def test_test_item_in_unit_test_file_stays_with_developer() -> None:
    assert owners_at().fixer(item("tests/test_a.py")) is None


def test_lint_item_in_unit_test_file_goes_to_unit_tester() -> None:
    assert owners_at().fixer(item("tests/test_a.py", Source.LINT)) == UNIT


def test_test_item_in_e2e_file_goes_to_integration_tester() -> None:
    assert owners_at().fixer(item("tests/e2e/test_a.py")) == E2E


def test_item_in_own_file_is_own() -> None:
    assert owners_at().fixer(item("agile_team/a.py")) is None


def test_item_with_no_files_is_own() -> None:
    assert owners_at().fixer(Item("x.py", Source.TEST)) is None


def test_item_with_split_owners_is_own() -> None:
    assert owners_at().fixer(Item("t.py", Source.TEST, ["tests/t.py", "tests/e2e/t.py"])) is None


# 6. counts


def test_lint_outside_touched_is_dropped() -> None:
    assert not owners_at().counts(item("tests/a.py", Source.LINT))


def test_lint_in_touched_counts() -> None:
    assert owners_at(touched=frozenset({"tests/a.py"})).counts(item("tests/a.py", Source.LINT))


def test_test_item_always_counts() -> None:
    assert owners_at().counts(item("tests/a.py"))


# 7. split


def test_fixes_follow_writer_order_not_item_order() -> None:
    touched = frozenset({"tests/test_u.py"})
    items = [item("tests/e2e/test_i.py"), item("tests/test_u.py", Source.LINT)]
    split = owners.split(items, owners_at(touched=touched))
    assert [f.role for f in split.fixes] == ["unit-tester", "integration-tester"]
    assert split.own == []


def test_one_fix_per_role_holds_all_its_items() -> None:
    items = [item("tests/e2e/a.py"), item("tests/e2e/b.py")]
    split = owners.split(items, owners_at())
    assert len(split.fixes) == 1
    assert [i.path for i in split.fixes[0].items] == ["tests/e2e/a.py", "tests/e2e/b.py"]


def test_own_test_items_are_kept_and_tested() -> None:
    split = owners.split([item("tests/test_a.py")], owners_at())
    assert [i.path for i in split.own] == ["tests/test_a.py"]
    assert split.fixes == []
    assert split.tested


def test_own_lint_items_are_dropped() -> None:
    touched = frozenset({"agile_team/a.py"})
    split = owners.split([item("agile_team/a.py", Source.LINT)], owners_at(touched=touched))
    assert split.own == [] and split.fixes == []
    assert not split.tested


def test_untouched_lint_is_dropped() -> None:
    split = owners.split([item("tests/a.py", Source.LINT)], owners_at())
    assert split.fixes == [] and not split.tested


def test_tested_is_true_for_a_test_item_in_a_fix() -> None:
    split = owners.split([item("tests/e2e/a.py")], owners_at())
    assert split.tested


def test_not_tested_when_only_lint_fixes() -> None:
    split = owners.split([item("tests/a.py", Source.LINT)], owners_at(touched=frozenset({"tests/a.py"})))
    assert split.fixes and not split.tested


# 8. asserts_changed


def test_reindented_assert_is_not_a_change() -> None:
    diff = "-    assert x == 1\n+        assert   x == 1\n"
    assert not owners.asserts_changed(diff)


def test_changed_comparison_is_a_change() -> None:
    assert owners.asserts_changed("-    assert x == 1\n+    assert x == 2\n")


def test_file_headers_are_ignored() -> None:
    diff = "--- a/tests/t.py\n+++ b/tests/t.py\n-    y = 1\n+    y = 2\n"
    assert not owners.asserts_changed(diff)


def test_non_assertion_lines_are_ignored() -> None:
    assert not owners.asserts_changed("-    x = 1\n+    x = 2\n")


def test_added_assert_is_a_change() -> None:
    assert owners.asserts_changed("+    assert ok\n")


@pytest.mark.parametrize(
    "line",
    ["with pytest.raises(ValueError):", "expect(a).toBe(1)", "assert_eq!(a, b);", "assertEquals(a, b)"],
)
def test_other_toolchain_assertions_are_marked(line: str) -> None:
    assert owners.asserts_changed(f"+{line}\n")


def test_empty_diff_is_no_change() -> None:
    assert not owners.asserts_changed("")


# 9. fix_note


@pytest.mark.parametrize(
    ("asserts", "changed", "text"),
    [
        ("s65 G9", True, "changed what a test asserts because s65 G9"),
        ("s65 G9", False, "named s65 G9, but no assertion line changed"),
        ("", True, "assertion lines changed, but no rule was named; check them"),
        ("", False, "no assertion change"),
    ],
)
def test_fix_note(asserts: str, changed: bool, text: str) -> None:
    record = FixRecord("integration-tester", ["a"], "abc", asserts, changed)
    assert owners.fix_note(record) == text


# 10. fix_lines


def test_fix_lines_without_a_rule() -> None:
    it = Item("t.py", Source.TEST, ["tests/e2e/t.py"], ["boom", "more"])
    assert owners.fix_lines(Fix("integration-tester", [it])) == [
        "Items:",
        "- tests/e2e/t.py (test)",
        "    boom",
        "    more",
    ]


def test_fix_lines_with_rule_and_why() -> None:
    it = Item("t.py", Source.LINT, ["tests/t.py"], ["x"])
    lines = owners.fix_lines(Fix("unit-tester", [it], "s65 G9", "lay_out never wipes"))
    assert lines[-1] == "Design rule the failing step cited: s65 G9: lay_out never wipes"
    assert lines[1] == "- tests/t.py (lint)"


def test_fix_lines_rule_without_why() -> None:
    lines = owners.fix_lines(Fix("unit-tester", [item("tests/t.py")], "s65 G9"))
    assert lines[-1] == "Design rule the failing step cited: s65 G9"


# 11. load_fix


def test_load_fix_round_trips_through_json() -> None:
    fix = Fix("unit-tester", [Item("t.py", Source.LINT, ["tests/t.py"], ["l"])], "r", "w")
    data = json.loads(json.dumps(asdict(fix)))
    back = owners.load_fix(data)
    assert back == fix
    assert back.items[0].source is Source.LINT


# gates additions (12-17 pure parts)


def test_route_is_a_verdict() -> None:
    assert gates.Verdict.ROUTE == "route"


def test_story_state_has_gate_fix_fields_empty() -> None:
    s = gates.StoryState("s1", "t", "implement")
    assert (s.files, s.fixes, s.fixed) == ([], [], [])


def test_outcome_has_fixes_and_hidden_output() -> None:
    o = gates.Outcome(gates.Verdict.PASS, output="secret")
    assert o.fixes == []
    assert "secret" not in repr(o)


def test_fix_refusal_without_story() -> None:
    assert gates.fix_refusal("integration-tester", None) == "a gate fix needs a story"


def test_fix_refusal_with_no_queue() -> None:
    s = gates.StoryState("s1", "t", "implement")
    assert gates.fix_refusal("integration-tester", s) == "story s1 has no gate fix queued"


def test_fix_refusal_wrong_role() -> None:
    s = gates.StoryState("s1", "t", "implement", fixes=[Fix("unit-tester", [item("tests/a.py")])])
    assert gates.fix_refusal("integration-tester", s) == "story s1's next gate fix is for unit-tester"


def test_fix_refusal_right_role() -> None:
    s = gates.StoryState("s1", "t", "implement", fixes=[Fix("unit-tester", [item("tests/a.py")])])
    assert gates.fix_refusal("unit-tester", s) is None


def test_fix_refusal_keeps_the_story_checks() -> None:
    s = gates.StoryState(
        "s1", "t", "implement", status=gates.StoryStatus.DONE, fixes=[Fix("unit-tester", [item("tests/a.py")])]
    )
    assert gates.fix_refusal("unit-tester", s) == gates.dispatch_refusal("developer", s)
    assert gates.fix_refusal("unit-tester", s) is not None


# 28. handoff asserts


def test_handoff_asserts_defaults_empty() -> None:
    h = roles.parse_handoff('```handoff\n{"status": "done"}\n```')
    assert h.asserts == ""


def test_handoff_asserts_is_read() -> None:
    h = roles.parse_handoff('```handoff\n{"status": "done", "asserts": "s65 G9"}\n```')
    assert h.asserts == "s65 G9"


def test_handoff_asserts_must_be_a_string() -> None:
    with pytest.raises(roles.HandoffError, match="asserts must be a string"):
        roles.parse_handoff('```handoff\n{"status": "done", "asserts": 3}\n```')


def test_gate_fix_kinds() -> None:
    from agile_team import boundary, events

    assert boundary.StepKind.GATE_FIX == "gate-fix"
    assert events.EventKind.GATE_FIX == "gate-fix"
