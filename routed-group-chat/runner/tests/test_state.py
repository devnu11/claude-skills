"""Unit tests for ``state``: turns, chat state and the on-disk store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from group_chat.state import ChatState, Store, Turn

pytestmark = pytest.mark.unit


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


def test_turn_round_trip_through_dict() -> None:
    turn = Turn("po", "line one\nline two")
    assert Turn(**vars(turn)) == turn


def test_chat_state_round_trip_through_dict() -> None:
    state = ChatState(summary="s", last_addressed=("po", "manager"))
    state.add(Turn("human", "QUESTION: q?\nDECISION: d"))
    data = json.loads(json.dumps(state.to_dict()))
    assert ChatState.from_dict(data) == state
    assert data["last_addressed"] == ["po", "manager"]


def test_from_dict_partial_uses_defaults() -> None:
    state = ChatState.from_dict({"summary": "only"})
    assert state == ChatState(summary="only")


def test_unicode_survives_save(tmp_path: Path) -> None:
    store = Store(tmp_path / "chat")
    state = ChatState(turns=[Turn("po", "café ✓")])
    store.save(state)
    assert store.load() == state


def test_save_creates_nested_directory(tmp_path: Path) -> None:
    store = Store(tmp_path / "a" / "b")
    store.save(ChatState())
    assert store.path.exists()


def test_corrupt_state_raises(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.path.write_text("{not json")
    with pytest.raises(json.JSONDecodeError):
        store.load()


def test_truncated_state_raises(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.save(ChatState(turns=[Turn("po", "hi")]))
    store.path.write_text(store.path.read_text()[:20])
    with pytest.raises(json.JSONDecodeError):
        store.load()


def test_turn_missing_field_raises(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.path.write_text('{"turns": [{"speaker": "po"}]}')
    with pytest.raises(TypeError):
        store.load()


def test_leftover_tmp_file_is_ignored(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.save(ChatState(summary="good"))
    store.path.with_suffix(".tmp").write_text("{half")
    assert store.load().summary == "good"


def test_add_does_not_dedupe_turns() -> None:
    state = ChatState()
    state.add(Turn("po", "x"))
    state.add(Turn("po", "x"))
    assert len(state.turns) == 2
