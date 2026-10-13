"""s108: the sprint end in four steps (push, rebase, restack, ci), every PR ready, big-PR notes."""

from __future__ import annotations

import pytest
from agile_team import boundary as bd
from agile_team.boundary import BoundaryHold, Edge, Stage
from agile_team.ci import Bucket, Check
from agile_team.upstream import Pr, PrMode, PrState, Rebase, SyncOutcome

from .fake_system import Done, FakeSystem
from .test_boundary_runner import NEW, Env, entry, pushes
from .test_s108_restack import H1, H2, H3, N1, N2, lines, same_tree

GREEN = [Check("build", Bucket.PASS, "ci", "")]


@pytest.fixture
def env(make_runtime) -> Env:
    return Env(make_runtime)


def open_pr(env: Env, e: bd.StackEntry, base: str, state: PrState = PrState.OPEN) -> None:
    e.pr, e.url, e.base, e.mode, e.pushed = (
        e.sprint,
        f"https://h/{e.sprint}",
        base,
        PrMode.READY,
        e.head,
    )
    env.prs.prs[e.branch] = Pr(e.sprint, e.url, state, False, base)


PIN = "c" * 40  # the REBASE stage pins sync_from with the first rev-parse HEAD (M8, s59 R2)


def at_stage(
    env: Env, stage: Stage, *heads: str, merged: int = 1, push: bd.Permission = bd.Permission.YES
):
    """A stack of ready PRs (sprints 9..) at ``stage``; the first ``merged`` are merged."""
    stack = [entry(9 + i) for i in range(len(heads))]
    for i, (e, head) in enumerate(zip(stack, heads, strict=True)):
        e.head, e.checked = head, head
        below = stack[i - 1].branch if i else "main"
        open_pr(env, e, below, PrState.MERGED if i < merged else PrState.OPEN)
    env.rt.state.upstream.stack = stack
    env.rt.state.upstream.team_branch = "main"
    env.rt.state.upstream.push = push
    env.prs.check_list = GREEN
    env.rt.state.sprint = 8 + len(heads)
    return env.open(Edge.END, stage=stage), stack


def at_ci(env: Env, *heads: str, merged: int = 1):
    """At the ci stage."""
    return at_stage(env, Stage.CI, *heads, merged=merged)


def at_restack(env: Env, *heads: str, merged: int = 1, push: bd.Permission = bd.Permission.YES):
    """At the restack stage."""
    return at_stage(env, Stage.RESTACK, *heads, merged=merged, push=push)


def fresh_stack(env: Env, count: int, stage: Stage = Stage.RESTACK) -> bd.Boundary:
    """``count`` entries with no PR yet; the last is the sprint's own."""
    env.rt.state.upstream.push = bd.Permission.YES
    env.rt.state.upstream.stack = [entry(i + 1) for i in range(count)]
    env.rt.state.upstream.team_branch = "main"
    env.rt.state.sprint = count
    return env.open(Edge.END, stage=stage)


def script_noop(fake: FakeSystem, count: int, commits: str = "2\n") -> None:
    """Every entry rebases to its own head (main unmoved): same tree, ``commits`` left."""
    fake.reply(("git", "rev-parse", "HEAD"), *[lines(NEW)] * count)
    same_tree(fake, NEW, "")
    fake.reply(("rev-list", "--count"), Done(0, commits))


def script_fast_path(fake: FakeSystem, *new: str) -> None:
    """Rebase gives ``new`` heads in turn; each has the same tree as before."""
    fake.reply(("git", "rev-parse", "HEAD"), *[lines(sha) for sha in new])
    for sha in new:
        same_tree(fake, sha, "")
    fake.reply(("rev-list", "--count"), Done(0, "2\n"))


def pr_calls(env: Env, verb: str) -> list:
    return [c for c in env.prs.calls if c[0] == verb]


def updates(env: Env) -> list[str]:
    return [m.text for m in env.rt.relay.messages() if m.kind == "update"]


# ----- M1: every PR ready (created at restack) ----------------------------------


def test_every_created_pr_is_ready_and_based_on_the_one_below(env: Env, fake: FakeSystem) -> None:
    fresh_stack(env, 3)
    script_noop(fake, 3)
    env.br.step()
    creates = [spec for _, spec in pr_calls(env, "create")]
    assert [s.mode for s in creates] == [PrMode.READY] * 3
    assert [s.base for s in creates] == ["main", "team/sprint-1", "team/sprint-2"]
    assert "Stacked on team/sprint-1 (#1)" in creates[1].body


