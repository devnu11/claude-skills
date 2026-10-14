"""Integration tests: the chat lock (``lock`` via ``Store``) around a whole ``say``.

Only the model is faked; lock files are real and written as another process would.
"""

from __future__ import annotations

import json
import os

import pytest
from group_chat.state import StateError

from ..conftest import FakeBackend
from ..lockutil import dead_pid, live_pid, write_owner
from .conftest import MakeChat

pytestmark = pytest.mark.integration


def test_lock_owner_record_during_say(make_chat: MakeChat) -> None:
    chat = make_chat(FakeBackend())
    seen: list[dict[str, object]] = []

    class Spy(FakeBackend):
        def complete(self, system: str, prompt: str, model: str | None) -> str:
            seen.append(json.loads(chat.store.lock_path.read_text()))
            return super().complete(system, prompt, model)

    make_chat(Spy()).say("@po hi")
    assert seen[0]["pid"] == os.getpid()
    assert set(seen[0]) == {"pid", "host", "token"}


def test_dead_lock_is_taken_over_and_message_saved(
    make_chat: MakeChat, backend: FakeBackend
) -> None:
    chat = make_chat(backend)
    chat.store.directory.mkdir()
    write_owner(chat.store.lock_path, dead_pid())
    assert [t.speaker for t in chat.say("@po hi")] == ["po"]
    assert not chat.store.lock_path.exists()
    assert len(chat.store.load().turns) == 2


def test_live_lock_refuses_and_is_kept(make_chat: MakeChat, backend: FakeBackend) -> None:
    chat = make_chat(backend)
    chat.store.directory.mkdir()
    write_owner(chat.store.lock_path, live_pid(), token="theirs")
    with pytest.raises(StateError, match=f"held by pid {live_pid()}"):
        chat.say("@po hi")
    assert json.loads(chat.store.lock_path.read_text())["token"] == "theirs"
    assert backend.calls == []
    assert not chat.store.path.exists()
