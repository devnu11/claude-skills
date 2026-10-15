"""s151: the sprint end pushes the team branch as built, gates the rebase on its CI, then rebases.

One group per AC. A scripted git, ``FakePrs`` and fake checks; real git is proven in e2e.
"""

from __future__ import annotations

import asyncio
import importlib
import json

import pytest
from agile_team import boundary as bd
from agile_team import ci
from agile_team.boundary import BoundaryHold, Edge, Stage
from agile_team.ci import Bucket, Check, CiResult, CiVerdict
from agile_team.gates import StoryState, StoryStatus
from agile_team.po_tools import Tools
from agile_team.upstream import PrMode, Rebase, SyncOutcome

from .fake_system import FAKE_HEAD, Done, FakeSystem
from .test_boundary_runner import Env, entry, pushes

AS_BUILT = "a5b" + "0" * 37
REBASED = "7eb" + "0" * 37
TARGET = "origin/main"
LINK = "https://github.com/o/r/actions/runs/1/job/77"
RED = [Check("unit", Bucket.FAIL, "ci", LINK)]
GREEN = [Check("unit", Bucket.PASS, "ci", LINK)]
PENDING = [Check("unit", Bucket.PENDING, "ci", "")]


@pytest.fixture
def env(make_runtime) -> Env:
    return Env(make_runtime)


class Rebases:
    """A stand-in for ``Upstream.rebase_onto``: records the calls, gives one result."""

    def __init__(self, result: Rebase) -> None:
        self.result = result
        self.olds: list[str] = []

    def __call__(self, old: str) -> Rebase:
        self.olds.append(old)
        return self.result


def stub_rebase(env: Env, result: Rebase | None = None) -> Rebases:
    stub = Rebases(result or Rebase(SyncOutcome.CURRENT))
    env.rt.upstream.rebase_onto = stub
    return stub


def head_is(env: Env, sha: str) -> None:
    env.rt.git.head = lambda: sha


def built(env: Env, **kw) -> bd.StackEntry:
    """Sprint 1's entry, pushed as built at AS_BUILT with a PR, HEAD there."""
    e = entry(1, pr=5, mode=PrMode.READY, url="https://h/5", **kw)
    e.head = e.end = e.pushed = e.as_is = AS_BUILT
    env.rt.state.upstream.stack = [e]
    env.rt.state.upstream.team_branch = "main"
    env.rt.state.upstream.push = bd.Permission.YES
    head_is(env, AS_BUILT)
    return e


def green_read(e: bd.StackEntry, head: str = AS_BUILT) -> None:
    e.ci = CiResult(5, "https://h/5", head, CiVerdict.GREEN, list(GREEN))


def at(env: Env, stage: Stage, **kw) -> bd.StackEntry:
    e = built(env, **kw)
    env.open(Edge.END, stage=stage)
    return e


def posted(env: Env) -> list[str]:
    return [m.text for m in env.rt.relay.messages()]


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def last(env: Env) -> dict:
    return env.events()[-1].data


# ----- AC1.1 / AC1.2: see test_boundary_runner (push as built, the PR) ----------


def test_ac1_1_the_as_built_push_moves_the_stage_on_to_ci(env: Env, fake: FakeSystem) -> None:
    head_is(env, AS_BUILT)
    e = entry(1)
    env.rt.state.upstream.stack = [e]
    env.rt.state.upstream.push = bd.Permission.YES
    b = env.open(Edge.END, stage=Stage.PUSH)
    env.br.step()
    [argv] = pushes(fake)
    assert argv[-1] == f"{AS_BUILT}:refs/heads/team/sprint-1"
    assert (e.head, e.pushed, e.as_is) == (AS_BUILT, AS_BUILT, AS_BUILT) and b.stage is Stage.CI


def test_ac1_1_the_commit_count_is_taken_against_the_target(env: Env, fake: FakeSystem) -> None:
    head_is(env, AS_BUILT)
    e = entry(1)
    env.rt.state.upstream.stack = [e]
    env.rt.state.upstream.push = bd.Permission.YES
    fake.reply(("rev-list", "--count"), Done(0, "4\n"))
    env.open(Edge.END, stage=Stage.PUSH)
    env.br.step()
    assert e.commits == 4
    [count] = [c for c in fake.commands if "--count" in c.argv]
    assert count.argv[-1] == f"{TARGET}..{AS_BUILT}"


