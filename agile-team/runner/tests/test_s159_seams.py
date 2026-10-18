"""s159 slices 4, 5, 7: the new OS seam names, ShaWatch (L8), worktree checkout guard (B5, B6),
the new waits rows and Runtime.at (B3)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from agile_team import system
from agile_team.ci import Bucket, Check, CiVerdict
from agile_team.gates import StoryState
from agile_team.git_ops import Git

from .fake_system import FAKE_REPO, Done, FakeSystem
from .late import Late

ci_mod = Late("ci")
co = Late("checkout")
SHA = "a" * 40
RUN = FAKE_REPO / ".team" / "run"


def test_system_names_in_thread_and_temp_dir_s159_c6() -> None:
    assert "in_thread" in system.__all__ and "temp_dir" in system.__all__


def test_in_thread_runs_the_function_and_returns_its_result(fake: FakeSystem) -> None:
    assert asyncio.run(system.in_thread(lambda a, b: a + b, 1, 2)) == 3


def test_temp_dir_is_outside_the_repo(fake: FakeSystem) -> None:
    assert FAKE_REPO not in system.temp_dir().parents


# ---------- ShaWatch (L8) ----------


@dataclass
class ShaPrs:
    reads: list[list[Check]]
    calls: list[str] = field(default_factory=list)

    def sha_checks(self, sha: str) -> list[Check]:
        self.calls.append(sha)
        return self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]

    def job(self, link: str) -> None:
        return None

    def failed_log(self, link: str) -> str:
        return ""


def watch(prs: ShaPrs, limit: float = 600):
    return ci_mod.ShaWatch(prs, limit)  # type: ignore[arg-type]


def test_a_green_landing_head_is_green_with_no_pr(fake: FakeSystem) -> None:
    prs = ShaPrs([[Check("build", Bucket.PASS, "ci")]])
    got = asyncio.run(watch(prs).result(SHA, []))
    assert got.verdict is CiVerdict.GREEN and got.pr == 0 and got.url == "" and got.head == SHA
    assert prs.calls == [SHA]


def test_a_failing_check_on_our_code_is_red(fake: FakeSystem) -> None:
    prs = ShaPrs([[Check("build", Bucket.FAIL, "ci", link="https://h/runs/1")]])
    got = asyncio.run(watch(prs).result(SHA, []))
    assert got.verdict in (CiVerdict.RED, CiVerdict.INFRA, CiVerdict.MAIN)
    assert got.verdict is not CiVerdict.GREEN


def test_no_checks_at_the_deadline_is_never_green(fake: FakeSystem) -> None:
    got = asyncio.run(watch(ShaPrs([[]]), limit=0).result(SHA, []))
    assert got.verdict in (CiVerdict.NONE, CiVerdict.PENDING)


# ---------- worktree drift and accept-checkout --story (B5, B6) ----------


def story_on(branch: str = "team/story-s1", head: str = SHA) -> StoryState:
    return StoryState(id="s1", title="t", step="implement", branch=branch, worktree_head=head)


def test_a_clean_worktree_has_no_drift_b5(fake: FakeSystem) -> None:
    fake.reply(("symbolic-ref",), Done(0, "team/story-s1\n"))
    fake.reply(("rev-parse", "HEAD"), Done(0, SHA + "\n"))
    assert co.check_worktree(Git(FAKE_REPO), story_on()) is None


def test_a_moved_worktree_head_is_drift_b5(fake: FakeSystem) -> None:
    fake.reply(("symbolic-ref",), Done(0, "team/story-s1\n"))
    fake.reply(("rev-parse", "HEAD"), Done(0, "b" * 40 + "\n"))
    assert co.check_worktree(Git(FAKE_REPO), story_on()) is not None


def test_a_switched_branch_is_drift_b5(fake: FakeSystem) -> None:
    fake.reply(("symbolic-ref",), Done(0, "other\n"))
    fake.reply(("rev-parse", "HEAD"), Done(0, SHA + "\n"))
    assert co.check_worktree(Git(FAKE_REPO), story_on()) is not None


def test_apply_accepts_a_queued_worktree_request_b6(make_runtime, fake: FakeSystem) -> None:
    rt = make_runtime()
    rt.state.stories["s1"] = story = story_on(head="c" * 40)
    story.drift, story.hold = ["a.py"], "worktree_drift"
    system.make_dirs(rt.config.run_dir / "checkouts")
    system.write_text(rt.config.run_dir / "checkouts" / "c1.json", '{"story": "s1"}')
    fake.reply(("rev-parse", "HEAD"), Done(0, SHA + "\n"))
    assert co.CheckoutRequests(rt.config).apply(rt) == ["s1"]
    assert story.drift == [] and story.hold is None and story.worktree_head == SHA
