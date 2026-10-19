"""s163 S1/S3: the switch counts git-cherry '+' lines; a head main has is dropped."""

from __future__ import annotations

from agile_team.config import UpstreamSettings
from agile_team.git_ops import Git
from agile_team.upstream import Upstream

from .fake_system import FAKE_REPO, Done, FakeSystem

HEAD = "c" * 40


def upstream() -> Upstream:
    return Upstream(Git(FAKE_REPO), UpstreamSettings())


def cherry(fake: FakeSystem, out: str) -> None:
    fake.reply(("git", "cherry"), Done(0, out))


def test_count_unpicked_counts_plus_lines(fake: FakeSystem) -> None:
    cherry(fake, f"+ {'a' * 40}\n- {'b' * 40}\n+ {'d' * 40}\n")
    assert upstream().count_unpicked("HEAD") == 2
    [argv] = [c.argv for c in fake.commands if "cherry" in c.argv]
    assert argv[-2:] == [upstream().target, "HEAD"]


def test_count_unpicked_of_all_rebased_copies_is_zero(fake: FakeSystem) -> None:
    cherry(fake, f"- {'a' * 40}\n- {'b' * 40}\n")
    assert upstream().count_unpicked("HEAD") == 0


def test_count_unpicked_of_nothing_is_zero(fake: FakeSystem) -> None:
    cherry(fake, "")
    assert upstream().count_unpicked(HEAD) == 0


def test_a_contained_head_is_contained(fake: FakeSystem) -> None:
    fake.reply(("git", "merge-base", "--is-ancestor"), Done(0))
    assert upstream().why_in_target(HEAD) == "contained"


def test_a_rebased_head_is_patch_equivalent(fake: FakeSystem) -> None:
    fake.reply(("git", "merge-base", "--is-ancestor"), Done(1))
    cherry(fake, f"- {'a' * 40}\n")
    assert upstream().why_in_target(HEAD) == "patch-equivalent"


def test_a_head_with_a_commit_main_lacks_is_not_in_target(fake: FakeSystem) -> None:
    fake.reply(("git", "merge-base", "--is-ancestor"), Done(1))
    cherry(fake, f"- {'a' * 40}\n+ {'b' * 40}\n")
    assert upstream().why_in_target(HEAD) is None
