"""s19: when the runner hands control to the PO (the HANDOVERS table and the prompt)."""

import pytest
from agile_team import handover
from agile_team.gates import PreviousStep, StoryState, StoryStatus
from agile_team.handover import HANDOVERS, Pass, Trigger
from agile_team.state import RunState

T = Trigger


def gated(verdict="pass", **gate) -> dict:
    return {"verdict": verdict, "reason": "", "story_status": "active", **gate}


def test_trigger_values_are_snake_case() -> None:
    assert [t.value for t in Trigger] == [
        "refused",
        "error",
        "stopped",
        "bad_handoff",
        "questions",
        "quarantine",
        "round_cap",
        "unroutable",
        "human_message",
        "sprint_end",
        "stalled",
    ]


def test_table_rows_are_in_design_order() -> None:
    assert [r.trigger for r in HANDOVERS] == [
        T.REFUSED,
        T.ERROR,
        T.STOPPED,
        T.BAD_HANDOFF,
        T.QUESTIONS,
        T.QUARANTINE,
        T.ROUND_CAP,
        T.UNROUTABLE,
    ]
    assert set(handover.QUIET_AFTER_PO) == {T.SPRINT_END, T.STALLED}


ROWS = [
    (
        {"status": "refused", "role": "architect", "reason": "no"},
        T.REFUSED,
        "s1: architect was refused: no",
    ),
    (
        {"status": "error", "role": "architect", "reason": "crashed: X: y"},
        T.ERROR,
        "s1: architect crashed: crashed: X: y; details in .team/run/crash.log",
    ),
    (
        {"status": "blocked", "role": "architect", "summary": "stuck"},
        T.STOPPED,
        "s1: architect reported blocked: stuck",
    ),
    (
        {"status": "failed", "role": "developer", "summary": "dead"},
        T.STOPPED,
        "s1: developer reported failed: dead",
    ),
    (
        {"status": "bad_handoff", "role": "scribe", "reason": "no block"},
        T.BAD_HANDOFF,
        "s1: scribe gave no valid handoff: no block",
    ),
    (
        {"status": "done", "role": "architect", "open_questions": ["a?", "b?"]},
        T.QUESTIONS,
        "s1: architect asks: a?; b?",
    ),
    (
        {"status": "done", "role": "developer", "quarantine": "abc123"},
        T.QUARANTINE,
        "s1: developer's out-of-scope changes are quarantined in abc123; tell the owning role "
        "to reuse them (git cherry-pick -n abc123) or ignore them",
    ),
    (
        {
            "status": "done",
            "role": "developer",
            "gate": gated("bounce", story_status="needs_manager"),
        },
        T.ROUND_CAP,
        "s1: hit the round cap; run the manager on it for a ruling",
    ),
    (
        {
            "status": "changes_requested",
            "role": "code-reviewer",
            "next_role": "devops",
            "gate": gated("bounce"),
        },
        T.UNROUTABLE,
        "s1: code-reviewer sent it back for devops, which owns no pipeline step; "
        "brief devops yourself, then continue_story",
    ),
]


@pytest.mark.parametrize(("report", "trigger", "line"), ROWS)
def test_each_row_matches_and_formats(report, trigger, line) -> None:
    assert handover.triggers(report) == [trigger]
    assert handover.report_lines(report, "s1") == [line]


@pytest.mark.parametrize(
    "report",
    [
        {"status": "done", "role": "architect", "gate": gated("pass")},
        {"status": "done", "role": "developer", "gate": gated("bounce", reason="tests fail")},
        {"status": "done", "role": "integration-tester", "gate": gated("bounce")},
        {"status": "bad_handoff", "role": "unit-tester", "reason": "r"},
        {"status": "returned", "role": "customer-proxy", "gate": gated("return")},
        {
            "status": "changes_requested",
            "role": "code-reviewer",
            "next_role": "developer-gui",
            "gate": gated("bounce"),
        },
        {
            "status": "changes_requested",
            "role": "customer-proxy",
            "next_role": "architect",
            "gate": gated("bounce"),
        },
        {"status": "changes_requested", "role": "x", "next_role": "devops", "gate": gated("pass")},
        {"status": "done", "open_questions": [], "quarantine": None},
        {},
    ],
)
def test_quiet_reports_hand_over_nothing(report) -> None:
    assert handover.triggers(report) == []
    assert handover.matching(report) == []
    assert handover.hold_reason(report) is None
    assert handover.report_lines(report, "s1") == []


def test_bad_handoff_of_a_gated_role_does_not_hand_over() -> None:
    assert handover.triggers({"status": "bad_handoff", "role": "developer"}) == []
    assert handover.triggers({"status": "bad_handoff", "role": "manager"}) == [T.BAD_HANDOFF]


def test_unroutable_needs_a_bounce_and_a_next_role() -> None:
    no_role = {"gate": gated("bounce"), "status": "changes_requested", "next_role": None}
    assert handover.triggers(no_role) == []
    not_bounce = {"gate": gated("pass"), "next_role": "devops"}
    assert handover.triggers(not_bounce) == []
    pipeline_role = {"gate": gated("bounce"), "next_role": "quality-czar"}
    assert handover.triggers(pipeline_role) == []


