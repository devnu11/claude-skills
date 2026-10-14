from __future__ import annotations

from pathlib import Path

from group_chat.state import ChatState, Store, Turn


def test_new_chat_is_empty(tmp_path: Path) -> None:
    assert Store(tmp_path / "chat").load() == ChatState()


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    store = Store(tmp_path / "chat")
    state = ChatState(summary="s", last_addressed=("po",))
    state.add(Turn("po", "DECISION: go"))
    store.save(state)
    assert store.load() == state
    assert not store.path.with_suffix(".tmp").exists()


def test_add_applies_markers() -> None:
    state = ChatState()
    state.add(Turn("human", "QUESTION: when?"))
    assert state.log.questions[0].by == "human"


def test_turn_render() -> None:
    assert Turn("po", "hi").render() == "@po: hi"
