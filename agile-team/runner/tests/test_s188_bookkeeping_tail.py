"""s188: a bookkeeping tail on the sprint's pushed head is not new work at the END boundary."""

from __future__ import annotations

import pytest
from agile_team import boundary as bd
from agile_team import handover
from agile_team.boundary import BoundaryHold, Edge, Stage
from agile_team.ci import Bucket, Check, CiResult, CiVerdict
from agile_team.ci_triage import Job, Step
from agile_team.handover import Trigger as T
from agile_team.upstream import Pr, PrMode, PrState, Rebase, SyncOutcome

from .fake_system import Done, FakeSystem
from .s29_helpers import FakePrs
from .test_boundary_runner import Env, entry, pushes
from .test_s159_boundary_replay import replayed

H = "a1" * 20  # the sha CI judged and the PR holds
C = "c2" * 20  # HEAD: H plus the PO's chore commit
LINK = "https://github.com/o/r/actions/runs/1/job/77"
URL = "https://example/pull/{}"
TAIL_MARK = "\x1e"


@pytest.fixture
def cenv(make_runtime) -> Env:
    env = Env(make_runtime)
    env.prs = FakePrs()
    env.rt.prs = env.prs
    env.rt.state.upstream.team_branch = "main"
    return env


def listing(*commits: tuple[str, ...]) -> str:
    """A ``git log --name-only`` tail: each commit is (sha, parent, *paths)."""
    chunks = []
    for sha, parent, *paths in commits:
        chunks.append(f"{TAIL_MARK}{sha} {parent}\n\n" + "\n".join(paths) + "\n")
    return "".join(chunks)


CHORE = listing((C, H, ".team/po/handoff.md"))
CODE_TAIL = listing((C, H, ".team/po/handoff.md", "agile-team/runner/x.py"))


def script_tail(fake: FakeSystem, tail: str) -> None:
    """HEAD sits above H and ``tail`` is what lies between them."""
    fake.reply(("git", "merge-base", H, "HEAD"), Done(0, H + "\n"))
    fake.reply(("git", "log", "--first-parent", "--name-only"), Done(0, tail))


def calls(env: Env, name: str) -> list[tuple]:
    return [c for c in env.prs.calls if c[0] == name]


def at_tail(cenv: Env, fake: FakeSystem, tail: str, pr: int = 74) -> bd.StackEntry:
    """Sprint 53: END at push-replayed, pushed H, draft PR, HEAD is C."""
    script_tail(fake, tail)
    own = entry(1)
    replayed(cenv, own)
    own.pushed = own.head = H
    own.pr, own.url = pr, URL.format(pr)
    own.ci = CiResult(pr, own.url, H, CiVerdict.GREEN)
    cenv.rt.git.head = lambda: C
    return own


# ---------- AC1: the sprint 53 case ----------


def test_a_chore_tail_pushes_nothing_and_keeps_the_pr_ac1(cenv: Env, fake: FakeSystem) -> None:
    own = at_tail(cenv, fake, CHORE)
    cenv.drive()
    assert pushes(fake) == []
    assert calls(cenv, "create") == [] and calls(cenv, "close") == []
    [(_, number, spec)] = calls(cenv, "edit")
    assert number == 74 and spec.mode is PrMode.READY
    assert own.pr == 74 and own.replays == 0 and own.branch == "team/sprint-1"


def test_a_chore_tail_finishes_the_boundary_with_the_ff_for_h_ac1(
    cenv: Env, fake: FakeSystem
) -> None:
    at_tail(cenv, fake, CHORE)
    cenv.drive()
    up = cenv.rt.state.upstream
    assert cenv.rt.state.boundary is None
    assert f"git push origin {H}:main" in up.report
    final = cenv.events()[-1].data
    assert final["outcome"] == "done"
    assert final["ci"] == "green" and "#74" in final["prs"]


def test_a_chore_tail_is_kept_head_stays_on_c_ac1(cenv: Env, fake: FakeSystem) -> None:
    own = at_tail(cenv, fake, CHORE)
    cenv.drive()
    assert cenv.rt.git.head() == C and own.pushed == H
    assert not [c for c in fake.commands if c.argv[:2] == ("git", "reset")]


def test_a_code_tail_still_pushes_the_replay_branch_ac1(cenv: Env, fake: FakeSystem) -> None:
    own = at_tail(cenv, fake, CODE_TAIL)
    cenv.drive()
    [push] = pushes(fake)
    assert "team/sprint-1-r1" in " ".join(push)
    assert own.branch == "team/sprint-1-r1" and own.replays == 1
    assert len(calls(cenv, "create")) == 1
    [(_, closed, _note)] = calls(cenv, "close")
    assert closed == 74


def test_no_listed_tail_is_work_so_the_replay_branch_is_pushed_ac1(
    cenv: Env, fake: FakeSystem
) -> None:
    script_tail(fake, "")
    own = entry(1)
    replayed(cenv, own)
    own.pushed = own.head = H
    cenv.rt.git.head = lambda: C
    cenv.drive()
    assert len(pushes(fake)) == 1 and own.replays == 1