def test_a_report_can_match_several_rows_in_table_order() -> None:
    report = {
        "status": "blocked",
        "role": "architect",
        "summary": "s",
        "open_questions": ["q"],
        "quarantine": "abc",
    }
    assert handover.triggers(report) == [T.STOPPED, T.QUESTIONS, T.QUARANTINE]
    assert handover.hold_reason(report) == "stopped, questions, quarantine"
    assert len(handover.report_lines(report, "s1")) == 3


def test_report_fields_default_to_empty_and_name_the_run() -> None:
    fields = handover.report_fields({}, None)
    assert fields == dict.fromkeys(
        ["role", "status", "summary", "reason", "questions", "quarantine", "next_role"], ""
    ) | {"story": "run"}
    full = {"role": "r", "open_questions": ["a", "b"], "quarantine": "q", "next_role": "n"}
    assert handover.report_fields(full, "s2") == fields | {
        "story": "s2",
        "role": "r",
        "questions": "a; b",
        "quarantine": "q",
        "next_role": "n",
    }


def test_report_fields_turn_none_into_empty_strings() -> None:
    fields = handover.report_fields({"next_role": None, "quarantine": None, "summary": None}, "s1")
    assert fields["next_role"] == fields["quarantine"] == fields["summary"] == ""


def test_story_less_report_line_says_run() -> None:
    report = {"status": "error", "role": "manager", "reason": "crashed: E"}
    assert handover.report_lines(report, None)[0].startswith("run: manager crashed")


# ----- previous_step (R15) ----------------------------------------------------


def test_previous_step_from_a_gate_report() -> None:
    report = {
        "role": "code-reviewer",
        "status": "changes_requested",
        "summary": "too long",
        "next_role": "developer-gui",
        "gate": gated("bounce", reason="too long"),
    }
    assert handover.previous_step(report) == PreviousStep(
        "code-reviewer", "changes_requested", "too long", "bounce", "too long", "developer-gui"
    )


def test_previous_step_from_a_bad_handoff() -> None:
    report = {"role": "unit-tester", "status": "bad_handoff", "reason": "no block"}
    assert handover.previous_step(report) == PreviousStep(
        "unit-tester", "bad_handoff", "", "bounce", "no block"
    )


@pytest.mark.parametrize(
    "report",
    [
        {"role": "architect", "status": "refused", "reason": "x"},
        {"role": "architect", "status": "error", "reason": "x"},
        {"role": "scribe", "status": "done", "summary": "s"},
        {"role": "architect", "status": "halted"},
    ],
)
def test_previous_step_ignores_other_reports(report) -> None:
    assert handover.previous_step(report) is None


# ----- Pass, board and prompt ------------------------------------------------


def test_pass_defaults_and_quiet() -> None:
    assert Pass([], [], []).steps == 0
    assert Pass([T.SPRINT_END], ["l"], []).quiet()
    assert Pass([T.STALLED, T.SPRINT_END], [], []).quiet()
    assert not Pass([T.SPRINT_END], [], [], steps=2).quiet()
    assert not Pass([T.HUMAN_MESSAGE], [], []).quiet()
    assert not Pass([T.SPRINT_END, T.HUMAN_MESSAGE], [], []).quiet()
    assert not Pass([], [], []).quiet()


def board_state() -> RunState:
    st = RunState(sprint=2)
    add = st.stories
    add["s19"] = StoryState("s19", "a", "implement", rounds=1, sprint=2, hold="stopped")
    add["s20"] = StoryState("s20", "b", "done", status=StoryStatus.DONE, sprint=2)
    add["s21"] = StoryState("s21", "c", "design", sprint=2)
    add["s22"] = StoryState("s22", "d", "design", sprint=1)
    add["s23"] = StoryState("s23", "e", "design")
    return st


def test_board_lists_the_current_sprint_only() -> None:
    assert handover.board(board_state()) == (
        "Stories: s19 implement r1 held, s20 done, s21 design r0"
    )


def test_board_shows_non_active_status() -> None:
    st = RunState(sprint=1)
    st.stories["s1"] = StoryState(
        "s1", "a", "implement", rounds=3, status=StoryStatus.NEEDS_MANAGER, sprint=1
    )
    st.stories["s2"] = StoryState("s2", "b", "e2e", status=StoryStatus.BLOCKED, sprint=1)
    assert handover.board(st) == "Stories: s1 implement r3 needs_manager, s2 e2e r0 blocked"


def test_prompt_layout() -> None:
    pass_ = Pass([T.ERROR], ["first line", "second line"], ["s19"], steps=3)
    lines = handover.prompt(pass_, board_state()).splitlines()
    assert lines[0] == "The runner needs you (sprint 2; 3 steps since your last turn):"
    assert lines[1:3] == ["- first line", "- second line"]
    assert lines[3] == "Stories: s19 implement r1 held, s20 done, s21 design r0"
    assert "\n".join(lines[4:]) == handover.HANDOVER_FOOTER


def test_footer_names_the_tools() -> None:
    footer = handover.HANDOVER_FOOTER
    assert footer.startswith("Handle these, then end your turn;")
    for name in ("continue_story", "set_developer", "run_role"):
        assert name in footer
