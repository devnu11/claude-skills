"""s134: ``NumberedQueue`` itself, on the fake system (ADR-0069)."""

from pathlib import Path

import pytest
from agile_team import system
from agile_team.numbered_queue import Entry, NumberedQueue

from .fake_system import FAKE_REPO, FakeSystem

FOLDER = FAKE_REPO / "run" / "q"
QUEUE = NumberedQueue(FOLDER, "t", ".md")


def names() -> list[str]:
    return [p.name for p in system.list_dir(FOLDER)]


def test_publish_writes_whole_and_numbers_from_one(fake: FakeSystem) -> None:
    assert QUEUE.publish("a") == Entry("t1", FOLDER / "t1.md")
    assert fake.text_of(FOLDER / "t1.md") == "a"
    assert QUEUE.publish("b").id == "t2"


def test_publish_keeps_text_byte_for_byte(fake: FakeSystem) -> None:
    entry = QUEUE.publish("  \n x \n\n")
    assert fake.text_of(entry.path) == "  \n x \n\n"


def test_first_number_follows_the_largest_and_ignores_other_names(fake: FakeSystem) -> None:
    for name in ("t1.md", "t5.md", ".draft-9", "t7.txt", "tx.md", "r9.md"):
        fake.put(FOLDER / name, "x")
    assert QUEUE.publish("n").id == "t6"


def test_a_taken_number_is_skipped(fake: FakeSystem, monkeypatch) -> None:
    tried: list[str] = []
    real = system.hard_link

    def link(dest: Path, src: Path) -> None:
        tried.append(dest.name)
        if dest.name == "t2.md":
            raise FileExistsError(str(dest))
        real(dest, src)

    fake.put(FOLDER / "t1.md", "x")
    monkeypatch.setattr(system, "hard_link", link)
    assert QUEUE.publish("n").id == "t3"
    assert tried == ["t2.md", "t3.md"]


def test_an_existing_file_at_a_taken_number_is_kept(fake: FakeSystem, monkeypatch) -> None:
    fake.put(FOLDER / "t1.md", "first")
    monkeypatch.setattr(NumberedQueue, "_next_number", lambda self: 1)
    assert QUEUE.publish("second").id == "t2"
    assert fake.text_of(FOLDER / "t1.md") == "first"


def test_no_draft_is_left_after_publishing(fake: FakeSystem) -> None:
    QUEUE.publish("a")
    QUEUE.publish("b")
    assert names() == ["t1.md", "t2.md"]


def test_no_draft_is_left_when_the_draft_cannot_be_written(fake: FakeSystem) -> None:
    system.make_dirs(FOLDER)
    fake.fill_disk()
    with pytest.raises(OSError):
        QUEUE.publish("x")
    assert names() == []


def test_no_draft_is_left_when_linking_fails_otherwise(fake: FakeSystem, monkeypatch) -> None:
    def link(dest: Path, src: Path) -> None:
        raise PermissionError("no")

    monkeypatch.setattr(system, "hard_link", link)
    with pytest.raises(PermissionError):
        QUEUE.publish("x")
    assert names() == []


def test_entries_are_in_number_order_with_paths_on_disk(fake: FakeSystem) -> None:
    for name in ("t10.md", "t9.md", "t01.md", "msg-1.md", ".draft-3"):
        fake.put(FOLDER / name, "x")
    assert QUEUE.entries() == [
        Entry("t1", FOLDER / "t01.md"),
        Entry("t9", FOLDER / "t9.md"),
        Entry("t10", FOLDER / "t10.md"),
    ]


def test_entries_are_empty_without_a_folder_and_publish_creates_it(fake: FakeSystem) -> None:
    assert QUEUE.entries() == []
    QUEUE.publish("x")
    assert [e.id for e in QUEUE.entries()] == ["t1"]


def test_prefix_and_suffix_are_literal(fake: FakeSystem) -> None:
    queue = NumberedQueue(FOLDER, "f", ".json")
    fake.put(FOLDER / "f1xjson", "x")
    fake.put(FOLDER / "f2.json", "x")
    assert [e.id for e in queue.entries()] == ["f2"]