def test_an_open_draft_is_made_ready_by_the_restack(env: Env, fake: FakeSystem) -> None:
    fresh_stack(env, 1)
    script_noop(fake, 1)
    env.prs.prs["team/sprint-1"] = Pr(4, "u", PrState.OPEN, True, "main")
    env.br.step()
    [(_, number, spec)] = pr_calls(env, "edit")
    assert number == 4 and spec.mode is PrMode.READY
    assert env.prs.prs["team/sprint-1"].draft is False


def test_the_pushed_report_names_ci_on_every_pr_and_goes_to_ci(env: Env, fake: FakeSystem) -> None:
    b = fresh_stack(env, 2)
    script_noop(fake, 2)
    env.br.step()
    [text] = [t for t in updates(env) if "are pushed" in t]
    assert "waits for CI on every PR of the stack" in text
    assert b.stage is Stage.CI


# ----- M17: commits and big PR notes -------------------------------------------


def test_commits_are_counted_against_the_target_then_the_branch_below(
    env: Env, fake: FakeSystem
) -> None:
    fresh_stack(env, 2)
    script_noop(fake, 2, commits="4\n")
    env.br.step()
    e1, e2 = env.rt.state.upstream.stack
    assert (e1.commits, e2.commits) == (4, 4)
    spans = [c.argv[-1] for c in fake.commands if "--count" in c.argv]
    assert f"origin/main..{e1.head}" in spans and f"{e1.head}..{e2.head}" in spans


def test_the_pushed_report_gets_a_note_for_a_big_pr(env: Env, fake: FakeSystem) -> None:
    fresh_stack(env, 1)
    script_noop(fake, 1, commits="101\n")
    env.br.step()
    [text] = [t for t in updates(env) if "are pushed" in t]
    assert text.endswith("git fetch origin && git push origin origin/team/sprint-1:main")
    assert "\nPR #1 (team/sprint-1) has 101 commits" in text


def test_a_green_report_gets_the_note(env: Env) -> None:
    _b, [e] = at_ci(env, H1, merged=0)
    e.commits = 120
    env.br.step()
    up = env.rt.state.upstream
    assert up.report.endswith("origin/team/sprint-9:main") and "has 120 commits" in up.report


def test_a_none_report_gets_the_note(env: Env) -> None:
    _b, [e] = at_ci(env, H1, merged=0)
    env.prs.check_list = []
    e.commits = 120
    env.br.step()
    assert env.rt.state.upstream.report.endswith("origin/team/sprint-9:main")


def test_small_prs_add_no_note(env: Env) -> None:
    _b, [e] = at_ci(env, H1, merged=0)
    e.commits = 100
    env.br.step()
    assert "commits, more than" not in env.rt.state.upstream.report


# ----- M7: PUSH pushes the sprint's own branch only ------------------------------


def test_push_pushes_only_the_sprints_own_branch_and_no_pr_call(env: Env, fake: FakeSystem) -> None:
    b = fresh_stack(env, 3, Stage.PUSH)
    env.br.step()
    [argv] = pushes(fake)
    assert argv[-1] == "refs/heads/team/sprint-3:refs/heads/team/sprint-3"
    assert "--force-with-lease=refs/heads/team/sprint-3:" in " ".join(argv)
    assert env.prs.calls == [] and b.stage is Stage.REBASE
    assert env.outcomes() == ["pass"]


def test_push_skips_a_branch_already_pushed(env: Env, fake: FakeSystem) -> None:
    b = fresh_stack(env, 1, Stage.PUSH)
    e = env.rt.state.upstream.stack[0]
    e.pushed = e.head
    env.br.step()
    assert pushes(fake) == [] and b.stage is Stage.REBASE


def test_push_with_an_empty_stack_passes_and_still_runs_the_rebase(env: Env) -> None:
    b = fresh_stack(env, 0, Stage.PUSH)
    env.br.step()
    assert env.events()[-1].data["note"] == "no review branch to push"
    assert b.stage is Stage.REBASE and env.rt.state.boundary is b


