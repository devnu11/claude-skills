"""Integration tests: roster file, GroupChat, context, decision log and Store together.

Only the model is faked; the roster, prompt files and state.json are real files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from group_chat.state import Store, Turn

from ..conftest import FakeBackend
from .conftest import MakeChat

pytestmark = pytest.mark.integration


def test_prompt_file_reaches_system_prompt(make_chat: MakeChat, backend: FakeBackend) -> None:
    make_chat(backend).send("@po scope?")
    assert backend.calls[0].system.startswith("You own the backlog.")
    assert backend.calls[0].model == "haiku"


def test_prompt_file_edit_is_picked_up_on_reload(
    make_chat: MakeChat, backend: FakeBackend, roster_file: Path
) -> None:
    make_chat(backend).send("@po one")
    (roster_file.parent / "po.md").write_text("You are the new PO.\n")
    make_chat(backend).send("@po two")
    assert backend.calls[-1].system.startswith("You are the new PO.")


def test_state_survives_reload_in_fresh_chat(make_chat: MakeChat, backend: FakeBackend) -> None:
    backend.replies = {"po": ["DECISION: ship Friday\nQUESTION: who tests?"]}
    first = make_chat(backend)
    first.send("@po plan?")
    second = make_chat(FakeBackend())
    state = second.store.load()
    assert state == first.store.load()
    assert state.last_addressed == ("po",)
    assert [e.id for e in state.log.decisions] == ["D1"]
    assert second.send("and?")[0].speaker == "po"


def test_state_json_is_plain_data(make_chat: MakeChat, backend: FakeBackend) -> None:
    chat = make_chat(backend)
    chat.send("@manager hi")
    data = json.loads(chat.store.path.read_text())
    assert data["turns"] == [
        {"speaker": "human", "text": "@manager hi"},
        {"speaker": "manager", "text": "manager reply"},
    ]
    assert data["last_addressed"] == ["manager"]


def test_role_b_sees_role_a_reply_and_pinned_log(make_chat: MakeChat, backend: FakeBackend) -> None:
    backend.replies = {"po": ["Cut search.\nDECISION: cut search from v1"]}
    make_chat(backend).send("@po @manager what do we cut?")
    manager_prompt = backend.calls[1].prompt
    assert '<turn speaker="po">\nCut search.\n' in manager_prompt
    assert "- [D1] cut search from v1 (by po)" in manager_prompt
    assert manager_prompt.endswith("Reply as @manager.")


def test_second_run_sees_first_run_thread(make_chat: MakeChat, backend: FakeBackend) -> None:
    backend.replies = {"liaison": ["team blocked on CI"]}
    make_chat(backend).send("@liaison status?")
    make_chat(backend).send("@manager react")
    assert '<turn speaker="liaison">\nteam blocked on CI\n</turn>' in backend.calls[-1].prompt


def test_refused_message_leaves_existing_state(make_chat: MakeChat, backend: FakeBackend) -> None:
    chat = make_chat(backend)
    chat.send("@po hi")
    before = chat.store.path.read_text()
    with pytest.raises(ValueError):
        make_chat(backend).send("@cto hi")
    assert chat.store.path.read_text() == before


def test_resolved_across_runs(make_chat: MakeChat, backend: FakeBackend) -> None:
    make_chat(backend).send("@po QUESTION: budget?")
    backend.replies = {"manager": ["Approved.\nRESOLVED: Q1"]}
    make_chat(backend).send("@manager budget?")
    assert make_chat(backend).store.load().log.questions == []


def test_store_used_directly_matches_chat(make_chat: MakeChat, backend: FakeBackend) -> None:
    chat = make_chat(backend)
    chat.send("@po hi")
    assert Store(chat.store.directory).load().turns[-1] == Turn("po", "po reply")