def test_ac1_2_the_pr_is_created_ready_onto_the_target(env: Env) -> None:
    head_is(env, AS_BUILT)
    env.rt.state.upstream.stack = [entry(1)]
    env.rt.state.upstream.push = bd.Permission.YES
    env.open(Edge.END, stage=Stage.PUSH)
    env.br.step()
    [(_, spec)] = [c for c in env.prs.calls if c[0] == "create"]
    assert (spec.branch, spec.base, spec.mode) == ("team/sprint-1", "main", PrMode.READY)


# ----- AC2.1: green CI of the as-built push is the gate ----------------------------


def test_ac2_1_green_advances_to_rebase_and_finishes_nothing(env: Env) -> None:
    e = at(env, Stage.CI)
    env.prs.check_list = GREEN
    b = env.rt.state.boundary
    env.br.step()
    assert b.stage is Stage.REBASE and env.rt.state.boundary is b and b.hold is None
    assert e.ci.verdict is CiVerdict.GREEN and e.ci.head == AS_BUILT
    assert last(env)["outcome"] == "pass" and last(env)["ci"] == "green"
    assert ci.READY_PHRASE not in env.rt.state.upstream.report
    assert not [t for t in posted(env) if ci.READY_PHRASE in t]


def test_ac2_1_pending_holds_and_nothing_is_rebased_until_green(env: Env) -> None:
    at(env, Stage.CI)
    stub = stub_rebase(env)
    env.prs.check_list = PENDING
    env.prs.wait_checks = lambda n, s: False
    env.drive()
    b = env.rt.state.boundary
    assert b.hold is BoundaryHold.CI_PENDING and b.stage is Stage.CI
    assert stub.olds == [] and env.rt.git.head() == AS_BUILT
    env.prs.check_list, env.prs.wait_checks = GREEN, lambda n, s: True
    call(Tools(env.rt).continue_boundary({"note": ""}))
    env.br.step()
    assert b.stage is Stage.REBASE


# ----- AC2.2: red holds, is reported to the PO and the liaison ---------------------


def test_ac2_2_red_holds_and_reports_the_failing_checks_to_the_liaison(env: Env) -> None:
    at(env, Stage.CI)
    stub = stub_rebase(env)
    env.prs.check_list = RED
    env.prs.failed_log = lambda link: "FAILED tests/x.py::test_y"
    [report] = env.drive()
    b = env.rt.state.boundary
    assert b.hold is BoundaryHold.CI_FAILED and b.stage is Stage.CI
    assert report["boundary"]["outcome"] == "held" and report["boundary"]["ci"] == "red"
    [text] = [t for t in posted(env) if "the boundary holds and nothing is rebased" in t]
    assert "unit" in text and "FAILED tests/x.py::test_y" in text and "#5" in text
    assert stub.olds == [] and env.rt.git.head() == AS_BUILT


def test_ac2_2_continue_stays_refused_at_ci_failed(env: Env) -> None:
    at(env, Stage.CI)
    env.prs.check_list = RED
    env.drive()
    seen = len(env.events())
    out = call(Tools(env.rt).continue_boundary({"note": "retry"}))
    assert out["status"] == "refused" and len(env.events()) == seen


def test_ac2_2_no_checks_finish_not_rebased(env: Env) -> None:
    at(env, Stage.CI)
    stub = stub_rebase(env)
    env.prs.check_list = []
    env.drive()
    assert env.rt.state.boundary is None and last(env)["ci"] == "none"
    assert bd.NOT_REBASED.format(target=TARGET) in env.rt.state.upstream.report
    assert stub.olds == []


def test_ac2_2_a_draft_pr_finishes_not_rebased(env: Env) -> None:
    e = at(env, Stage.CI)
    e.mode = PrMode.DRAFT
    stub = stub_rebase(env)
    env.drive()
    assert last(env)["ci"] == "none" and stub.olds == []
    assert env.rt.state.upstream.report.endswith(bd.NOT_REBASED.format(target=TARGET))


# ----- AC3.1: after green, rebase onto the target and remap -------------------------