def test_push_without_permission_is_local_and_still_rebases(env: Env, fake: FakeSystem) -> None:
    b = fresh_stack(env, 1, Stage.PUSH)
    env.rt.state.upstream.push = bd.Permission.NO
    env.br.step()
    assert pushes(fake) == [] and env.prs.calls == []
    assert env.events()[-1].data["ci"] == "none" and b.stage is Stage.REBASE


def test_push_with_the_permission_unasked_holds(env: Env, fake: FakeSystem) -> None:
    b = fresh_stack(env, 1, Stage.PUSH)
    env.rt.state.upstream.push = bd.Permission.UNASKED
    env.br.step()
    assert b.hold is BoundaryHold.PUSH_PERMISSION and pushes(fake) == []


def test_a_rejected_push_at_push_holds_and_rebase_has_not_run(env: Env, fake: FakeSystem) -> None:
    b = fresh_stack(env, 1, Stage.PUSH)
    fake.reply(("git", "push"), Done(1, "stale info"))
    env.br.step()
    assert b.hold is BoundaryHold.PUSH_REJECTED and b.stage is Stage.PUSH
    assert env.events()[-1].data["branch"] == "team/sprint-1"


# ----- the END order (checklist 4) -----------------------------------------------


def test_the_end_boundary_pushes_then_rebases_then_restacks(
    env: Env, fake: FakeSystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    b, (_e9, e10, e11) = at_stage(env, Stage.PUSH, H1, H2, H3)
    e11.pushed = ""
    monkeypatch.setattr(env.rt.upstream, "rebase_onto", lambda old: Rebase(SyncOutcome.CURRENT))
    script_fast_path(fake, PIN, N1, N2)
    env.br.step()
    assert env.prs.calls == [] and b.stage is Stage.REBASE
    env.br.step()
    assert env.prs.calls == [] and b.stage is Stage.RESTACK
    env.br.step()
    assert env.outcomes() == ["pass", "current", "merged", "restacked"]
    assert pr_calls(env, "edit")
    log = [c.argv for c in fake.commands]
    pushed = [i for i, a in enumerate(log) if a[:2] == ("git", "push")]
    first_rebase = next(i for i, a in enumerate(log) if "--onto" in a)
    assert pushed[0] < first_rebase < pushed[1]
    assert (e10.head, e11.head) == (N1, N2) and b.stage is Stage.CI


# ----- M9-M11: restack -----------------------------------------------------------


def test_a_merged_bottom_is_dropped_the_rest_rebased_pushed_and_retargeted(
    env: Env, fake: FakeSystem
) -> None:
    b, (_e9, e10, e11) = at_restack(env, H1, H2, H3)
    script_fast_path(fake, N1, N2)
    env.br.step()
    assert env.rt.state.upstream.stack == [e10, e11]
    assert (e10.head, e11.head) == (N1, N2) and (e10.pushed, e11.pushed) == (N1, N2)
    assert env.outcomes() == ["merged", "restacked"]
    assert env.events()[-1].data["branches"] == ["team/sprint-10", "team/sprint-11"]
    assert b.stage is Stage.CI and env.rt.state.boundary is b
    assert env.prs.prs["team/sprint-10"].base == "main"
    assert env.prs.prs["team/sprint-11"].base == "team/sprint-10"
    assert not env.prs.prs["team/sprint-10"].draft
    assert pr_calls(env, "edit") and not pr_calls(env, "create")


def test_branches_are_pushed_with_a_lease_on_the_old_pushed_value(
    env: Env, fake: FakeSystem
) -> None:
    at_restack(env, H1, H2, H3)
    script_fast_path(fake, N1, N2)
    env.br.step()
    argvs = pushes(fake)
    assert [a[-1] for a in argvs] == [
        "refs/heads/team/sprint-10:refs/heads/team/sprint-10",
        "refs/heads/team/sprint-11:refs/heads/team/sprint-11",
    ]
    assert f"--force-with-lease=refs/heads/team/sprint-10:{H2}" in argvs[0]
    assert f"--force-with-lease=refs/heads/team/sprint-11:{H3}" in argvs[1]


def test_no_open_pr_is_left_on_a_merged_base(env: Env, fake: FakeSystem) -> None:
    at_restack(env, H1, H2, H3, merged=2)
    script_fast_path(fake, N1)
    env.br.step()
    dropped = {"team/sprint-9", "team/sprint-10"}
    open_prs = [p for p in env.prs.prs.values() if p.state is PrState.OPEN]
    assert open_prs and not [p for p in open_prs if p.base in dropped]
    assert env.prs.prs["team/sprint-11"].base == "main"


def test_the_dropped_prs_are_untouched(env: Env, fake: FakeSystem) -> None:
    at_restack(env, H1, H2, H3)
    script_fast_path(fake, N1, N2)
    before = env.prs.prs["team/sprint-9"]
    env.br.step()
    assert env.prs.prs["team/sprint-9"] == before
    assert all(c[1] != 9 for c in pr_calls(env, "edit"))


def test_checked_follows_the_head_only_when_it_equalled_the_old_head(
    env: Env, fake: FakeSystem
) -> None:
    _b, (_e9, e10, e11) = at_restack(env, H1, H2, H3)
    e11.checked = "9" * 40
    script_fast_path(fake, N1, N2)
    env.br.step()
    assert e10.checked == N1 and e11.checked == "9" * 40


def test_nothing_merged_and_main_unmoved_moves_no_head_but_still_runs_the_prs(
    env: Env, fake: FakeSystem
) -> None:
    b = fresh_stack(env, 2)
    script_noop(fake, 2)
    first = env.rt.state.upstream.stack[0]
    first.pushed = first.head
    env.br.step()
    assert len(pushes(fake)) == 1  # the already-pushed parent is not pushed again
    assert len(pr_calls(env, "create")) == 2 and b.stage is Stage.CI
    assert not [c for c in fake.commands if c.argv[1:2] == ["branch"] and "--force" in c.argv]


def test_an_emptied_entry_is_dropped(env: Env, fake: FakeSystem) -> None:
    at_restack(env, H1, H2, H3, merged=0)
    script_fast_path(fake, N1, N2)
    fake.reply(("rev-list", "--count"), Done(0, "0\n"), Done(0, "3\n"), Done(0, "3\n"))
    env.br.step()
    assert "merged" in env.outcomes()
    assert 9 not in [e.sprint for e in env.rt.state.upstream.stack]


def test_restack_with_an_empty_stack_advances(env: Env) -> None:
    b = fresh_stack(env, 0)
    env.br.step()
    assert b.stage is Stage.CI and env.prs.calls == []


# ----- M12: refused plan -> rebuild ----------------------------------------------


def test_a_changed_tree_rebuilds_the_stack_and_moves_nothing(env: Env, fake: FakeSystem) -> None:
    b, (_e9, e10, e11) = at_restack(env, H1, H2, H3)
    fake.reply(("git", "rev-parse", "HEAD"), lines(N1))
    same_tree(fake, N1, H2, equal=False)
    env.br.step()
    assert b.stage is Stage.REVIEW and b.restack is True and env.rt.state.boundary is b
    assert env.outcomes()[-1] == "rebuild"
    note = env.events()[-1].data["note"]
    assert note == "team/sprint-10 rebased onto origin/main has a different tree"
    assert pushes(fake) == [] and not pr_calls(env, "edit")
    assert (e10.head, e11.head) == (H2, H3)
    assert not [c for c in fake.commands if c.argv[1:2] == ["branch"]]


def test_a_stopped_rebase_rebuilds_too(env: Env, fake: FakeSystem) -> None:
    b, _ = at_restack(env, H1, H2)
    fake.reply(("git", "rebase"), Done(1, "CONFLICT"))
    env.br.step()
    assert b.stage is Stage.REVIEW and env.outcomes()[-1] == "rebuild"
    assert "did not rebase cleanly" in env.events()[-1].data["note"]


# ----- M13: rejected push at restack ---------------------------------------------


def test_a_rejected_push_at_restack_holds_and_stays(env: Env, fake: FakeSystem) -> None:
    b, _ = at_restack(env, H1, H2, H3)
    script_fast_path(fake, N1, N2)
    fake.reply(("git", "push"), Done(1, "stale info"))
    env.br.step()
    assert b.hold is BoundaryHold.PUSH_REJECTED and b.stage is Stage.RESTACK
    data = env.events()[-1].data
    assert data["branch"] == "team/sprint-10" and "stale info" in data["reason"]
    assert len(pushes(fake)) == 1  # nothing after the refused push


# ----- M15: local delivery and guards --------------------------------------------


@pytest.mark.parametrize("why", ["permission", "no gh"])
def test_a_local_boundary_makes_no_gh_call_or_push_but_still_restacks(
    env: Env, fake: FakeSystem, why: str
) -> None:
    perm = bd.Permission.NO if why == "permission" else bd.Permission.YES
    at_restack(env, H1, H2, push=perm)
    if why == "no gh":
        env.prs.reason = "gh is not installed"
    finds: list[str] = []
    env.prs.find = lambda branch: finds.append(branch)
    script_fast_path(fake, N1)
    env.br.step()
    assert finds == [] and pushes(fake) == [] and env.prs.calls == []
    assert env.rt.state.boundary is None and env.rt.state.upstream.report


def test_a_failed_fetch_after_a_merge_is_found_holds_an_error(env: Env, fake: FakeSystem) -> None:
    b, _ = at_restack(env, H1, H2)
    fake.reply(("git", "fetch"), Done(1, "network down"))
    env.br.step()
    assert b.hold is BoundaryHold.ERROR
    assert "network down" in env.events()[-1].data["reason"]


# ----- M14/M16: ci ---------------------------------------------------------------


def test_ci_makes_no_find_call_and_green_finishes(env: Env) -> None:
    at_ci(env, H1, H2, merged=0)
    finds: list[str] = []
    env.prs.find = lambda branch: finds.append(branch)
    waited: list[int] = []
    env.prs.wait_checks = lambda n, s: waited.append(n) or True
    env.br.step()
    assert finds == [] and sorted(waited) == [9, 10]
    assert env.rt.state.boundary is None and env.outcomes()[-1] == "done"


def test_one_pr_without_checks_makes_the_verdict_none_never_green(env: Env) -> None:
    at_ci(env, H1, H2, merged=0)
    env.prs.checks = lambda n: GREEN if n == 9 else []
    env.br.step()
    assert env.events()[-1].data["ci"] == "none"


def test_an_empty_stack_at_ci_finishes_with_the_nothing_report(env: Env) -> None:
    env.rt.state.upstream.stack = []
    env.rt.state.upstream.team_branch = "main"
    env.open(Edge.END, stage=Stage.CI)
    env.br.step()
    assert env.rt.state.boundary is None
    assert env.rt.state.upstream.report == bd.NOTHING_REPORT.format(target="origin/main")


# ----- AC2: nothing mid-sprint, the sync stage ----------------------------------


def test_a_merge_made_mid_sprint_changes_nothing_until_the_sprint_ends(
    env: Env, fake: FakeSystem
) -> None:
    """AC2: nothing is due mid-sprint; only the END boundary's restack acts on the merge."""
    b, stack = at_restack(env, H1, H2)
    env.rt.state.boundary = None
    script_fast_path(fake, N1)
    finds: list[str] = []
    env.prs.find = lambda branch: finds.append(branch)
    assert env.br.due() is None
    assert pushes(fake) == [] and pr_calls(env, "edit") == [] and finds == []
    assert [(e.head, e.pushed, e.base) for e in stack] == [
        (H1, H1, "main"),
        (H2, H2, "team/sprint-9"),
    ]
    env.rt.state.boundary = b
    env.prs.find = type(env.prs).find.__get__(env.prs)
    env.br.step()
    assert [e.sprint for e in env.rt.state.upstream.stack] == [10]
    assert pushes(fake) and env.prs.prs["team/sprint-10"].base == "main"


def test_the_end_sync_only_adds_the_entry_and_follows_nothing(env: Env, fake: FakeSystem) -> None:
    b, _ = at_stage(env, Stage.SYNC, H1, H2)
    script_fast_path(fake, N1)
    env.br.step()
    assert env.outcomes() == ["pass"] and pushes(fake) == []
    assert b.stage is Stage.CHECK and not hasattr(env.br, "_drop_merged")


def test_the_end_rebase_stage_fetches_first(env: Env, fake: FakeSystem) -> None:
    fresh_stack(env, 1, Stage.REBASE)
    env.br.step()
    assert any(c.argv[:2] == ("git", "fetch") for c in fake.commands)