def test_a_merge_base_that_is_not_h_means_work_ac1(cenv: Env, fake: FakeSystem) -> None:
    at_tail(cenv, fake, CHORE)
    fake.reply(("git", "merge-base", H, "HEAD"), Done(0, "f" * 40 + "\n"))
    cenv.drive()
    assert len(pushes(fake)) == 1


# ---------- AC3: shipped at push-replayed (the target holds H, not C) ----------


def test_a_target_holding_h_closes_as_shipped_with_h_ac3(cenv: Env, fake: FakeSystem) -> None:
    at_tail(cenv, fake, CHORE)
    fake.reply(("git", "merge-base", H, "origin/main"), Done(0, H + "\n"))
    cenv.drive()
    up = cenv.rt.state.upstream
    assert pushes(fake) == [] and calls(cenv, "create") == []
    assert cenv.rt.state.boundary is None and up.closed == 1
    data = cenv.events()[-1].data
    assert data["outcome"] == "done" and data["sha"] == H and "ci" not in data
    assert up.report == bd.SHIPPED_REPORT.format(sprint=1, target="origin/main", sha=H)


def test_the_shipped_close_names_h_on_the_pr_ac3(cenv: Env, fake: FakeSystem) -> None:
    at_tail(cenv, fake, CHORE)
    fake.reply(("git", "merge-base", H, "origin/main"), Done(0, H + "\n"))
    cenv.drive()
    [(_, number, note)] = calls(cenv, "close")
    assert number == 74
    assert note == bd.SHIPPED_PR_NOTE.format(target="origin/main", sha=H)


# ---------- AC3: the sprint 54 case, from the push stage on ----------


def at_push_with_tail(cenv: Env, fake: FakeSystem, state: PrState) -> bd.StackEntry:
    """END at push, entry pushed H with PR #82 in ``state``, HEAD is C above a chore."""
    script_tail(fake, CHORE)
    own = entry(1)
    own.pushed = own.as_is = own.head = H
    own.pr, own.url, own.mode = 82, URL.format(82), PrMode.READY
    cenv.rt.state.upstream.stack = [own]
    cenv.rt.state.upstream.push = bd.Permission.YES
    cenv.rt.git.head = lambda: C
    cenv.prs.prs[own.branch] = Pr(82, own.url, state, False, "main")
    cenv.prs.check_list = [Check("unit", Bucket.PASS, "ci", LINK)]
    cenv.prs.jobs = {LINK: Job("77", H, "unit", (Step("Set up job", "success"),))}
    cenv.rt.upstream.rebase_onto = lambda old: Rebase(SyncOutcome.CURRENT)
    cenv.open(Edge.END, stage=Stage.PUSH)
    return own


def test_the_push_stage_keeps_the_work_head_ac3(cenv: Env, fake: FakeSystem) -> None:
    own = at_push_with_tail(cenv, fake, PrState.MERGED)
    cenv.br.step()
    assert pushes(fake) == []
    assert own.head == own.end == cenv.rt.state.upstream.last_end == H
    assert cenv.rt.state.boundary.stage is Stage.CI


def test_a_merged_pr_checked_on_h_reads_green_not_stale_ac3(cenv: Env, fake: FakeSystem) -> None:
    at_push_with_tail(cenv, fake, PrState.MERGED)
    cenv.br.step()
    cenv.br.step()
    b = cenv.rt.state.boundary
    assert b.stage is Stage.REPLAY and b.hold is None


def test_the_sprint_54_end_closes_shipped_with_no_ci_pending_hold_ac3(
    cenv: Env, fake: FakeSystem
) -> None:
    at_push_with_tail(cenv, fake, PrState.MERGED)
    fake.reply(("git", "merge-base", H, "origin/main"), Done(0, H + "\n"))
    reports = cenv.drive()
    up = cenv.rt.state.upstream
    assert cenv.rt.state.boundary is None and up.closed == 1
    assert pushes(fake) == [] and calls(cenv, "create") == []
    assert all(e.data.get("hold") != BoundaryHold.CI_PENDING.value for e in cenv.events())
    assert cenv.events()[-1].data["sha"] == H
    assert reports[-1]["boundary"]["outcome"] == "done"


# ---------- AC2: ci_green fires once, on the finish ----------


def test_ci_green_fires_once_and_names_the_pr_held_ac2(cenv: Env, fake: FakeSystem) -> None:
    own = at_push_with_tail(cenv, fake, PrState.OPEN)
    reports = cenv.drive()
    raised = [r for r in reports if T.CI_GREEN in handover.triggers(r)]
    [final] = raised
    boundary = final["boundary"]
    assert boundary["outcome"] == "done" and boundary["ci"] == "green"
    assert "#82" in boundary["prs"] and own.pr == 82
    assert calls(cenv, "close") == [] and pushes(fake) == []
    passes = [r for r in reports if r["boundary"]["outcome"] == "pass"]
    assert any(r["boundary"].get("ci") == "green" for r in passes)
