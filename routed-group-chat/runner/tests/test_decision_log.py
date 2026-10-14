from __future__ import annotations

from group_chat.decision_log import DecisionLog, Entry


def test_markers_number_entries_in_order() -> None:
    log = DecisionLog()
    log.apply("po", "Agreed.\nDECISION: ship v1 Friday\nQUESTION: who owns QA?\n")
    log.apply("manager", "QUESTION: budget?\nDECISION: Dana owns QA\nRESOLVED: Q1")
    assert log.decisions == [
        Entry("D1", "ship v1 Friday", "po"),
        Entry("D2", "Dana owns QA", "manager"),
    ]
    assert log.questions == [Entry("Q2", "budget?", "manager")]


def test_resolved_accepts_lowercase_and_trailing_text() -> None:
    log = DecisionLog()
    log.apply("po", "QUESTION: scope?")
    log.apply("po", "RESOLVED: q1 settled above")
    assert log.questions == []


def test_marker_after_leading_mentions() -> None:
    log = DecisionLog()
    log.apply("human", "@po, @manager DECISION: go\nsee @po DECISION: not this")
    assert [entry.text for entry in log.decisions] == ["go"]


def test_text_without_markers_changes_nothing() -> None:
    log = DecisionLog()
    log.apply("po", "We decided nothing. decision: lowercase is not a marker")
    assert log == DecisionLog()


def test_render_empty_and_full() -> None:
    log = DecisionLog()
    assert log.render() == "## Decisions\n- none\n## Open questions\n- none"
    log.apply("human", "DECISION: weekly sync")
    assert "- [D1] weekly sync (by human)" in log.render()


def test_round_trip() -> None:
    log = DecisionLog()
    log.apply("po", "DECISION: a\nQUESTION: b")
    assert DecisionLog.from_dict(log.to_dict()) == log
    assert DecisionLog.from_dict({}) == DecisionLog()
