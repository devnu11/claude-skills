"""s71: ``Relay.tell`` / ``told`` on the fake system, hard link included (s62 T2)."""

import errno
from pathlib import Path

import pytest
from agile_team import system
from agile_team.numbered_queue import NumberedQueue
from agile_team.relay import Relay, Told

from .fake_system import FAKE_REPO, FakeSystem

RUN = FAKE_REPO / "run"


def messages_dir(run_dir: Path) -> Path:
    return run_dir / "liaison" / "messages"


# ----- the fake's hard_link --------------------------------------------------------------


def test_hard_link_copies_content_and_records_the_op(fake: FakeSystem) -> None:
    fake.put(FAKE_REPO / "a", "x")
    system.hard_link(FAKE_REPO / "b", FAKE_REPO / "a")
    assert fake.text_of(FAKE_REPO / "b") == "x" and fake.text_of(FAKE_REPO / "a") == "x"
    assert fake.ops[-1] == ("hard_link", FAKE_REPO / "b")


def test_hard_link_refuses_an_existing_link(fake: FakeSystem) -> None:
    fake.put(FAKE_REPO / "a", "x")
    fake.put(FAKE_REPO / "b", "old")
    with pytest.raises(FileExistsError):
        system.hard_link(FAKE_REPO / "b", FAKE_REPO / "a")
    assert fake.text_of(FAKE_REPO / "b") == "old"


def test_hard_link_to_a_missing_target_raises(fake: FakeSystem) -> None:
    with pytest.raises(FileNotFoundError):
        system.hard_link(FAKE_REPO / "b", FAKE_REPO / "nope")


def test_hard_link_on_a_full_disk_raises_enospc(fake: FakeSystem) -> None:
    fake.put(FAKE_REPO / "a", "x")
    fake.fill_disk()
    with pytest.raises(OSError) as caught:
        system.hard_link(FAKE_REPO / "b", FAKE_REPO / "a")
    assert caught.value.errno == errno.ENOSPC


# ----- Relay.tell / told (T2) ------------------------------------------------------------


def test_tell_writes_the_text_whole(fake: FakeSystem) -> None:
    relay = Relay(RUN)
    told = relay.tell("hi\n")
    assert told == Told("t1", messages_dir(RUN) / "t1.md")
    assert fake.text_of(told.path) == "hi\n"
    assert relay.tell("again").id == "t2"


def test_tell_keeps_the_text_unstripped(fake: FakeSystem) -> None:
    told = Relay(RUN).tell("  \n body \n\n")
    assert fake.text_of(told.path) == "  \n body \n\n"


def test_next_number_follows_the_largest_and_ignores_other_files(fake: FakeSystem) -> None:
    relay = Relay(RUN)
    for name in ("t1.md", "t5.md", "msg-1791761013.md", ".draft-9", "t7.txt", "tx.md"):
        fake.put(relay.messages_dir / name, "x")
    assert relay.tell("new").id == "t6"


def test_told_lists_in_number_order(fake: FakeSystem) -> None:
    relay = Relay(RUN)
    for name in ("t10.md", "t9.md", "t1.md", "msg-1.md", ".draft-3"):
        fake.put(relay.messages_dir / name, "x")
    assert [t.id for t in relay.told()] == ["t1", "t9", "t10"]


def test_told_is_empty_without_a_folder(fake: FakeSystem) -> None:
    assert Relay(RUN / "none").told() == []


def test_a_lost_race_lands_in_the_next_number(fake: FakeSystem, monkeypatch) -> None:
    relay = Relay(RUN)
    fake.put(relay.messages_dir / "t1.md", "first")
    monkeypatch.setattr(NumberedQueue, "_next_number", lambda self: 1)
    told = relay.tell("second")
    assert told.id == "t2" and fake.text_of(told.path) == "second"
    assert fake.text_of(relay.messages_dir / "t1.md") == "first"
    assert [p.name for p in system.list_dir(relay.messages_dir)] == ["t1.md", "t2.md"]


def test_the_draft_is_removed_when_publishing_fails(fake: FakeSystem) -> None:
    relay = Relay(RUN)
    fake.fill_disk()
    with pytest.raises(OSError):
        relay.tell("x")
    assert fake.files.keys().isdisjoint({str(relay.messages_dir / ".draft-4242")})
    assert not any(k.startswith(str(relay.messages_dir)) for k in fake.files)


def test_the_draft_is_removed_after_a_publish_error(fake: FakeSystem, monkeypatch) -> None:
    relay = Relay(RUN)

    def boom(link: Path, target: Path) -> None:
        raise PermissionError("no")

    monkeypatch.setattr(system, "hard_link", boom)
    with pytest.raises(PermissionError):
        relay.tell("x")
    assert list(system.list_dir(relay.messages_dir)) == []


def test_unread_drops_the_delivered_ids(fake: FakeSystem) -> None:
    relay = Relay(RUN)
    for _ in range(3):
        relay.tell("x")
    assert [t.id for t in relay.unread(["t2"])] == ["t1", "t3"]
    assert relay.unread(["t1", "t2", "t3"]) == []