def test_ac3_1_the_rebase_remaps_the_recorded_hashes(env: Env) -> None:
    e = at(env, Stage.REBASE)
    green_read(e)
    story = env.rt.state.stories["s1"]
    story.commit = "old1" + "0" * 36
    stub = stub_rebase(
        env, Rebase(SyncOutcome.REBASED, sha=REBASED, moved={story.commit: "new1" + "0" * 36})
    )
    b = env.rt.state.boundary
    env.br.step()
    assert stub.olds == [AS_BUILT] and story.commit == "new1" + "0" * 36
    assert last(env)["outcome"] == "rebased" and b.stage is Stage.PUSH_REBASED


def test_ac3_1_as_is_pushed_and_ci_are_never_remapped(env: Env) -> None:
    e = at(env, Stage.REBASE)
    green_read(e)
    stub_rebase(env, Rebase(SyncOutcome.REBASED, sha=REBASED, moved={AS_BUILT: REBASED}))
    env.br.step()
    assert (e.as_is, e.pushed, e.ci.head) == (AS_BUILT, AS_BUILT, AS_BUILT)


def test_s151_ac3_1_rebase_conflict_wakes_devops_and_holds_nothing(env: Env) -> None:
    """Pins s151/AC6.1 (slice 2): a rebase conflict wakes DevOps and sets no hold."""
    e = at(env, Stage.REBASE)
    green_read(e)
    stub_rebase(env, Rebase(SyncOutcome.CONFLICT, files=("a.py",), commit="c" * 40, subject="s"))
    env.br.step()
    b = env.rt.state.boundary
    assert b.hold is None and b.failure.case is bd.FixCase.REBASE_CONFLICT
    assert b.failure.stage is bd.Stage.REBASE and b.sync_from
    assert b.failure.files == ["a.py"]
    assert env.br.due().kind is bd.StepKind.REBASE_FIX


# ----- AC3.2: force-push the rebased branch to the same branch ----------------------


def at_push_rebased(env: Env) -> bd.StackEntry:
    e = at(env, Stage.PUSH_REBASED)
    green_read(e)
    head_is(env, REBASED)
    return e


def test_ac3_2_the_rebased_head_is_pushed_with_the_lease_on_the_as_built_sha(
    env: Env, fake: FakeSystem
) -> None:
    e = at_push_rebased(env)
    fake.reply(("rev-list", "--count"), Done(0, "3\n"))
    b = env.rt.state.boundary
    env.br.step()
    [argv] = pushes(fake)
    assert f"--force-with-lease=refs/heads/team/sprint-1:{AS_BUILT}" in argv
    assert argv[-1] == f"{REBASED}:refs/heads/team/sprint-1"
    assert (e.head, e.pushed, e.as_is, e.commits) == (REBASED, REBASED, AS_BUILT, 3)
    assert b.stage is Stage.CI_REBASED and last(env)["outcome"] == "pushed"
    assert [c for c in env.prs.calls if c[0] in ("create", "edit")] == []


def test_ac3_2_the_liaison_hears_that_the_pr_holds_both_pushes(env: Env) -> None:
    at_push_rebased(env)
    env.br.step()
    [text] = [t for t in posted(env) if "now holds the team branch rebased" in t]
    assert "#5" in text and REBASED[:7] in text and AS_BUILT[:7] in text


def test_ac3_2_a_moved_remote_is_refused_and_held(env: Env, fake: FakeSystem) -> None:
    at_push_rebased(env)
    fake.reply(("git", "push"), Done(1, "! [rejected] (stale info)"))
    b = env.rt.state.boundary
    env.br.step()
    assert b.hold is BoundaryHold.PUSH_REJECTED and b.stage is Stage.PUSH_REBASED
    assert last(env)["reason"] == "! [rejected] (stale info)"


def test_ac3_2_a_current_rebase_pushes_nothing_and_finishes_green(
    env: Env, fake: FakeSystem
) -> None:
    e = at(env, Stage.PUSH_REBASED)
    green_read(e)
    env.br.step()
    assert pushes(fake) == [] and env.rt.state.boundary is None
    assert last(env)["ci"] == "green" and ci.READY_PHRASE in env.rt.state.upstream.report
    assert bd.REBASE_UNCHANGED.format(branch="team/sprint-1", sha=AS_BUILT) in [
        ev.data.get("note") for ev in env.events()
    ]


