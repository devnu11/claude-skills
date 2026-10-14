"""Unit tests for ``decision_log``: marker parsing and the pinned log."""

from __future__ import annotations

import pytest
from group_chat.decision_log import DecisionLog, Entry

pytestmark = pytest.mark.unit


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


def test_indented_marker_counts() -> None:
    log = DecisionLog()
    log.apply("po", "notes:\n    DECISION: indented\n\tQUESTION: tabbed")
    assert [e.text for e in log.decisions] == ["indented"]
    assert [e.text for e in log.questions] == ["tabbed"]


@pytest.mark.parametrize(
    "text",
    ["> DECISION: quoted", "- DECISION: bullet", "`DECISION: code`", "Note DECISION: inline"],
)
def test_marker_not_at_line_start_is_ignored(text: str) -> None:
    log = DecisionLog()
    log.apply("po", text)
    assert log.decisions == []


def test_marker_text_is_trimmed() -> None:
    log = DecisionLog()
    log.apply("po", "DECISION:\t  ship it  \t")
    assert log.decisions == [Entry("D1", "ship it", "po")]


def test_marker_needs_text_on_same_line() -> None:
    log = DecisionLog()
    log.apply("po", "DECISION:\nship it")
    assert log.decisions == []


@pytest.mark.xfail(strict=True, reason="BUG: a whitespace-only DECISION pins an empty entry")
def test_whitespace_only_decision_is_ignored() -> None:
    log = DecisionLog()
    log.apply("po", "DECISION:   ")
    assert log.decisions == []


def test_resolved_unknown_id_changes_nothing() -> None:
    log = DecisionLog()
    log.apply("po", "QUESTION: a?")
    log.apply("po", "RESOLVED: Q9")
    assert [e.id for e in log.questions] == ["Q1"]


def test_resolved_twice_is_harmless() -> None:
    log = DecisionLog()
    log.apply("po", "QUESTION: a?\nQUESTION: b?")
    log.apply("po", "RESOLVED: Q1\nRESOLVED: Q1")
    assert [e.id for e in log.questions] == ["Q2"]


def test_resolved_decision_id_does_not_remove_decision() -> None:
    log = DecisionLog()
    log.apply("po", "DECISION: keep")
    log.apply("po", "RESOLVED: D1")
    assert [e.id for e in log.decisions] == ["D1"]


def test_question_ids_never_reused_after_resolve() -> None:
    log = DecisionLog()
    log.apply("po", "QUESTION: a?\nRESOLVED: Q1\nQUESTION: b?")
    assert log.questions == [Entry("Q2", "b?", "po")]


@pytest.mark.xfail(strict=True, reason="BUG: 'RESOLVED: Q1.' (trailing punctuation) is ignored")
def test_resolved_with_trailing_punctuation_closes() -> None:
    log = DecisionLog()
    log.apply("po", "QUESTION: a?")
    log.apply("po", "RESOLVED: Q1.")
    assert log.questions == []


def test_from_dict_partial_uses_defaults() -> None:
    log = DecisionLog.from_dict({"decisions": [{"id": "D1", "text": "a", "by": "po"}]})
    assert log.next_decision == 1
    assert log.questions == []


def test_from_dict_rejects_malformed_entry() -> None:
    with pytest.raises(TypeError):
        DecisionLog.from_dict({"decisions": [{"id": "D1"}]})
