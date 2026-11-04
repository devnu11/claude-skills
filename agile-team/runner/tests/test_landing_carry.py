"""s180 C1 to C6: the pure helpers and the Carrier of ``landing_carry`` on a scripted git."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from agile_team.gates import StoryState, StoryStatus
from agile_team.git_ops import Git, GitError
from agile_team.story_branches import StoryRebase
from agile_team.story_rebase import ListedCommit
from agile_team.upstream import UpstreamError

from .fake_system import FAKE_REPO, Done
from .late import Late

lc = Late("landing_carry")
M, B, H, P = "m" * 40, "b" * 40, "h" * 40, "p" * 40
T = "t" * 40
TREE = FAKE_REPO / ".team" / "run" / "land"
SEP, END = "\x1f", "\x1e"
C1, C2 = ListedCommit("1" * 40, "docs(s2): amend"), ListedCommit("2" * 40, "chore: step")


def span(pushed: str = P):
    return lc.CarrySpan(merge=M, base=B, head=H, pushed=pushed)


def story(sid: str, **kw) -> StoryState:
    return StoryState(sid, "T", "implement", sprint=1, **kw)


# ---------- pure functions ----------


def test_format_commit_is_the_short_sha_and_the_subject() -> None:
    assert lc.format_commit(C1) == "1111111 docs(s2): amend"


def test_the_give_up_text_keeps_its_name_and_value() -> None:
    assert lc.GIVE_UP_MOVED == "sprint head moved"


def test_no_stories_means_no_fork() -> None:
    assert lc.find_forked_story([], (C1,)) == ""


def test_a_base_sha_on_a_carried_commit_is_a_fork() -> None:
    text = lc.find_forked_story([story("s3", base_sha=C2.sha)], (C1, C2))
    assert text == lc.CARRY_FORKED.format(story="s3", commit=lc.format_commit(C2))


def test_a_queued_rebase_onto_a_carried_commit_is_a_fork() -> None:
    forked = story(
        "s3", base_sha="z" * 40, rebase=StoryRebase(C1.sha, B, B, "b", [], "developer-cli")
    )
    assert "s3" in lc.find_forked_story([forked], (C1, C2))


def test_a_finished_story_is_ignored() -> None:
    done = story("s3", base_sha=C1.sha, status=StoryStatus.DONE)
    cancelled = story("s4", base_sha=C1.sha, status=StoryStatus.CANCELLED)
    assert lc.find_forked_story([done, cancelled], (C1,)) == ""


def test_the_first_forked_story_by_numeric_id_is_named() -> None:
    late, early = story("s10", base_sha=C1.sha), story("s9", base_sha=C1.sha)
    assert "s9" in lc.find_forked_story([late, early], (C1,))


def test_an_unrelated_base_is_no_fork() -> None:
    assert lc.find_forked_story([story("s3", base_sha=B)], (C1, C2)) == ""


def test_build_moved_drop_lists_every_commit_oldest_first() -> None:
    carry = lc.Carry(span(), commits=(C1, C2), refusal="why not")
    assert lc.build_moved_drop(carry) == lc.Drop(
        "sprint head moved", ("1111111 docs(s2): amend", "2222222 chore: step"), "why not"
    )


def test_build_moved_drop_with_no_commits_and_no_refusal() -> None:
    assert lc.build_moved_drop(lc.Carry(span())) == lc.Drop("sprint head moved", (), "")


def test_describe_drop_is_the_event_dict() -> None:
    drop = lc.Drop("sprint head moved", ("a b", "c d"), "no")
    assert lc.describe_drop(drop, M) == {
        "merge": M,
        "why": "sprint head moved",
        "moved_by": ["a b", "c d"],
        "refusal": "no",
    }


def test_a_drop_defaults_to_no_commits_and_no_refusal() -> None:
    assert lc.describe_drop(lc.Drop("x"), M)["moved_by"] == []
    assert lc.describe_drop(lc.Drop("x"), M)["refusal"] == ""


def test_a_carry_defaults_to_nothing_carried() -> None:
    carry = lc.Carry(span())
    assert carry.commits == () and carry.tip == "" and carry.moved == {} and carry.refusal == ""


def test_remove_land_tree_removes_the_worktree_then_a_leftover_directory(fake) -> None:
    fake.put(TREE / "f", "x")
    lc.remove_land_tree(Git(FAKE_REPO), TREE)
    assert any(c.argv[1:5] == ("worktree", "remove", "--force", str(TREE)) for c in fake.commands)
    assert not fake.exists(TREE)


def test_remove_land_tree_leaves_nothing_to_remove_when_the_path_is_gone(fake) -> None:
    lc.remove_land_tree(Git(FAKE_REPO), TREE)
    assert not fake.exists(TREE)


# ---------- the Carrier ----------


@dataclass
class StubUpstream:
    """The Upstream surface the Carrier uses, over the scripted git."""

    git: Git
    moves: list = field(default_factory=list)
    fail: Exception | None = None
    advanced: bool = True

    def is_ancestor(self, older: str, newer: str) -> bool:
        return self.git.attempt("merge-base", "--is-ancestor", older, newer)[0] == 0

    def advance_to(self, sha: str) -> bool:
        self.moves.append(("advance_to", sha))
        return self.advanced

    def reset_team_branch(self, old: str, sha: str) -> None:
        self.moves.append(("reset_team_branch", old, sha))
        if self.fail:
            raise self.fail

    def listing(self, spec: str):
        from agile_team import rewrite

        argv = ("log", "--reverse", "--topo-order", "--date=raw", "--format=x", spec)
        return rewrite.parse_listing(self.git.run(*argv))


def carrier(fake):
    up = StubUpstream(Git(FAKE_REPO))
    return lc.Carrier(up, TREE), up


def issued(fake, *words: str) -> list:
    return [c for c in fake.commands if all(w in c.argv for w in words)]


def test_find_refusal_passes_when_every_check_passes(fake) -> None:
    c, _ = carrier(fake)
    assert c.find_refusal(span()) == ""


def test_find_refusal_a_head_that_does_not_descend_from_the_base_is_off_head(fake) -> None:
    c, _ = carrier(fake)
    fake.reply(("merge-base", "--is-ancestor"), Done(1))
    assert c.find_refusal(span()) == lc.CARRY_OFF_HEAD.format(head=H[:12], base=B[:12])


def test_find_refusal_names_the_first_merge_among_the_carried_commits(fake) -> None:
    c, _ = carrier(fake)
    fake.reply(("rev-list", "--merges"), Done(0, f"{C1.sha}\n{C2.sha}\n"))
    fake.reply(("log", "-1", "--format=%s"), Done(0, "Merge x\n"))
    assert c.find_refusal(span()) == lc.CARRY_MERGE.format(commit=f"{C1.sha[:7]} Merge x")
    assert any(C1.sha in cmd.argv for cmd in issued(fake, "log", "-1"))


def test_find_refusal_pushed_past_the_base_is_refused(fake) -> None:
    c, _ = carrier(fake)
    fake.reply(("merge-base", "--is-ancestor"), Done(0), Done(1))
    assert c.find_refusal(span()) == lc.CARRY_PUSHED.format(pushed=P[:12], base=B[:12])


def test_find_refusal_with_nothing_pushed_skips_the_pushed_check(fake) -> None:
    c, _ = carrier(fake)
    fake.reply(("merge-base", "--is-ancestor"), Done(0), Done(1))
    assert c.find_refusal(span(pushed="")) == ""


def test_find_refusal_checks_apply_in_order_off_head_first(fake) -> None:
    c, _ = carrier(fake)
    fake.reply(("merge-base", "--is-ancestor"), Done(1))
    fake.reply(("rev-list", "--merges"), Done(0, f"{C1.sha}\n"))
    assert c.find_refusal(span()) == lc.CARRY_OFF_HEAD.format(head=H[:12], base=B[:12])


def test_find_refusal_a_merge_comes_before_a_pushed_commit(fake) -> None:
    c, _ = carrier(fake)
    fake.reply(("merge-base", "--is-ancestor"), Done(0), Done(1))
    fake.reply(("rev-list", "--merges"), Done(0, f"{C1.sha}\n"))
    fake.reply(("log", "-1", "--format=%s"), Done(0, "m\n"))
    assert "is a merge" in c.find_refusal(span())


def test_list_carried_is_empty_when_base_is_head(fake) -> None:
    c, _ = carrier(fake)
    assert c.list_carried(lc.CarrySpan(M, B, B, "")) == ()
    assert issued(fake, "log") == []


def test_list_carried_reads_the_commits_oldest_first(fake) -> None:
    c, _ = carrier(fake)
    fake.reply(
        ("log", "--reverse", f"{B}..{H}"),
        Done(0, f"{C1.sha}\t{C1.subject}\n{C2.sha}\t{C2.subject}\n"),
    )
    assert c.list_carried(span()) == (C1, C2)


def script_listings(fake) -> None:
    fake.reply(("log", "--topo-order", f"{B}..{H}"), Done(0, f"old1{SEP}S1{END}old2{SEP}S2{END}"))
    fake.reply(("log", "--topo-order", f"{M}..{T}"), Done(0, f"new1{SEP}S1{END}new2{SEP}S2{END}"))
    fake.reply(("rev-parse", "HEAD"), Done(0, T + "\n"))


def test_carry_cherry_picks_the_span_onto_the_merge_in_the_land_tree(fake) -> None:
    c, _ = carrier(fake)
    script_listings(fake)
    carry = c.carry(span(), (C1, C2))
    [add] = issued(fake, "worktree", "add")
    assert add.argv[-3:] == ("--detach", str(TREE), M) or M in add.argv
    [pick] = issued(fake, "cherry-pick")
    assert pick.argv[-2:] == ("--keep-redundant-commits", f"{B}..{H}") and pick.cwd == TREE
    assert carry.tip == T and carry.refusal == "" and carry.commits == (C1, C2)
    assert carry.moved == {"old1": "new1", "old2": "new2"}


def test_carry_removes_the_worktree_after_a_clean_replay(fake) -> None:
    c, _ = carrier(fake)
    script_listings(fake)
    c.carry(span(), (C1,))
    assert issued(fake, "worktree", "remove", "--force")


def conflict(fake) -> None:
    fake.reply(("cherry-pick", "--keep-redundant-commits"), Done(1, "CONFLICT"))
    fake.reply(("diff", "--name-only", "--diff-filter=U"), Done(0, "a.md\nb.md\n"))
    fake.reply(("rev-parse", "CHERRY_PICK_HEAD"), Done(0, C2.sha + "\n"))
    fake.reply(("log", "-1", "--format=%s"), Done(0, C2.subject + "\n"))


def test_a_conflict_aborts_and_refuses_naming_the_commit_and_files(fake) -> None:
    c, _ = carrier(fake)
    conflict(fake)
    carry = c.carry(span(), (C1, C2))
    assert issued(fake, "cherry-pick", "--abort")
    assert "2222222 chore: step" in carry.refusal
    assert "a.md" in carry.refusal and "b.md" in carry.refusal and M[:12] in carry.refusal
    assert carry.commits == (C1, C2) and carry.tip == "" and carry.moved == {}


def test_a_conflict_removes_the_worktree_too(fake) -> None:
    c, _ = carrier(fake)
    conflict(fake)
    c.carry(span(), (C1, C2))
    assert issued(fake, "worktree", "remove", "--force")


def test_move_checkout_with_nothing_carried_fast_forwards_to_the_tip(fake) -> None:
    c, up = carrier(fake)
    carry = lc.Carry(span(), tip=M)
    assert c.move_checkout(carry) is True
    assert up.moves == [("advance_to", M)]


def test_move_checkout_with_nothing_carried_reports_a_failed_fast_forward(fake) -> None:
    c, up = carrier(fake)
    up.advanced = False
    assert c.move_checkout(lc.Carry(span(), tip=M)) is False


def test_move_checkout_with_commits_resets_the_branch_from_head_to_tip(fake) -> None:
    c, up = carrier(fake)
    carry = lc.Carry(span(), commits=(C1,), tip=T)
    assert c.move_checkout(carry) is True
    assert up.moves == [("reset_team_branch", H, T)]


@pytest.mark.parametrize("error", [UpstreamError("moved"), GitError("reset failed")])
def test_move_checkout_returns_false_when_the_reset_fails(fake, error) -> None:
    c, up = carrier(fake)
    up.fail = error
    assert c.move_checkout(lc.Carry(span(), commits=(C1,), tip=T)) is False


def test_the_cherry_pick_argv_is_the_keep_redundant_form() -> None:
    assert lc.CHERRY_PICK_ARGV == ("cherry-pick", "--keep-redundant-commits")


def test_tree_is_a_path() -> None:
    assert isinstance(TREE, Path)
