"""s159 slice 5: StoryPusher and StoryCiPoll (P4, SC1), story_rebase (S2, S3, O1)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from agile_team.boundary import Permission, PrMode, StackEntry
from agile_team.ci import Bucket, Check
from agile_team.git_ops import Git
from agile_team.owners import Owners, Writer
from agile_team.story_branches import StoryCi, StoryRebase

from .fake_system import FAKE_REPO, Done, FakeSystem
from .late import Late
from .s29_helpers import FakePrs

story_ci = Late("story_ci")
story_rebase = Late("story_rebase")
HEAD, OLD = "b" * 40, "a" * 40


@dataclass
class ShaPrs(FakePrs):
    sha_list: list = field(default_factory=lambda: [Check("build", Bucket.PASS, "ci")])

    def sha_checks(self, sha: str) -> list:
        self.calls.append(("sha_checks", sha))
        return self.sha_list

    def close(self, pr: int, note: str) -> None:
        self.calls.append(("close", pr, note))


def pushes(fake: FakeSystem) -> list[tuple[str, ...]]:
    return [tuple(c.argv) for c in fake.commands if "push" in c.argv]


def ready(make_runtime, fake: FakeSystem, push: Permission = Permission.YES):
    rt = make_runtime(prs=ShaPrs())
    rt.state.upstream.push = push
    rt.state.upstream.team_branch = "agile-team"
    rt.state.upstream.stack = [StackEntry(1, "team/sprint-1", OLD, OLD, head=OLD, pushed=OLD)]
    fake.reply(("symbolic-ref",), Done(0, "agile-team\n"))
    fake.reply(("rev-parse", "HEAD"), Done(0, HEAD + "\n"))
    story = rt.state.stories["s1"] = _story()
    return rt, story


def _story():
    from agile_team.gates import StoryState

    return StoryState(
        id="s1", title="t", step="implement", branch="team/story-s1", worktree_head=HEAD
    )


# ---------- StoryPusher (P4) ----------


def test_a_committing_step_pushes_the_story_branch_with_its_lease_p4(make_runtime, fake) -> None:
    rt, story = ready(make_runtime, fake)
    assert story_ci.StoryPusher(rt).after_step(story) is None
    [argv] = pushes(fake)
    assert "--force-with-lease=refs/heads/team/story-s1:" in " ".join(argv)
    assert story.pushed == HEAD


def test_a_draft_pr_targets_the_sprint_branch_p4(make_runtime, fake) -> None:
    rt, story = ready(make_runtime, fake)
    story_ci.StoryPusher(rt).after_step(story)
    [(_, spec)] = [c for c in rt.prs.calls if c[0] == "create"]
    assert spec.branch == "team/story-s1" and spec.base == "team/sprint-1"
    assert spec.mode is PrMode.DRAFT and spec.title.startswith("s1: ")
    assert story.pr is not None


def test_nothing_is_pushed_while_permission_is_unasked_p1(make_runtime, fake) -> None:
    rt, story = ready(make_runtime, fake, Permission.UNASKED)
    assert story_ci.StoryPusher(rt).after_step(story) is None
    assert pushes(fake) == [] and story.pushed == "" and story.pr is None


def test_nothing_is_pushed_when_permission_is_no_p3(make_runtime, fake) -> None:
    rt, story = ready(make_runtime, fake, Permission.NO)
    story_ci.StoryPusher(rt).after_step(story)
    assert pushes(fake) == []


def test_pushed_is_saved_only_after_success_p4(make_runtime, fake) -> None:
    rt, story = ready(make_runtime, fake)
    story.pushed = OLD
    fake.reply(("merge-base", "--is-ancestor"), Done(1))
    out = story_ci.StoryPusher(rt).after_step(story)
    assert out and story.pushed == OLD and pushes(fake) == []


def test_an_unchanged_head_pushes_nothing_p4(make_runtime, fake) -> None:
    rt, story = ready(make_runtime, fake)
    story.pushed = HEAD
    story_ci.StoryPusher(rt).after_step(story)
    assert pushes(fake) == []


# ---------- StoryCiPoll (SC1, SC2) ----------


def poller(make_runtime, fake):
    rt, story = ready(make_runtime, fake)
    story.pushed = HEAD
    return rt, story, story_ci.StoryCiPoll(rt)


def test_a_settled_green_result_is_recorded_sc1(make_runtime, fake) -> None:
    _, story, poll = poller(make_runtime, fake)
    got = poll.poll(story, 1000.0)
    assert got == StoryCi(HEAD, "green", "pr") and story.ci == got


def test_the_same_result_is_not_recorded_twice_sc1(make_runtime, fake) -> None:
    _, story, poll = poller(make_runtime, fake)
    poll.poll(story, 1000.0)
    assert poll.poll(story, 1000.0 + story_ci.STORY_CI_POLL_S) is None


def test_polls_are_at_least_sixty_seconds_apart_sc1(make_runtime, fake) -> None:
    rt, story, poll = poller(make_runtime, fake)
    poll.poll(story, 1000.0)
    calls = len(rt.prs.calls)
    story.ci = None
    assert poll.poll(story, 1030.0) is None and len(rt.prs.calls) == calls


def test_a_story_not_yet_due_never_asks_whether_gh_works_sc1(make_runtime, fake) -> None:
    """Rate limit (2026-10-20): the time gate comes before ``prs.missing()``."""
    rt, story, poll = poller(make_runtime, fake)
    asked: list[str] = []
    rt.prs.missing = lambda: asked.append("missing")
    poll.claim_due(story, 1000.0)
    for second in range(1, story_ci.STORY_CI_POLL_S):
        assert poll.claim_due(story, 1000.0 + second) is False
    assert asked == ["missing"]


def test_the_poll_interval_is_sixty_seconds_sc1() -> None:
    assert story_ci.STORY_CI_POLL_S == 60


def test_unsettled_checks_record_nothing_sc1(make_runtime, fake) -> None:
    rt, story, poll = poller(make_runtime, fake)
    rt.prs.sha_list = [Check("build", Bucket.PENDING, "ci")]
    assert poll.poll(story, 1000.0) is None and story.ci is None


def test_no_pushed_head_means_no_poll_sc1(make_runtime, fake) -> None:
    rt, story, poll = poller(make_runtime, fake)
    story.pushed = ""
    assert poll.poll(story, 1000.0) is None and rt.prs.calls == []


def test_a_red_story_ci_holds_nothing_sc2(make_runtime, fake) -> None:
    rt, story, poll = poller(make_runtime, fake)
    rt.prs.sha_list = [Check("build", Bucket.FAIL, "ci", link="https://h/runs/1")]
    got = poll.poll(story, 1000.0)
    assert got is not None and got.verdict != "green"
    assert story.hold is None and story.po_hold is None


# ---------- story_rebase (O1, S2, S3) ----------

OWNERS = Owners(
    (
        Writer("implement", "developer", ("src/**", "tests/**")),
        Writer("ops-review", "devops", (".github/**", "pyproject.toml", "uv.lock")),
    ),
    "implement",
)


@pytest.mark.parametrize(
    ("files", "devops"),
    [
        ([".github/workflows/ci.yml"], True),
        (["uv.lock", "pyproject.toml"], True),
        (["unowned/thing.cfg"], True),
        (["src/app.py"], False),
        ([".github/workflows/ci.yml", "src/app.py"], False),
    ],
)
def test_devops_resolves_only_git_owned_files_o1(files, devops) -> None:
    assert story_rebase.needs_devops(files, OWNERS) is devops


REBASE = StoryRebase(
    onto="c" * 40,
    base=OLD,
    old="team/story-s1",
    branch="team/story-s1-r1",
    files=["a.py"],
    role="developer",
)


def argvs(fake: FakeSystem) -> list[tuple[str, ...]]:
    return [tuple(c.argv) for c in fake.commands]


def test_prepare_branches_then_rebases_onto_the_new_base_s2(fake: FakeSystem) -> None:
    fake.reply(("rebase", "--onto"), Done(1, "CONFLICT"))
    story_rebase.prepare(Git(FAKE_REPO), REBASE)
    got = argvs(fake)
    branch = next(a for a in got if "checkout" in a and "-b" in a and REBASE.branch in a)
    rebase = next(a for a in got if "rebase" in a and "--onto" in a)
    assert got.index(branch) < got.index(rebase)
    assert REBASE.onto in rebase and REBASE.base in rebase


def test_prepare_on_the_rebase_branch_does_nothing_ac2_13(fake: FakeSystem) -> None:
    """AC2.13: re-entering with the rebase branch checked out starts nothing again."""
    fake.reply(("symbolic-ref",), Done(0, REBASE.branch + "\n"))
    story_rebase.prepare(Git(FAKE_REPO), REBASE)
    assert not [a for a in argvs(fake) if "checkout" in a or "rebase" in a]


def clean(fake: FakeSystem) -> None:
    fake.reply(("symbolic-ref",), Done(0, REBASE.branch + "\n"))
    fake.reply(("status", "--porcelain"), Done(0, ""))
    fake.reply(("merge-base", "--is-ancestor"), Done(0))
    fake.reply(("log",), Done(0, "one\ntwo\n"))


def test_a_finished_clean_rebase_has_no_refusal_s3(fake: FakeSystem) -> None:
    clean(fake)
    assert story_rebase.refusal(Git(FAKE_REPO), REBASE) is None


def test_a_dirty_tree_is_refused_s3(fake: FakeSystem) -> None:
    clean(fake)
    fake.reply(("status", "--porcelain"), Done(0, " M a.py\n"))
    assert story_rebase.refusal(Git(FAKE_REPO), REBASE)


def test_head_off_the_rebase_branch_is_refused_s3(fake: FakeSystem) -> None:
    clean(fake)
    fake.reply(("symbolic-ref",), Done(0, "elsewhere\n"))
    assert REBASE.branch in story_rebase.refusal(Git(FAKE_REPO), REBASE)


def test_head_not_descending_from_onto_is_refused_s3(fake: FakeSystem) -> None:
    clean(fake)
    fake.reply(("merge-base", "--is-ancestor"), Done(1))
    assert story_rebase.refusal(Git(FAKE_REPO), REBASE)


def test_changed_commits_are_refused_s3(fake: FakeSystem) -> None:
    clean(fake)
    fake.reply(("log", f"{REBASE.base}..{REBASE.old}"), Done(0, "one\ntwo\nthree\n"))
    fake.reply(("log", f"{REBASE.onto}..HEAD"), Done(0, "one\ntwo\n"))
    assert story_rebase.refusal(Git(FAKE_REPO), REBASE)
