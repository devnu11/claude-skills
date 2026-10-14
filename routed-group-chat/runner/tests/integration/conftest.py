"""Integration fixtures: a roster on disk and a chat wired to real files."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from group_chat.backend import Backend
from group_chat.chat import GroupChat, Limits
from group_chat.roster import load
from group_chat.state import Store

MakeChat = Callable[..., GroupChat]


@pytest.fixture
def make_chat(roster_file: Path) -> MakeChat:
    """A fresh GroupChat over the on-disk roster and chat dir, as a new process would build."""

    def build(backend: Backend, **limits: Any) -> GroupChat:
        store = Store(roster_file.parent / "chat")
        return GroupChat(load(roster_file), backend, store, Limits(**limits))

    return build
