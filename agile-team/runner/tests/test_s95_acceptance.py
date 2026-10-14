"""s95: acceptance per environment: the round, the verdict, the handoff field (AE6-AE9, AE11, AE14)."""

import json

import pytest
from agile_team import acceptance, dispatch, gates
from agile_team.acceptance import Decision, Mark, Round, Tried
from agile_team.roles import Handoff, HandoffError, handoff_report, parse_handoff
from agile_team.story_spec import Criterion, Spec

NAMES = ("cli", "dashboard")


def ok(environment: str) -> Tried:
    return Tried(environment, Mark.PASS)


def bad(environment: str, *failed: str, summary: str = "broken", role: str | None = None) -> Tried:
    return Tried(environment, Mark.FAIL, tuple(failed), summary, role)


# ----- AE7 due / with_try ---------------------------------------------------


def test_due_is_the_first_untried_in_config_order() -> None:
    assert Round(NAMES).due() == "cli"
    assert Round(NAMES, (ok("cli"),)).due() == "dashboard"


def test_due_is_the_first_name_when_the_round_is_complete() -> None:
    assert Round(NAMES, (ok("cli"), bad("dashboard", "AC2"))).due() == "cli"


def test_due_is_none_without_names() -> None:
    assert Round(()).due() is None


def test_due_ignores_unnamed_environments() -> None:
    assert Round(NAMES, (ok("gone"),)).due() == "cli"
    assert not Round(NAMES, (ok("cli"), ok("gone"))).complete()


def test_with_try_replaces_and_keeps_config_order() -> None:
    r = Round(NAMES, (ok("cli"),)).with_try(ok("dashboard"))
    assert [t.environment for t in r.tried] == ["cli", "dashboard"]
    again = Round(NAMES, (ok("cli"),)).with_try(bad("cli", "AC1"))
    assert again.tried == (bad("cli", "AC1"),)


def test_with_try_puts_a_late_first_in_config_order() -> None:
    r = Round(NAMES, (ok("dashboard"),)).with_try(ok("cli"))
    assert [t.environment for t in r.tried] == ["cli", "dashboard"]


def test_with_try_on_a_complete_round_restarts_it() -> None:
    done = Round(NAMES, (ok("cli"), ok("dashboard")))
    assert done.with_try(bad("cli", "AC1")).tried == (bad("cli", "AC1"),)


def test_with_try_drops_unnamed_entries() -> None:
    r = Round(NAMES, (ok("gone"),)).with_try(ok("cli"))
    assert r.tried == (ok("cli"),)


# ----- AE8 decision and texts ----------------------------------------------


def test_decision_next_while_incomplete_even_after_a_fail() -> None:
    assert Round(NAMES).decision() is Decision.NEXT
    assert Round(NAMES, (bad("cli", "AC1"),)).decision() is Decision.NEXT


def test_decision_pass_and_fail() -> None:
    assert Round(NAMES, (ok("cli"), ok("dashboard"))).decision() is Decision.PASS
    assert Round(NAMES, (ok("cli"), bad("dashboard", "AC2"))).decision() is Decision.FAIL


def test_failures_in_config_order() -> None:
    r = Round(NAMES, (bad("cli", "AC1"), bad("dashboard", "AC2")))
    assert [t.environment for t in r.failures()] == ["cli", "dashboard"]


def test_failed_text_lists_every_failure() -> None:
    r = Round(
        NAMES,
        (
            bad("cli", "AC2", summary="export prints no header row"),
            bad("dashboard", "AC4", summary="the Export button is missing"),
        ),
    )
    assert r.failed_text() == (
        "acceptance failed in 2 of 2 environments:\n"
        "- cli: AC2: export prints no header row\n"
        "- dashboard: AC4: the Export button is missing"
    )


def test_failed_text_names_only_the_failed_and_joins_ids() -> None:
    r = Round(NAMES, (ok("cli"), bad("dashboard", "AC3", "AC4", summary="x")))
    assert r.failed_text() == "acceptance failed in 1 of 2 environments:\n- dashboard: AC3, AC4: x"


def test_failed_text_without_ids() -> None:
    r = Round(NAMES, (ok("cli"), bad("dashboard", summary="x")))
    assert "- dashboard: no AC named: x" in r.failed_text()


