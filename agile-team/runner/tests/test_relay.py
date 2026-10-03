"""PO <-> liaison relay files."""

from pathlib import Path

import pytest
from agile_team.relay import Note, Relay, RelayError


def test_post_answer_and_blocking(tmp_path: Path) -> None:
    r = Relay(tmp_path / "run")
    q = r.post(Note("question", "Which DB?", ["s1"]))
    r.post(Note("update", "started"))
    q2 = r.post(Note("question", "Name?", ["s2"]))
    assert [q.id, q2.id] == ["m1", "m3"]
    assert r.blocked_stories() == {"s1", "s2"}
    r.answer("m1", "sqlite")
    assert r.answers()["m1"].text == "sqlite"
    assert [m.id for m in r.open_questions()] == ["m3"]
    assert r.blocked_stories() == {"s2"}


def test_bad_kind_and_unknown_id(tmp_path: Path) -> None:
    r = Relay(tmp_path)
    with pytest.raises(RelayError):
        r.post(Note("chat", "x"))
    r.post(Note("update", "x"))
    with pytest.raises(RelayError):
        r.answer("m1", "not a question")
    with pytest.raises(RelayError):
        r.answer("m9", "x")
