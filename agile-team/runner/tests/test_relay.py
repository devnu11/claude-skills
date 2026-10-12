"""PO <-> liaison relay files."""

import pytest
from agile_team.relay import Note, Relay, RelayError

from .fake_system import FAKE_REPO


def test_post_answer_and_blocking() -> None:
    r = Relay(FAKE_REPO / "run")
    q = r.post(Note("question", "Which DB?", ["s1"]))
    r.post(Note("update", "started"))
    q2 = r.post(Note("question", "Name?", ["s2"]))
    assert [q.id, q2.id] == ["m1", "m3"]
    assert r.blocked_stories() == {"s1", "s2"}
    r.answer("m1", "sqlite")
    assert r.answers()["m1"].text == "sqlite"
    assert [m.id for m in r.open_questions()] == ["m3"]
    assert r.blocked_stories() == {"s2"}


def test_bad_kind_and_unknown_id() -> None:
    r = Relay(FAKE_REPO / "run")
    with pytest.raises(RelayError):
        r.post(Note("chat", "x"))
    r.post(Note("update", "x"))
    with pytest.raises(RelayError):
        r.answer("m1", "not a question")
    with pytest.raises(RelayError):
        r.answer("m9", "x")
