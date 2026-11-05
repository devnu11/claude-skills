"""s188 end to end on real git: a PO chore on a sprint head is not new work (AC1, AC3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ..conftest import git
from .test_s59_rebase_e2e import World, make_world


@pytest.fixture
def repos(tmp_path: Path) -> World:
    return make_world(tmp_path)


def green_head(world: World) -> str:
    """One sprint commit on the team clone: the head CI judged."""
    return world.commit(world.team, "src/a.txt", "a\n", "sprint one")


def test_ac1_a_po_chore_on_the_green_head_is_only_bookkeeping(repos: World) -> None:
    head = green_head(repos)
    repos.commit(repos.team, ".team/po/handoff.md", "done\n", "chore(team): product-owner step")
    assert repos.upstream().has_only_bookkeeping(head) is True


def test_ac1_a_code_commit_on_the_green_head_is_new_work(repos: World) -> None:
    head = green_head(repos)
    repos.commit(repos.team, "src/b.txt", "b\n", "more work")
    assert repos.upstream().has_only_bookkeeping(head) is False


def test_ac1_a_chore_mixed_with_code_is_new_work(repos: World) -> None:
    head = green_head(repos)
    repos.commit(repos.team, ".team/po/handoff.md", "x\n", "chore(team): product-owner step")
    repos.commit(repos.team, "src/c.txt", "c\n", "code after chore")
    assert repos.upstream().has_only_bookkeeping(head) is False


def test_ac1_no_commits_after_the_head_is_not_a_tail(repos: World) -> None:
    head = green_head(repos)
    assert repos.upstream().has_only_bookkeeping(head) is False


def test_ac3_main_holding_the_head_is_shipped_though_a_chore_sits_on_it(repos: World) -> None:
    head = green_head(repos)
    git(repos.team, "push", "-q", "origin", f"{head}:refs/heads/main")
    git(repos.team, "fetch", "-q", "origin")
    repos.commit(repos.team, ".team/po/handoff.md", "done\n", "chore(team): product-owner step")
    up = repos.upstream()
    assert up.has_only_bookkeeping(head) is True
    assert up.is_in_target(head) is True