# ----- AC3.3: the rebased CI is recorded; red is reported and never held -------------


def at_ci_rebased(env: Env, checks: list[Check]) -> bd.StackEntry:
    e = at(env, Stage.CI_REBASED)
    e.head = e.pushed = REBASED
    head_is(env, REBASED)
    env.prs.check_list = checks
    return e


def test_ac3_3_green_finishes_with_the_green_report(env: Env) -> None:
    e = at_ci_rebased(env, GREEN)
    env.drive()
    assert env.rt.state.boundary is None and last(env)["ci"] == "green"
    assert ci.READY_PHRASE in env.rt.state.upstream.report
    assert e.ci.verdict is CiVerdict.GREEN and e.ci.head == REBASED


def test_ac3_3_red_finishes_not_ready_and_does_not_hold(env: Env) -> None:
    e = at_ci_rebased(env, RED)
    [report] = env.drive()
    assert env.rt.state.boundary is None and last(env)["outcome"] == "done"
    assert last(env)["ci"] == "red" and e.ci.verdict is CiVerdict.RED
    assert report["boundary"]["ci"] == "red"
    [text] = [t for t in posted(env) if "NOT ready" in t]
    assert "do not merge it" in text and "unit" in text and AS_BUILT[:7] in text
    assert ci.READY_PHRASE not in env.rt.state.upstream.report
    assert text in env.rt.state.upstream.report


@pytest.mark.parametrize(
    ("checks", "verdict"), [(PENDING, "pending"), ([], "none")], ids=["pending", "none"]
)
def test_ac3_3_pending_and_none_finish_not_ready_without_a_hold(
    env: Env, checks: list[Check], verdict: str
) -> None:
    at_ci_rebased(env, checks)
    env.prs.wait_checks = lambda n, s: checks != PENDING
    env.drive()
    assert env.rt.state.boundary is None and last(env)["ci"] == verdict
    assert ci.READY_PHRASE not in env.rt.state.upstream.report


# ----- AC4.1: the gate in code ----------------------------------------------------


def refused_at_rebase(env: Env, fake: FakeSystem) -> tuple[Rebases, dict]:
    stub = stub_rebase(env)
    b = env.rt.state.boundary
    before = (env.rt.git.head(), len(fake.commands))
    env.br.step()
    assert len(fake.commands) == before[1]  # no fetch, no git call at all
    assert env.rt.git.head() == before[0]
    assert b.stage is Stage.CI and b.hold is BoundaryHold.ERROR
    return stub, last(env)


def test_ac4_1_no_ci_read_refuses_the_rebase(env: Env, fake: FakeSystem) -> None:
    e = at(env, Stage.REBASE)
    e.ci = None
    stub, data = refused_at_rebase(env, fake)
    assert stub.olds == [] and data["outcome"] == "refused"
    assert data["reason"] == bd.REBASE_WAITS.format(
        branch="team/sprint-1", sha=AS_BUILT, verdict="no CI read"
    )


def test_ac4_1_red_refuses_the_rebase(env: Env, fake: FakeSystem) -> None:
    e = at(env, Stage.REBASE)
    e.ci = CiResult(5, "u", AS_BUILT, CiVerdict.RED)
    stub, data = refused_at_rebase(env, fake)
    assert stub.olds == [] and "red" in data["reason"]


def test_ac4_1_green_on_another_sha_refuses_the_rebase(env: Env, fake: FakeSystem) -> None:
    e = at(env, Stage.REBASE)
    green_read(e, head="f" * 40)
    stub, data = refused_at_rebase(env, fake)
    assert stub.olds == [] and data["outcome"] == "refused"


def test_ac4_1_no_entry_refuses_with_no_as_is(env: Env, fake: FakeSystem) -> None:
    env.rt.state.upstream.stack = []
    env.open(Edge.END, stage=Stage.REBASE)
    stub, data = refused_at_rebase(env, fake)
    assert stub.olds == [] and data["reason"] == bd.NO_AS_IS


