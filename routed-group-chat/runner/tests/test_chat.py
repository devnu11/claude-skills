"""Unit tests for ``chat``: the orchestrator with a scripted backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from group_chat.addressing import AddressError
from group_chat.chat import GroupChat, Limits, handoff_of
from group_chat.roster import Roster
from group_chat.state import Store, Turn

from .conftest import FakeBackend

pytestmark = pytest.mark.unit

NAMES = ("manager", "po", "liaison")


def make(roster: Roster, backend: FakeBackend, tmp_path: Path, **limits: Any) -> GroupChat:
    return GroupChat(roster, backend, Store(tmp_path / "chat"), Limits(**limits))


def test_only_the_addressed_role_answers(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.replies = {"manager": ["Friday."]}
    chat = make(roster, backend, tmp_path)
    assert chat.say("@manager when?") == [Turn("manager", "Friday.")]
    assert len(backend.calls) == 1
    assert backend.calls[0].model is None


def test_each_role_sees_the_whole_thread(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.replies = {"po": ["scope is fixed"]}
    chat = make(roster, backend, tmp_path)
    chat.say("@po scope?")
    chat.say("@manager does that work?")
    last = backend.calls[-1].prompt
    assert "@human: @po scope?" in last
    assert "@po: scope is fixed" in last
    assert last.endswith("Reply as @manager.")


def test_broadcast_answers_in_roster_order(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    replies = make(roster, backend, tmp_path).say("@all status?")
    assert [turn.speaker for turn in replies] == list(NAMES)


def test_sticky_addressee_persists_across_runs(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    make(roster, backend, tmp_path).say("@po first")
    replies = make(roster, backend, tmp_path).say("and then?")
    assert [turn.speaker for turn in replies] == ["po"]


def test_refused_message_is_not_recorded(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    chat = make(roster, backend, tmp_path)
    with pytest.raises(AddressError):
        chat.say("hello?")
    assert chat.store.load().turns == []


def test_handoff_passes_the_floor(roster: Roster, backend: FakeBackend, tmp_path: Path) -> None:
    backend.replies = {"manager": ["Not mine.\nHANDOFF: @po"]}
    replies = make(roster, backend, tmp_path).say("@manager scope?")
    assert [turn.speaker for turn in replies] == ["manager", "po"]


def test_handoff_limit_drops_extra_hops(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.replies = {"manager": ["HANDOFF: @po"], "po": ["HANDOFF: @manager"]}
    replies = make(roster, backend, tmp_path, max_handoffs=1).say("@manager ?")
    assert [turn.speaker for turn in replies] == ["manager", "po", "orchestrator"]
    assert "handoff to @manager dropped" in replies[-1].text


def test_decisions_from_replies_are_pinned(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.replies = {"po": ["DECISION: ship Friday"]}
    chat = make(roster, backend, tmp_path)
    chat.say("@po QUESTION: ship date?")
    log = chat.store.load().log
    assert [e.text for e in log.decisions] == ["ship Friday"]
    assert [e.by for e in log.questions] == ["human"]


def test_compaction_folds_old_turns_into_summary(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.summary = "folded"
    chat = make(roster, backend, tmp_path, recent_tokens=1, keep_turns=2)
    chat.say("@po one")
    chat.say("@po two")
    state = chat.store.load()
    assert state.summary == "folded"
    assert [turn.text for turn in state.turns] == ["@po two", "po reply"]
    assert "@human: @po one" in backend.calls[-1].prompt


def test_no_compaction_under_budget(roster: Roster, backend: FakeBackend, tmp_path: Path) -> None:
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


def test_role_model_is_passed_to_backend(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    make(roster, backend, tmp_path).say("@po hi")
    assert backend.calls[0].model == "haiku"


def test_summary_model_is_used_for_compaction(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    make(roster, backend, tmp_path, recent_tokens=1, keep_turns=0, summary_model="opus").say(
        "@manager hi"
    )
    assert backend.calls[-1].model == "opus"


def test_human_handoff_line_does_not_route(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    replies = make(roster, backend, tmp_path).say("@manager hi\nHANDOFF: @po")
    assert [turn.speaker for turn in replies] == ["manager"]


def test_handoff_does_not_change_sticky_addressee(
    roster: Roster, backend: FakeBackend, tmp_path: Path
) -> None:
    backend.replies = {"manager": ["HANDOFF: @po"]}
    chat = make(roster, backend, tmp_path)
    chat.say("@manager x")
    assert chat.store.load().last_addressed == ("manager",)


def test_zero_handoffs_records_note(roster: Roster, backend: FakeBackend, tmp_path: Path) -> None:
    backend.replies = {"manager": ["HANDOFF: @po"]}
    chat = make(roster, backend, tmp_path, max_handoffs=0)
    replies = chat.say("@manager x")
    assert [turn.speaker for turn in replies] == ["manager", "orchestrator"]
    assert chat.store.load().turns[-1].speaker == "orchestrator"


def test_backend_failure_records_nothing(roster: Roster, tmp_path: Path) -> None:
    class Boom:
        def complete(self, system: str, prompt: str, model: str | None) -> str:
            raise RuntimeError("down")

    chat = GroupChat(roster, Boom(), Store(tmp_path / "chat"))
    with pytest.raises(RuntimeError):
        chat.say("@po hi")
    assert not chat.store.path.exists()


def test_message_is_stripped(roster: Roster, backend: FakeBackend, tmp_path: Path) -> None:
    chat = make(roster, backend, tmp_path)
    chat.say("  @po hi  \n")
    assert chat.store.load().turns[0] == Turn("human", "@po hi")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  HANDOFF: @po  ", "po"),
        ("HANDOFF:@po", "po"),
        ("HANDOFF: @po\nmore text", "po"),
        ("HANDOFF: @po @liaison", None),
    ],
)
def test_handoff_of_spacing(text: str, expected: str | None) -> None:
    assert handoff_of(text, NAMES, "manager") == expected


@pytest.mark.xfail(
    strict=True, reason="BUG: HANDOFF after leading @mentions is ignored; protocol allows it"
)
def test_handoff_after_leading_mentions() -> None:
    assert handoff_of("@po HANDOFF: @liaison", NAMES, "manager") == "liaison"