def test_passed_text_names_the_environments() -> None:
    r = Round(NAMES, (ok("cli"), ok("dashboard")))
    assert r.passed_text() == "acceptance passed in every environment: cli, dashboard"


def test_next_text_names_environment_mark_and_next() -> None:
    r = Round(NAMES, (ok("cli"),))
    assert r.next_text(ok("cli")) == "acceptance environment cli: pass; next: dashboard"


def test_marks() -> None:
    r = Round(("cli", "dashboard", "review"), (ok("cli"), bad("dashboard", "AC2")))
    assert r.marks() == [
        {"name": "cli", "verdict": "pass"},
        {"name": "dashboard", "verdict": "fail"},
        {"name": "review", "verdict": ""},
    ]


def test_tried_of_done_is_a_pass() -> None:
    assert acceptance.tried_of("cli", Handoff("done", "fine")).mark is Mark.PASS


def test_tried_of_changes_requested_is_a_fail() -> None:
    h = Handoff("changes_requested", "no header", next_role="developer", failed_acs=["AC2"])
    assert acceptance.tried_of("cli", h) == Tried(
        "cli", Mark.FAIL, ("AC2",), "no header", "developer"
    )


def test_load_tried_round_trips() -> None:
    data = {
        "environment": "cli",
        "mark": "fail",
        "failed": ["AC1"],
        "summary": "s",
        "next_role": None,
    }
    assert acceptance.load_tried(data) == Tried("cli", Mark.FAIL, ("AC1",), "s", None)


# ----- report / brief ------------------------------------------------------


def test_report_file() -> None:
    assert acceptance.report_file("s120") == ".team/acceptance/s120.md"


def test_has_section() -> None:
    text = "# Report\n## Environment: cli   \nfine\n"
    assert acceptance.has_section(text, "cli")
    assert not acceptance.has_section(text, "dashboard")
    assert not acceptance.has_section("## Environment: cli-extra\n", "cli")
    assert not acceptance.has_section(None, "cli")


def test_brief_section_lists_only_that_environments_acs() -> None:
    spec = Spec(
        "s120",
        "T",
        (
            Criterion("AC1", "export prints rows", "cli"),
            Criterion("AC2", "button exists", "dashboard"),
            Criterion("AC3", "header row", "cli"),
        ),
    )
    text = acceptance.brief_section(spec, "cli")
    assert "## Criteria for this step: acceptance environment cli" in text
    assert "- AC1: export prints rows" in text
    assert "- AC3: header row" in text
    assert "AC2" not in text.replace('"failed_acs"', "")
    assert "## Environment: cli" in text
    assert ".team/acceptance/s120.md" in text
    assert '"failed_acs"' in text


# ----- AE9 Verdict.NEXT -----------------------------------------------------


def test_next_verdict_exists_and_is_no_setback() -> None:
    assert gates.Verdict.NEXT.value == "next"
    assert gates.Verdict.NEXT not in dispatch.SETBACKS


# ----- AE14 Handoff.failed_acs ---------------------------------------------


def block(**fields: object) -> str:
    return "```handoff\n" + json.dumps(fields) + "\n```"


def test_failed_acs_parses_in_order() -> None:
    h = parse_handoff(block(status="changes_requested", failed_acs=["AC3", "AC1"]))
    assert h.failed_acs == ["AC3", "AC1"]


def test_failed_acs_defaults_empty() -> None:
    assert parse_handoff(block(status="done")).failed_acs == []


@pytest.mark.parametrize("bad_value", ["AC1", [""], [1], ["AC1", " "]])
def test_failed_acs_must_be_a_list_of_ids(bad_value: object) -> None:
    with pytest.raises(HandoffError, match="failed_acs must be a list of AC ids"):
        parse_handoff(block(status="changes_requested", failed_acs=bad_value))


def test_failed_acs_needs_changes_requested() -> None:
    with pytest.raises(HandoffError, match="failed_acs needs status changes_requested"):
        parse_handoff(block(status="done", failed_acs=["AC1"]))


def test_handoff_report_omits_empty_failed_acs() -> None:
    assert "failed_acs" not in handoff_report(Handoff("done"))
    assert "failed_acs" in handoff_report(Handoff("changes_requested", failed_acs=["AC1"]))
