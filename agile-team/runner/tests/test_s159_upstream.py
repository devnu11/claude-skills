"""s159: push safety (P2, P5, B7), Prs.close and sha_checks."""

from __future__ import annotations

import pytest
from agile_team import upstream as up
from agile_team.config import UpstreamSettings
from agile_team.git_ops import Git
from agile_team.upstream import Lease, NoPrs, Upstream, UpstreamError

from .fake_system import FAKE_REPO, Done, FakeSystem

OLD, NEW = "a" * 40, "b" * 40
STORY = "team/story-s1"
LAND = "team/story-s1-land"


def upstream_for(**kw) -> Upstream:
    return Upstream(Git(FAKE_REPO), UpstreamSettings(**kw))


def issued(fake: FakeSystem, *words: str) -> list[tuple[str, ...]]:
    found = []
    for command in fake.commands:
        rest = iter(command.argv)
        if all(word in rest for word in words):
            found.append(tuple(command.argv))
    return found


def on_team(fake: FakeSystem) -> None:
    fake.reply(("git", "symbolic-ref"), Done(0, "agile-team\n"))


def test_a_descendant_push_carries_the_lease(fake: FakeSystem) -> None:
    """s159 rule: a descendant push carries the lease."""
    on_team(fake)
    assert upstream_for().push(Lease(STORY, OLD, NEW)) is None
    [argv] = issued(fake, "push")
    assert f"--force-with-lease=refs/heads/{STORY}:{OLD}" in argv
    assert any("is-ancestor" in c.argv for c in fake.commands)


def test_a_non_descendant_is_refused_before_any_push(fake: FakeSystem) -> None:
    """s159 rule: a non descendant is refused before any push."""
    on_team(fake)
    fake.reply(("merge-base", "--is-ancestor"), Done(1))
    out = upstream_for().push(Lease(STORY, OLD, NEW))
    assert out == up.NOT_FAST_FORWARD.format(sha=NEW, branch=STORY, expect=OLD)
    assert not issued(fake, "push")


def test_a_new_branch_skips_the_ancestor_check(fake: FakeSystem) -> None:
    """s159 rule: a new branch skips the ancestor check."""
    on_team(fake)
    assert upstream_for().push(Lease(STORY, "", NEW)) is None
    assert not any("is-ancestor" in c.argv for c in fake.commands)


def test_guard_accepts_both_prefixes(fake: FakeSystem) -> None:
    """s159 rule: guard accepts both prefixes."""
    on_team(fake)
    assert upstream_for().push(Lease("team/sprint-1", "", NEW)) is None
    assert upstream_for().push(Lease(STORY, "", NEW)) is None


@pytest.mark.parametrize("branch", ["main", "agile-team", "feature/x", "team/storys-1"])
def test_guard_refuses_others(fake: FakeSystem, branch: str) -> None:
    """s159 rule: guard refuses others."""
    on_team(fake)
    with pytest.raises(UpstreamError, match="refusing to push"):
        upstream_for().push(Lease(branch, "", NEW))


def test_refusal_text_names_both_prefixes() -> None:
    """s159 rule: refusal text names both prefixes."""
    text = up.REFUSED_PUSH.format(branch="x", prefix="team/sprint-", story_prefix="team/story-")
    assert "team/sprint-*" in text and "team/story-*" in text


def test_delete_sends_a_leased_delete_and_skips_ancestry(fake: FakeSystem) -> None:
    """s159 rule: delete sends a leased delete and skips ancestry."""
    on_team(fake)
    assert upstream_for().delete(Lease(LAND, NEW, "")) is None
    [argv] = issued(fake, "push")
    assert f":refs/heads/{LAND}" in argv
    assert f"--force-with-lease=refs/heads/{LAND}:{NEW}" in argv
    assert not any("is-ancestor" in c.argv for c in fake.commands)


@pytest.mark.parametrize("branch", [STORY, "team/sprint-1", "main", "team/story-s1-land-x"])
def test_delete_refuses_anything_but_landing_branches(fake: FakeSystem, branch: str) -> None:
    """s159 rule: delete refuses anything but landing branches."""
    on_team(fake)
    out = upstream_for().delete(Lease(branch, NEW, ""))
    assert out == up.REFUSED_DELETE.format(branch=branch, story_prefix="team/story-")
    assert not issued(fake, "push")


def test_no_prs_cannot_close_or_read_shas() -> None:
    """s159 rule: no prs cannot close or read shas."""
    prs = NoPrs("no gh")
    with pytest.raises(UpstreamError, match="no gh"):
        prs.close(1, "note")
    with pytest.raises(UpstreamError, match="no gh"):
        prs.sha_checks(NEW)


def test_texts() -> None:
    """s159 rule: texts."""
    assert up.NOT_FAST_FORWARD.startswith("refusing to push")
    assert up.REFUSED_DELETE.startswith("refusing to delete")
