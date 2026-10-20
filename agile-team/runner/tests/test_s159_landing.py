"""s159 slice 5: the Lander (L3 to L12, E3) on a scripted git, a fake PR service and fake checks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest
from agile_team.boundary import Permission, StackEntry
from agile_team.ci import Bucket, Check
from agile_team.events import EventKind
from agile_team.gates import StoryState, Verdict
from agile_team.halt import HaltKind
from agile_team.story_branches import Landed

from .fake_system import FAKE_REPO, Done, FakeSystem
from .late import Late
from .s29_helpers import FakePrs

landing = Late("landing")
MERGE, HEAD, OLD = "m" * 40, "h" * 40, "0" * 40
BRANCH, LAND = "team/story-s1", "team/story-s1-land"
SPRINT = "team/sprint-1"
RUN = FAKE_REPO / ".team" / "run"


@dataclass
class LandPrs(FakePrs):
    sha_list: list = field(default_factory=lambda: [Check("build", Bucket.PASS, "ci")])

    def sha_checks(self, sha: str) -> list:
        self.calls.append(("sha_checks", sha))
        return self.sha_list

    def close(self, pr: int, note: str) -> None:
        self.calls.append(("close", pr, note))


@dataclass
class Report:
    ok: bool

    @property
    def passed(self) -> bool:
        return self.ok

    def reason(self) -> str:
        return "tests failed: test_x"

    @property
    def failing_ids(self) -> list[str]:
        return []

    def summary(self) -> list:
        return []


def checks(monkeypatch, ok: bool = True) -> None:
    monkeypatch.setattr(landing.fullcheck, "run_checks", lambda *a, **k: Report(ok))


def setup(make_runtime, fake: FakeSystem, push=Permission.YES, prs=None):
    rt = make_runtime(prs=prs if prs is not None else LandPrs())
    rt.state.upstream.team_branch = "agile-team"
    rt.state.upstream.push = push
    entry = StackEntry(1, SPRINT, OLD, OLD, head=HEAD, pushed=HEAD)
    rt.state.upstream.stack = [entry]
    story = StoryState("s1", "Title", "land", sprint=1, branch=BRANCH, base_sha=OLD)
    story.pr = 5
    rt.state.stories["s1"] = story
    rt.state.sprint = 1
    fake.reply(("symbolic-ref",), Done(0, "agile-team\n"))
    fake.reply(("rev-parse", "HEAD"), Done(0, MERGE + "\n"))
    fake.reply(("rev-parse", f"{MERGE}^1"), Done(0, HEAD + "\n"))
    return rt, story, entry


def land(rt, story) -> dict:
    return asyncio.run(landing.Lander(rt, asyncio.Lock()).land(story))


def argvs(fake: FakeSystem) -> list[tuple[str, ...]]:
    return [tuple(c.argv) for c in fake.commands]


def issued(fake: FakeSystem, *words: str) -> list[tuple[str, ...]]:
    return [a for a in argvs(fake) if all(w in a for w in words)]


def ff(fake: FakeSystem) -> list:
    return issued(fake, "merge", "--ff-only")


def gate(report: dict) -> dict:
    return report["gate"]


# ---------- the merge (L4) ----------


def test_the_merge_is_no_ff_in_a_detached_land_worktree_l4(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch, ok=False)
    rt, story, _ = setup(make_runtime, fake)
    land(rt, story)
    add = issued(fake, "worktree", "add")[0]
    assert "--detach" in add and str(RUN / "land") in add and HEAD in add
    [merge] = issued(fake, "merge", "--no-ff")
    assert "--no-edit" in merge and "merge(s1): Title" in merge and BRANCH in merge


def test_the_land_worktree_is_removed_after_the_checks_l7(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch, ok=False)
    rt, story, _ = setup(make_runtime, fake)
    land(rt, story)
    assert issued(fake, "worktree", "remove")


# ---------- red checks (L7) ----------


def test_red_checks_bounce_to_implement_with_the_sprint_untouched_l7(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch, ok=False)
    rt, story, entry = setup(make_runtime, fake)
    out = land(rt, story)
    assert gate(out)["verdict"] == Verdict.BOUNCE and gate(out)["bounce_to"] == "implement"
    assert "test_x" in gate(out)["reason"]
    assert issued(fake, "push") == [] and ff(fake) == []
    assert entry.head == HEAD and story.landed is None


# ---------- local mode (P3) ----------


def test_local_mode_passes_on_green_checks_alone_p3(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake, prs=FakePrs(reason="no gh"))
    out = land(rt, story)
    assert gate(out)["verdict"] == Verdict.PASS and out["land"]["ci"] == "none"
    assert issued(fake, "push") == [] and len(ff(fake)) == 1
    assert entry.head == MERGE and story.landed.merge == MERGE and story.landed.pushed == ""


def test_permission_no_is_local_mode_p3(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake, push=Permission.NO)
    out = land(rt, story)
    assert out["land"]["ci"] == "none" and issued(fake, "push") == []


# ---------- green CI (L8, L9) ----------


def test_green_ci_pushes_landing_then_sprint_then_fast_forwards_l9(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake)
    out = land(rt, story)
    pushed = [" ".join(a) for a in issued(fake, "push")]
    assert (
        f"--force-with-lease=refs/heads/{LAND}:" in pushed[0]
        and f"{MERGE}:refs/heads/{LAND}" in pushed[0]
    )
    assert f"--force-with-lease=refs/heads/{SPRINT}:{HEAD}" in pushed[1]
    assert len(ff(fake)) == 1
    assert (entry.head, entry.pushed) == (MERGE, MERGE)
    assert gate(out)["verdict"] == Verdict.PASS and story.landed.merge == MERGE
    assert out["land"]["ci"] == "green"


def test_the_landing_branch_is_deleted_whatever_the_ci_says_l8(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    land(rt, story)
    deletes = [a for a in issued(fake, "push") if f":refs/heads/{LAND}" in a]
    assert len(deletes) == 1 and f"--force-with-lease=refs/heads/{LAND}:{MERGE}" in deletes[0]


def test_story_landed_event_records_both_parents_l9(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    fake.reply(("rev-list", "--parents"), Done(0, f"{MERGE} {HEAD} {BRANCH}\n"))
    land(rt, story)
    [event] = [e for e in rt.events.events() if e.kind == EventKind.STORY_LANDED]
    assert event.data["merge"] == MERGE and event.data["sprint_branch"] == SPRINT
    assert len(event.data["parents"]) == 2 and event.data["ci"] == "green"


def test_the_first_landing_opens_a_draft_sprint_pr_and_closes_the_story_pr_l9(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake)
    land(rt, story)
    [(_, spec)] = [c for c in rt.prs.calls if c[0] == "create"]
    assert spec.branch == SPRINT and spec.mode.value == "draft"
    assert entry.pr is not None and story.landed.pr == entry.pr
    [(_, number, note)] = [c for c in rt.prs.calls if c[0] == "close"]
    assert number == 5 and MERGE in note


def test_a_later_landing_reuses_the_sprint_pr_without_a_find_l9(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake)
    entry.pr = 9
    land(rt, story)
    assert not [c for c in rt.prs.calls if c[0] in ("create", "find")]
    assert story.landed.pr == 9


# ---------- red or missing CI (L8) ----------


def test_red_ci_bounces_to_implement_and_leaves_the_sprint_l8(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    prs = LandPrs(sha_list=[Check("build", Bucket.FAIL, "ci", link="https://h/runs/1")])
    rt, story, entry = setup(make_runtime, fake, prs=prs)
    out = land(rt, story)
    assert gate(out)["verdict"] == Verdict.BOUNCE and gate(out)["bounce_to"] == "implement"
    assert ff(fake) == [] and entry.head == HEAD and story.landed is None
    assert not [a for a in issued(fake, "push") if f"refs/heads/{SPRINT}" in " ".join(a)]
    assert [a for a in issued(fake, "push") if f":refs/heads/{LAND}" in a]


def test_no_checks_at_the_timeout_holds_as_ci_pending_never_green_l8(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake, prs=LandPrs(sha_list=[]))
    rt.config.gates.ci_timeout_s = 0
    out = land(rt, story)
    assert gate(out)["verdict"] == Verdict.HOLD and ff(fake) == [] and entry.head == HEAD


# ---------- permission (L3) ----------


def test_a_land_pushes_nothing_while_permission_is_unasked_l3(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake, push=Permission.UNASKED)
    out = land(rt, story)
    assert issued(fake, "push") == [] and out.get("status") == "waiting"


# ---------- merge conflicts (L5, L6) ----------


def conflict(fake: FakeSystem, *files: str) -> None:
    fake.reply(("merge", "--no-ff"), Done(1, "CONFLICT (content)"))
    fake.reply(("diff", "--name-only", "--diff-filter=U"), Done(0, "\n".join(files) + "\n"))


def test_a_conflict_bounces_to_land_and_queues_a_developer_rebase_l6(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    conflict(fake, "src/app.py")
    out = land(rt, story)
    assert gate(out)["verdict"] == Verdict.BOUNCE and gate(out)["bounce_to"] == "land"
    assert story.rebase is not None and story.rebase.files == ["src/app.py"]
    assert story.rebase.role.startswith("developer") and story.rebase.onto == HEAD
    assert issued(fake, "merge", "--abort") and issued(fake, "worktree", "remove")
    assert issued(fake, "push") == []


def test_git_owned_files_go_to_devops_o1(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    conflict(fake, "uv.lock")
    land(rt, story)
    assert story.rebase.role == "devops"


def test_a_story_file_clash_holds_for_the_po_l5(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    conflict(fake, ".team/stories/s1.md")
    fake.reply(("merge-file",), Done(1, "<<<<<<<"))
    out = land(rt, story)
    assert gate(out)["verdict"] == Verdict.HOLD
    assert gate(out)["reason"].startswith("story s1: its story file clashes")
    assert story.rebase is None and issued(fake, "worktree", "remove")


def test_a_clean_story_file_merge_completes_the_merge_l5(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    conflict(fake, ".team/stories/s1.md")
    fake.reply(("merge-file", "-p"), Done(0, "merged text\n"))
    out = land(rt, story)
    assert gate(out)["verdict"] == Verdict.PASS
    assert issued(fake, "add") and issued(fake, "commit")


# ---------- a rejected sprint push (L10) ----------


def reject_sprint(fake: FakeSystem) -> None:
    fake.reply(("push", f"{MERGE}:refs/heads/{SPRINT}"), Done(1, "! [rejected]"))


def test_a_remote_that_moved_ahead_is_followed_and_the_land_starts_again_l10(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    reject_sprint(fake)
    ahead = "a" * 40
    fake.reply(("merge-base", "--is-ancestor"), Done(0), Done(0), Done(1), Done(0))
    fake.reply(("ls-remote",), Done(0, f"{ahead}\trefs/heads/{SPRINT}\n"))
    land(rt, story)
    assert len(issued(fake, "merge", "--no-ff")) >= 2
    assert [e for e in rt.events.events() if e.kind == EventKind.STORY_LANDED] == []
    assert any(ahead in a for a in issued(fake, "merge", "--ff-only"))


def test_a_diverged_remote_halts_as_checkout_drift_l10(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    reject_sprint(fake)
    other = "d" * 40
    fake.reply(("ls-remote",), Done(0, f"{other}\trefs/heads/{SPRINT}\n"))
    fake.reply(("merge-base", "--is-ancestor"), Done(0), Done(1))
    land(rt, story)
    assert rt.halted_by is not None and rt.halted_by.kind is HaltKind.CHECKOUT
    assert other in rt.halted_by.reason and HEAD in rt.halted_by.reason
    assert ff(fake) == []


# ---------- resume after the landing push (L11) ----------


def test_resume_waits_on_the_pushed_sha_and_does_not_merge_or_push_again_l11(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    story.landed = Landed(MERGE, pushed=MERGE)
    land(rt, story)
    assert ("sha_checks", MERGE) in rt.prs.calls
    assert issued(fake, "merge", "--no-ff") == []
    assert not [a for a in issued(fake, "push") if f"{MERGE}:refs/heads/{LAND}" in a]


# ---------- the landing texts ----------


@pytest.mark.parametrize(
    "name", ["LAND_STORY_CLASH", "SPRINT_BRANCH_DIVERGED", "LANDED_NOTE", "STORY_PR_BODY"]
)
def test_the_landing_texts_exist(name: str) -> None:
    assert isinstance(getattr(landing, name), str)


# ---------- revert landing (E3) ----------


def test_a_revert_runs_revert_m1_in_the_land_worktree_and_lands_e3(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    story.landed = Landed(MERGE, pushed=MERGE, pr=1)
    asyncio.run(landing.Lander(rt, asyncio.Lock()).land_revert(story, "bad"))
    [revert] = issued(fake, "revert")
    assert "-m" in revert and "1" in revert and MERGE in revert
    assert issued(fake, "worktree", "add")
