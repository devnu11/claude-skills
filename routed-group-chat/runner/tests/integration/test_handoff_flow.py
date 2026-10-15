"""Integration tests: handoff chains through GroupChat, context and Store.

Only the model is faked; the roster and state.json are real files.
"""

from __future__ import annotations

import pytest
from group_chat.state import Turn

from ..conftest import FakeBackend
from .conftest import MakeChat

pytestmark = pytest.mark.integration


def speakers(turns: list[Turn]) -> list[str]:
    return [turn.speaker for turn in turns]


def test_chain_within_cap(make_chat: MakeChat, backend: FakeBackend) -> None:
    backend.replies = {"manager": ["HANDOFF: @po"], "po": ["HANDOFF: @liaison"]}
    replies = make_chat(backend).say("@manager go")
    assert speakers(replies) == ["manager", "po", "liaison"]


def test_chain_past_cap_records_note_in_thread(make_chat: MakeChat, backend: FakeBackend) -> None:
    backend.replies = {
        "manager": ["HANDOFF: @po"],
        "po": ["HANDOFF: @liaison"],
        "liaison": ["HANDOFF: @manager"],
    }
    chat = make_chat(backend)
    replies = chat.say("@manager go")
    assert speakers(replies) == ["manager", "po", "liaison", "orchestrator"]
    saved = chat.store.load().turns
    assert saved[-1].line == "@orchestrator: handoff to @manager dropped: limit reached"


def test_cap_is_per_human_message(make_chat: MakeChat, backend: FakeBackend) -> None:
    backend.replies = {"manager": ["HANDOFF: @po", "HANDOFF: @po"]}
    make_chat(backend, max_handoffs=1).say("@manager a")
    replies = make_chat(backend, max_handoffs=1).say("@manager b")
    assert speakers(replies) == ["manager", "po"]


def test_handed_role_sees_handoff_reply(make_chat: MakeChat, backend: FakeBackend) -> None:
    backend.replies = {"manager": ["Scope is yours.\nHANDOFF: @po"]}
    make_chat(backend).say("@manager scope?")
    expected = '<turn speaker="manager">\nScope is yours.\nHANDOFF: @po\n</turn>'
    assert expected in backend.calls[-1].prompt
    assert backend.calls[-1].prompt.endswith("Reply as @po.")


def test_handoff_inside_multi_address_queue(make_chat: MakeChat, backend: FakeBackend) -> None:
    backend.replies = {"po": ["HANDOFF: @liaison"]}
    replies = make_chat(backend).say("@po @manager views?")
    assert speakers(replies) == ["po", "manager", "liaison"]


def test_orchestrator_note_survives_reload_and_is_seen(
    make_chat: MakeChat, backend: FakeBackend
) -> None:
    backend.replies = {"manager": ["HANDOFF: @po"]}
    make_chat(backend, max_handoffs=0).say("@manager x")
    make_chat(backend).say("@po y")
    assert '<turn speaker="orchestrator">\nhandoff to @po dropped' in backend.calls[-1].prompt


def test_handoff_to_queued_role_skipped_under_all(
    make_chat: MakeChat, backend: FakeBackend
) -> None:
    backend.replies = {"manager": ["HANDOFF: @liaison"], "po": ["**HANDOFF:** @Liaison"]}
    chat = make_chat(backend)
    replies = chat.say("@all status?")
    assert speakers(replies) == ["manager", "po", "liaison"]
    assert chat.store.load().last_addressed == ("manager", "po", "liaison")


def test_bulleted_handoff_routes(make_chat: MakeChat, backend: FakeBackend) -> None:
    backend.replies = {"manager": ["Done.\n- **HANDOFF:** @PO"]}
    assert speakers(make_chat(backend).say("@manager go")) == ["manager", "po"]