def test_ac4_1_a_refusal_changes_no_recorded_hash(env: Env) -> None:
    e = at(env, Stage.REBASE)
    e.ci = None
    story = env.rt.state.stories["s1"]
    story.commit = "c1" * 20
    stub_rebase(env, Rebase(SyncOutcome.REBASED, sha=REBASED, moved={story.commit: "x" * 40}))
    env.br.step()
    assert story.commit == "c1" * 20 and env.rt.state.upstream.last_end != REBASED


def test_ac4_1_continue_after_a_refusal_reruns_the_ci_stage(env: Env) -> None:
    e = at(env, Stage.REBASE)
    e.ci = None
    stub_rebase(env)
    env.prs.check_list = GREEN
    env.br.step()
    call(Tools(env.rt).continue_boundary({"note": ""}))
    env.br.step()
    assert env.rt.state.boundary.stage is Stage.REBASE and e.ci.verdict is CiVerdict.GREEN


def test_ac4_1_the_rebase_runs_after_green_at_the_pushed_head(env: Env) -> None:
    e = at(env, Stage.REBASE)
    green_read(e)
    stub = stub_rebase(env)
    env.br.step()
    assert stub.olds == [AS_BUILT]


# ----- AC4.2: the cherry-pick review stage is gone ----------------------------------


def test_ac4_2_no_review_or_restack_stage() -> None:
    values = {s.value for s in Stage}
    assert not {"review", "restack"} & values
    assert not hasattr(Stage, "REVIEW") and not hasattr(Stage, "RESTACK")


@pytest.mark.parametrize("name", ["agile_team.stack", "agile_team.restack"])
def test_ac4_2_the_modules_are_deleted(name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(name)


def test_ac4_2_the_runner_has_no_review_machinery() -> None:
    from agile_team.boundary_runner import BoundaryRunner

    for gone in ("_review", "_restack", "_rebuild", "_push_stack", "_build_one"):
        assert not hasattr(BoundaryRunner, gone)


def test_ac4_2_a_full_end_makes_no_cherry_pick_and_no_review_worktree(
    env: Env, fake: FakeSystem
) -> None:
    first = env.as_built(entry(1))
    first.pushed = first.as_is = ""
    env.rt.state.upstream.stack = [first]
    env.rt.state.upstream.push = bd.Permission.YES
    env.open(Edge.END, stage=Stage.PUSH)
    env.drive()
    argvs = [c.argv for c in fake.commands]
    assert not [a for a in argvs if "cherry-pick" in a or "worktree" in a]
    assert env.rt.state.boundary is None and last(env)["ci"] == "green"


# ----- R2 / R4 / R10 ----------------------------------------------------------------


def test_the_end_sync_with_no_new_commit_runs_no_check(env: Env, fake: FakeSystem) -> None:
    env.rt.state.upstream.last_end = FAKE_HEAD
    env.open(Edge.END)
    env.drive()
    assert env.runner.calls == [] and env.rt.state.upstream.report.startswith("sprint 1 added")


def test_record_ci_bug_text_ends_with_not_rebased(env: Env) -> None:
    at(env, Stage.CI)
    env.prs.check_list = RED
    env.drive()
    env.rt.state.stories["s2"] = StoryState("s2", "Bug", "design", status=StoryStatus.ACTIVE)
    call(Tools(env.rt).record_ci_bug({"story": "s2"}))
    assert env.rt.state.upstream.report.endswith(bd.NOT_REBASED.format(target=TARGET))
    assert env.rt.state.boundary is None


def test_the_old_flow_events_still_render_by_name() -> None:
    assert {"built", "restacked", "rebuild", "merged"}.isdisjoint(
        {o.value for o in bd.BoundaryOutcome}
    )


# ----- the built-in role files describe the new flow ---------------------------------


def role_body(repo, name: str) -> str:
    from agile_team.roles import RoleBook

    return " ".join(RoleBook.for_repo(repo, {}).resolve(name).body.split())


def test_devops_fixes_only_on_the_team_branch(repo) -> None:
    body = role_body(repo, "devops")
    assert "review branch" not in body and "review worktree" not in body


def test_the_po_pushes_the_sprints_branch_and_knows_the_liaison_got_the_checks(repo) -> None:
    body = role_body(repo, "product-owner")
    assert "push the sprint's branch and open its PR" in body
    assert "(sync, checks, push, CI, rebase)" in body
    assert "review branches" not in body
    assert "liaison already got the failing checks" in body
