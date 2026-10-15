"""Unit tests for ``decision_log``: marker parsing and the pinned log."""

from __future__ import annotations

import re

import pytest
from group_chat.decision_log import PREFIX, DecisionLog, Entry, strip_fences, validate

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
    assert log.markdown == "## Decisions\n- none\n## Open questions\n- none"
    log.apply("human", "DECISION: weekly sync")
    assert "- [D1] weekly sync (by human)" in log.markdown


def test_round_trip() -> None:
    log = DecisionLog()
    log.apply("po", "DECISION: a\nQUESTION: b")
    assert DecisionLog.from_dict(log.json_data) == log
    assert DecisionLog.from_dict({}) == DecisionLog()


def test_indented_marker_counts() -> None:
    log = DecisionLog()
    log.apply("po", "notes:\n    DECISION: indented\n\tQUESTION: tabbed")
    assert [e.text for e in log.decisions] == ["indented"]
    assert [e.text for e in log.questions] == ["tabbed"]


@pytest.mark.parametrize(
    "text",
    ["> DECISION: quoted", "`DECISION: code`", "Note DECISION: inline", "decision: lower"],
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


@pytest.mark.parametrize(
    "line",
    [
        "- DECISION: x",
        "* DECISION: x",
        "**DECISION:** x",
        "- **DECISION:** x",
        "@Po, @MANAGER DECISION: x",
        "- @po **DECISION:** x",
    ],
)
def test_marker_prefixes_that_count(line: str) -> None:
    log = DecisionLog()
    log.apply("po", line)
    assert log.decisions == [Entry("D1", "x", "po")]


def test_lowercase_marker_does_not_count() -> None:
    log = DecisionLog()
    log.apply("po", "Decision: x\nquestion: y")
    assert log == DecisionLog()


def test_fenced_markers_are_ignored() -> None:
    log = DecisionLog()
    log.apply("po", "Example:\n```\nDECISION: fake\nQUESTION: fake?\n```\nDECISION: real")
    assert [e.text for e in log.decisions] == ["real"]
    assert log.questions == []


def test_indented_fence_with_language_is_ignored() -> None:
    log = DecisionLog()
    log.apply("po", "  ```text\n  DECISION: fake\n  ```\n")
    assert log.decisions == []


def test_marker_after_fence_closes_counts() -> None:
    log = DecisionLog()
    log.apply("po", "```\nx\n```\nDECISION: a\n```\nDECISION: b\n```")
    assert [e.text for e in log.decisions] == ["a"]


@pytest.mark.parametrize("line", ["QUESTION:", "QUESTION:   ", "- QUESTION:  "])
def test_blank_marker_text_is_ignored(line: str) -> None:
    log = DecisionLog()
    log.apply("po", line)
    assert log == DecisionLog()


@pytest.mark.parametrize(
    ("line", "still_open"),
    [
        ("RESOLVED: Q1, Q3", ["Q2"]),
        ("RESOLVED: q1,q3.", ["Q2"]),
        ("- RESOLVED: Q1 ,  Q3 settled", ["Q2"]),
        ("RESOLVED: q1 and q3.", ["Q2", "Q3"]),
        ("RESOLVED: Q1 now that Q3 is moot", ["Q2", "Q3"]),
        ("RESOLVED: Q1/Q3!", ["Q2", "Q3"]),
        ("- RESOLVED: Q3; Q1", ["Q1", "Q2"]),
        ("RESOLVED: see Q1", ["Q1", "Q2", "Q3"]),
    ],
)
def test_resolved_closes_leading_comma_separated_ids(line: str, still_open: list[str]) -> None:
    log = DecisionLog()
    log.apply("po", "QUESTION: a?\nQUESTION: b?\nQUESTION: c?")
    log.apply("manager", line)
    assert [e.id for e in log.questions] == still_open


def test_resolved_does_not_match_inside_words() -> None:
    log = DecisionLog()
    log.apply("po", "QUESTION: a?")
    log.apply("po", "RESOLVED: FAQ1 XQ1")
    assert [e.id for e in log.questions] == ["Q1"]


def test_prefix_is_exported_for_handoff() -> None:
    assert re.match(PREFIX + "HANDOFF", "- @po **HANDOFF")


def test_blank_bold_marker_is_ignored() -> None:
    log = DecisionLog()
    log.apply("po", "- **DECISION:**  ")
    assert log.decisions == []


@pytest.mark.parametrize(
    ("line", "text"),
    [
        ("**DECISION: ship**", "ship"),
        ("- **DECISION:** ship", "ship"),
        ("- **DECISION: ship Friday**  ", "ship Friday"),
        ("DECISION: use **bold** here", "use **bold** here"),
    ],
)
def test_trailing_bold_is_dropped(line: str, text: str) -> None:
    log = DecisionLog()
    log.apply("po", line)
    assert [e.text for e in log.decisions] == [text]


@pytest.mark.parametrize("line", ["**DECISION:**", "- **DECISION:**  "])
def test_bold_marker_without_text_is_ignored(line: str) -> None:
    log = DecisionLog()
    log.apply("po", line)
    assert log.decisions == []


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("a\n```\nDECISION: x\n```\nb", "a\nb"),
        ("a\n~~~\nDECISION: x\n~~~\nb", "a\nb"),
        ("a\n```python\nDECISION: x", "a"),
        ("```x```\nDECISION: y", "```x```\nDECISION: y"),
        ("```\nq\n~~~\nDECISION: v\n```\nDECISION: u", "DECISION: u"),
        ("~~~\n```\n~~~\nDECISION: w", "DECISION: w"),
        ("  ```\n  DECISION: x\n  ```", ""),
        ("no fences", "no fences"),
    ],
)
def test_strip_fences(text: str, kept: str) -> None:
    assert strip_fences(text) == kept


def test_unclosed_fence_hides_rest_of_message() -> None:
    log = DecisionLog()
    log.apply("po", "DECISION: a\n~~~\nDECISION: b\nQUESTION: c?")
    assert [e.text for e in log.decisions] == ["a"]
    assert log.questions == []


def test_tilde_fenced_markers_are_ignored() -> None:
    log = DecisionLog()
    log.apply("po", "~~~md\nRESOLVED: Q1\n~~~")
    log.apply("po", "QUESTION: open?")
    assert [e.id for e in log.questions] == ["Q1"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "log must be a table"),
        ({"next_decision": 1.5}, "next_decision must be a int"),
        ({"decisions": {}}, "decisions must be a list"),
        ({"questions": [{"id": "Q1", "text": "a", "by": 1}]}, "by must be a str"),
        ({"decisions": [{"id": "D1", "text": "a", "by": "po", "x": 1}]}, "unknown key"),
    ],
)
def test_validate_refuses_bad_log(data: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate(data, ValueError)


def test_validate_accepts_json_data_output() -> None:
    log = DecisionLog()
    log.apply("po", "DECISION: a\nQUESTION: b")
    validate(log.json_data, ValueError)


@pytest.mark.parametrize("line", ["DECISION: **", "- **DECISION:** ** "])
def test_marker_text_of_only_bold_is_ignored(line: str) -> None:
    log = DecisionLog()
    log.apply("po", line)
    assert log.decisions == []
