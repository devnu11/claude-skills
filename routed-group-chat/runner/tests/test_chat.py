from __future__ import annotations

from pathlib import Path

import pytest
from group_chat.addressing import AddressError
from group_chat.chat import GroupChat, Limits, handoff_of
from group_chat.roster import Roster
from group_chat.state import Store, Turn

from .conftest import FakeBackend

NAMES = ("manager", "po", "liaison")


def make(roster: Roster, backend: FakeBackend, tmp_path: Path, **limits: int) -> GroupChat:
    return GroupChat(roster, backend, Store(tmp_path / "chat"), Limits(**limits))


def test_only_the_addressed_role_answers(roster, backend, tmp_path: Path) -> None:
    backend.replies = {"manager": ["Friday."]}
    chat = make(roster, backend, tmp_path)
    assert chat.say("@manager when?") == [Turn("manager", "Friday.")]
    assert len(backend.calls) == 1
    assert backend.calls[0].model is None


def test_each_role_sees_the_whole_thread(roster, backend, tmp_path: Path) -> None:
    backend.replies = {"po": ["scope is fixed"]}
    chat = make(roster, backend, tmp_path)
    chat.say("@po scope?")
    chat.say("@manager does that work?")
    last = backend.calls[-1].prompt
    assert "@human: @po scope?" in last
    assert "@po: scope is fixed" in last
    assert last.endswith("Reply as @manager.")


def test_broadcast_answers_in_roster_order(roster, backend, tmp_path: Path) -> None:
    replies = make(roster, backend, tmp_path).say("@all status?")
    assert [turn.speaker for turn in replies] == list(NAMES)


def test_sticky_addressee_persists_across_runs(roster, backend, tmp_path: Path) -> None:
    make(roster, backend, tmp_path).say("@po first")
    replies = make(roster, backend, tmp_path).say("and then?")
    assert [turn.speaker for turn in replies] == ["po"]


def test_refused_message_is_not_recorded(roster, backend, tmp_path: Path) -> None:
    chat = make(roster, backend, tmp_path)
    with pytest.raises(AddressError):
        chat.say("hello?")
    assert chat.store.load().turns == []


def test_handoff_passes_the_floor(roster, backend, tmp_path: Path) -> None:
    backend.replies = {"manager": ["Not mine.\nHANDOFF: @po"]}
    replies = make(roster, backend, tmp_path).say("@manager scope?")
    assert [turn.speaker for turn in replies] == ["manager", "po"]


def test_handoff_limit_drops_extra_hops(roster, backend, tmp_path: Path) -> None:
    backend.replies = {"manager": ["HANDOFF: @po"], "po": ["HANDOFF: @manager"]}
    replies = make(roster, backend, tmp_path, max_handoffs=1).say("@manager ?")
    assert [turn.speaker for turn in replies] == ["manager", "po", "orchestrator"]
    assert "handoff to @manager dropped" in replies[-1].text


def test_decisions_from_replies_are_pinned(roster, backend, tmp_path: Path) -> None:
    backend.replies = {"po": ["DECISION: ship Friday"]}
    chat = make(roster, backend, tmp_path)
    chat.say("@po QUESTION: ship date?")
    log = chat.store.load().log
    assert [e.text for e in log.decisions] == ["ship Friday"]
    assert [e.by for e in log.questions] == ["human"]


def test_compaction_folds_old_turns_into_summary(roster, backend, tmp_path: Path) -> None:
    backend.summary = "folded"
    chat = make(roster, backend, tmp_path, recent_tokens=1, keep_turns=2)
    chat.say("@po one")
    chat.say("@po two")
    state = chat.store.load()
    assert state.summary == "folded"
    assert [turn.text for turn in state.turns] == ["@po two", "po reply"]
    assert "@human: @po one" in backend.calls[-1].prompt


def test_no_compaction_under_budget(roster, backend, tmp_path: Path) -> None:
    chat = make(roster, backend, tmp_path)
    chat.say("@po hi")
    assert chat.store.load().summary == ""
    assert len(backend.calls) == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("HANDOFF: @po", "po"),
        ("x\nHANDOFF: @po\nHANDOFF: @liaison", "liaison"),
        ("HANDOFF: @manager", None),
        ("HANDOFF: @cto", None),
        ("please handoff: @po", None),
    ],
)
def test_handoff_of(text: str, expected: str | None) -> None:
    assert handoff_of(text, NAMES, "manager") == expected
