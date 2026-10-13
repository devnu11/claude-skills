"""s108: every PR ready, merges followed at sync and at ci, big-PR notes in the reports."""

from __future__ import annotations

import pytest
from agile_team import boundary as bd
from agile_team import boundary_runner as br
from agile_team.boundary import BoundaryHold, Edge, Stage
from agile_team.ci import Bucket, Check
from agile_team.restack import FollowOutcome
from agile_team.upstream import Pr, PrMode, PrState

from .fake_system import Done, FakeSystem
from .test_boundary_runner import Env, entry, pushes
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


def at_ci(env: Env, *heads: str, merged: int = 1, push: bd.Permission = bd.Permission.YES):
    """A stack of ready PRs (sprints 9..) at the ci stage; the first ``merged`` are merged."""
    stack = [
        entry(
            9 + i,
        )
        for i in range(len(heads))
    ]
    for i, (e, head) in enumerate(zip(stack, heads, strict=True)):
        e.head, e.checked = head, head
        below = stack[i - 1].branch if i else "main"
        open_pr(env, e, below, PrState.MERGED if i < merged else PrState.OPEN)
    env.rt.state.upstream.stack = stack
    env.rt.state.upstream.team_branch = "main"
    env.rt.state.upstream.push = push
    env.prs.check_list = GREEN
    return env.open(Edge.END, stage=Stage.CI), stack


def script_fast_path(fake: FakeSystem, *new: str) -> None:
    """Rebase gives ``new`` heads in turn; each has the same tree as before."""
    fake.reply(("git", "rev-parse", "HEAD"), lines(*new))
    for sha in new:
        same_tree(fake, sha, "")
    fake.reply(("rev-list", "--count"), Done(0, "2\n"))


def pr_calls(env: Env, verb: str) -> list:
    return [c for c in env.prs.calls if c[0] == verb]


def updates(env: Env) -> list[str]:
    return [m.text for m in env.rt.relay.messages() if m.kind == "update"]


# ----- M1: every PR ready ----------------------------------------------------


def test_every_created_pr_is_ready_and_based_on_the_one_below(env: Env, fake: FakeSystem) -> None:
    env.rt.state.upstream.push = bd.Permission.YES
    env.rt.state.upstream.stack = [entry(1), entry(2), entry(3)]
    env.rt.state.upstream.team_branch = "main"
    env.open(Edge.END, stage=Stage.PUSH)
    env.br.step()
    creates = [spec for _, spec in pr_calls(env, "create")]
    assert [s.mode for s in creates] == [PrMode.READY] * 3
    assert [s.base for s in creates] == ["main", "team/sprint-1", "team/sprint-2"]
    assert "Stacked on team/sprint-1 (#1)" in creates[1].body


def test_an_open_draft_is_made_ready_by_the_push(env: Env) -> None:
    e = entry(1)
    env.rt.state.upstream.push = bd.Permission.YES
    env.rt.state.upstream.stack = [e]
    env.rt.state.upstream.team_branch = "main"
    env.prs.prs[e.branch] = Pr(4, "u", PrState.OPEN, True, "main")
    env.open(Edge.END, stage=Stage.PUSH)
    env.br.step()
    [(_, number, spec)] = pr_calls(env, "edit")
    assert number == 4 and spec.mode is PrMode.READY
    assert env.prs.prs[e.branch].draft is False


def test_the_pushed_report_names_ci_on_every_pr(env: Env) -> None:
    env.rt.state.upstream.push = bd.Permission.YES
    env.rt.state.upstream.stack = [entry(1), entry(2)]
    env.rt.state.upstream.team_branch = "main"
    env.open(Edge.END, stage=Stage.PUSH)
    env.br.step()
    [text] = [t for t in updates(env) if "are pushed" in t]
    assert "waits for CI on every PR of the stack" in text
    assert "(ready," not in text and "(draft," not in text


# ----- M12: commits and big PR notes -----------------------------------------


def test_commits_are_counted_against_the_target_then_the_branch_below(
    env: Env, fake: FakeSystem
) -> None:
    fake.reply(("rev-list", "--count"), Done(0, "4\n"), Done(0, "5\n"))
    env.rt.state.upstream.push = bd.Permission.YES
    env.rt.state.upstream.stack = [entry(1), entry(2)]
    env.rt.state.upstream.team_branch = "main"
    env.open(Edge.END, stage=Stage.PUSH)
    env.br.step()
    e1, e2 = env.rt.state.upstream.stack
    assert (e1.commits, e2.commits) == (4, 5)
    spans = [c.argv[-1] for c in fake.commands if "--count" in c.argv]
    assert spans == [f"origin/main..{e1.head}", f"{e1.head}..{e2.head}"]


def test_the_pushed_report_gets_a_note_for_a_big_pr(env: Env, fake: FakeSystem) -> None:
    fake.reply(("rev-list", "--count"), Done(0, "101\n"))
    env.rt.state.upstream.push = bd.Permission.YES
    env.rt.state.upstream.stack = [entry(1)]
    env.rt.state.upstream.team_branch = "main"
    env.open(Edge.END, stage=Stage.PUSH)
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
    env.prs.check_list = []
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


# ----- M2/M4/M5/M7/M10: the follow at the ci stage ---------------------------


def test_a_merged_bottom_is_dropped_the_rest_rebased_pushed_and_retargeted(
    env: Env, fake: FakeSystem
) -> None:
    b, (_e9, e10, e11) = at_ci(env, H1, H2, H3)
    script_fast_path(fake, N1, N2)
    env.br.step()
    assert env.rt.state.upstream.stack == [e10, e11]
    assert (e10.head, e11.head) == (N1, N2) and (e10.pushed, e11.pushed) == (N1, N2)
    assert env.outcomes()[-2:] == ["merged", "restacked"]
    assert env.events()[-1].data["branches"] == ["team/sprint-10", "team/sprint-11"]
    assert b.stage is Stage.CI and env.rt.state.boundary is b
    assert env.prs.prs["team/sprint-10"].base == "main"
    assert env.prs.prs["team/sprint-11"].base == "team/sprint-10"
    assert not env.prs.prs["team/sprint-10"].draft
    assert pr_calls(env, "edit") and not pr_calls(env, "create")


def test_branches_are_pushed_with_a_lease_on_the_old_pushed_value(
    env: Env, fake: FakeSystem
) -> None:
    at_ci(env, H1, H2, H3)
    script_fast_path(fake, N1, N2)
    env.br.step()
    argvs = pushes(fake)
    assert [a[-1] for a in argvs] == [
        "refs/heads/team/sprint-10:refs/heads/team/sprint-10",
        "refs/heads/team/sprint-11:refs/heads/team/sprint-11",
    ]
    assert f"--force-with-lease=refs/heads/team/sprint-10:{H2}" in argvs[0]
    assert f"--force-with-lease=refs/heads/team/sprint-11:{H3}" in argvs[1]


def test_the_update_names_the_merged_and_the_moved_prs(env: Env, fake: FakeSystem) -> None:
    at_ci(env, H1, H2, H3)
    script_fast_path(fake, N1, N2)
    env.br.step()
    assert updates(env)[-1] == bd.RESTACKED_UPDATE.format(
        target="main",
        merged="#9 (team/sprint-9)",
        prs="#10 (team/sprint-10) https://h/10; #11 (team/sprint-11) https://h/11",
    )


def test_no_open_pr_is_left_on_a_merged_base(env: Env, fake: FakeSystem) -> None:
    at_ci(env, H1, H2, H3, merged=2)
    script_fast_path(fake, N1)
    env.br.step()
    dropped = {"team/sprint-9", "team/sprint-10"}
    open_prs = [p for p in env.prs.prs.values() if p.state is PrState.OPEN]
    assert open_prs and not [p for p in open_prs if p.base in dropped]
    assert env.prs.prs["team/sprint-11"].base == "main"


def test_checked_follows_the_head_only_when_it_equalled_the_old_head(
    env: Env, fake: FakeSystem
) -> None:
    _b, (_e9, e10, e11) = at_ci(env, H1, H2, H3)
    e11.checked = "9" * 40
    script_fast_path(fake, N1, N2)
    env.br.step()
    assert e10.checked == N1 and e11.checked == "9" * 40


def test_the_next_step_watches_every_remaining_pr_and_green_finishes(
    env: Env, fake: FakeSystem
) -> None:
    _b, _ = at_ci(env, H1, H2, H3)
    script_fast_path(fake, N1, N2)
    env.br.step()
    waited: list[int] = []
    env.prs.wait_checks = lambda n, s: waited.append(n) or True
    env.br.step()
    assert sorted(waited) == [10, 11]
    assert env.rt.state.boundary is None and env.outcomes()[-1] == "done"


def test_there_is_no_wait_before_the_follow(env: Env, fake: FakeSystem) -> None:
    at_ci(env, H1, H2)
    script_fast_path(fake, N1)
    order: list[str] = []
    env.prs.wait_checks = lambda n, s: order.append("wait") or True
    real_find = env.prs.find
    env.prs.find = lambda branch: order.append("find") or real_find(branch)
    env.br.step()
    assert order and order[0] == "find" and "wait" not in order


def test_a_merge_found_after_the_watch_throws_the_verdict_away(env: Env, fake: FakeSystem) -> None:
    b, (e9, e10) = at_ci(env, H1, H2, merged=0)
    script_fast_path(fake, N1)

    def merged_while_waiting(number: int, seconds: float) -> bool:
        env.prs.set_state(e9.branch, PrState.MERGED)
        return True

    env.prs.wait_checks = merged_while_waiting
    env.br.step()
    assert "done" not in env.outcomes() and b.stage is Stage.CI
    assert env.outcomes()[-1] == "restacked" and env.rt.state.upstream.stack == [e10]
    assert env.rt.state.boundary is b


def test_nothing_merged_goes_on_to_the_verdict(env: Env) -> None:
    at_ci(env, H1, merged=0)
    env.br.step()
    assert env.outcomes() == ["done"] and not pr_calls(env, "edit")


def test_an_empty_stack_at_ci_finishes_with_the_nothing_report(env: Env) -> None:
    env.rt.state.upstream.stack = []
    env.rt.state.upstream.team_branch = "main"
    env.open(Edge.END, stage=Stage.CI)
    env.br.step()
    assert env.rt.state.boundary is None
    assert env.rt.state.upstream.report == bd.NOTHING_REPORT.format(target="origin/main")


# ----- refusals: rebuild -----------------------------------------------------


def test_a_changed_tree_rebuilds_the_stack_and_moves_nothing(env: Env, fake: FakeSystem) -> None:
    b, (_e9, e10, e11) = at_ci(env, H1, H2, H3)
    fake.reply(("git", "rev-parse", "HEAD"), lines(N1))
    same_tree(fake, N1, H2, equal=False)
    env.br.step()
    assert b.stage is Stage.REVIEW and env.rt.state.boundary is b
    rebuild = env.events()[-1].data
    assert env.outcomes()[-1] == "rebuild"
    assert rebuild["note"] == "team/sprint-10 rebased onto origin/main has a different tree"
    assert pushes(fake) == [] and not pr_calls(env, "edit")
    assert (e10.head, e11.head) == (H2, H3)
    assert not [c for c in fake.commands if c.argv[1:2] == ["branch"]]


def test_a_stopped_rebase_rebuilds_too(env: Env, fake: FakeSystem) -> None:
    b, _ = at_ci(env, H1, H2)
    fake.reply(("git", "rebase"), Done(1, "CONFLICT"))
    env.br.step()
    assert b.stage is Stage.REVIEW and env.outcomes()[-1] == "rebuild"
    assert "did not rebase cleanly" in env.events()[-1].data["note"]


def test_a_refused_follow_at_sync_logs_rebuild_and_leaves_the_edge_to_rebuild(
    env: Env, fake: FakeSystem
) -> None:
    b, _ = at_ci(env, H1, H2)
    b.stage, b.edge = Stage.SYNC, Edge.END
    fake.reply(("git", "rebase"), Done(1, "CONFLICT"))
    fake.reply(("git", "log", "--right-only"), lines("p" * 40))
    fake.reply(("git", "rev-list"), lines("p" * 40))
    env.br.step()
    assert "rebuild" in env.outcomes() and b.stage is not Stage.CI
    assert pushes(fake) == []


# ----- rejected push while following -----------------------------------------


def test_a_rejected_push_at_ci_holds_and_goes_back_to_push(env: Env, fake: FakeSystem) -> None:
    b, _ = at_ci(env, H1, H2, H3)
    script_fast_path(fake, N1, N2)
    fake.reply(("git", "push"), Done(1, "stale info"))
    env.br.step()
    assert b.hold is BoundaryHold.PUSH_REJECTED and b.stage is Stage.PUSH
    data = env.events()[-1].data
    assert data["branch"] == "team/sprint-10" and "stale info" in data["reason"]


# ----- guards (M2) -----------------------------------------------------------


@pytest.mark.parametrize("why", ["permission", "no gh"])
def test_the_follow_is_skipped_without_push_permission_or_gh(env: Env, why: str) -> None:
    perm = bd.Permission.NO if why == "permission" else bd.Permission.YES
    b, _ = at_ci(env, H1, H2, push=perm)
    if why == "no gh":
        env.prs.reason = "gh is not installed"
    finds: list[str] = []
    env.prs.find = lambda branch: finds.append(branch)
    env.br._followed(b)
    assert finds == []


def test_the_follow_reports_none_when_it_is_skipped(env: Env) -> None:
    b, _ = at_ci(env, H1, push=bd.Permission.NO)
    assert env.br._follow(b) is FollowOutcome.NONE


def test_a_failed_fetch_while_following_holds_an_error(env: Env, fake: FakeSystem) -> None:
    b, _ = at_ci(env, H1, H2)
    fake.reply(("git", "fetch"), Done(0), Done(1, "network down"))
    env.br.step()
    assert b.hold is BoundaryHold.ERROR
    assert "network down" in env.events()[-1].data["reason"]


# ----- tables ----------------------------------------------------------------


def test_the_ci_table_maps_each_outcome_to_what_happens_next() -> None:
    assert set(br.CI_AFTER_FOLLOW) == set(FollowOutcome)
    assert frozenset({FollowOutcome.REJECTED}) == br.SYNC_STOPS


def test_the_ci_table_actions_set_the_stage(env: Env) -> None:
    b, _ = at_ci(env, H1)
    br.CI_AFTER_FOLLOW[FollowOutcome.NONE](env.br, b)
    br.CI_AFTER_FOLLOW[FollowOutcome.RESTACKED](env.br, b)
    assert b.stage is Stage.CI
    br.CI_AFTER_FOLLOW[FollowOutcome.REBUILD](env.br, b)
    assert b.stage is Stage.REVIEW
    br.CI_AFTER_FOLLOW[FollowOutcome.REJECTED](env.br, b)
    assert b.stage is Stage.PUSH


# ----- sync stage ------------------------------------------------------------


def sync_with_merged_bottom(env: Env, fake: FakeSystem, edge: Edge) -> bd.Boundary:
    b, _ = at_ci(env, H1, H2)
    b.stage, b.edge = Stage.SYNC, edge
    script_fast_path(fake, N1)
    fake.reply(("git", "log", "--right-only"), lines("p" * 40))
    fake.reply(("git", "rev-list"), lines("p" * 40))
    return b


def test_the_start_sync_follows_the_merge_and_asks_for_a_restack(
    env: Env, fake: FakeSystem
) -> None:
    b = sync_with_merged_bottom(env, fake, Edge.START)
    env.br.step()
    assert "merged" in env.outcomes() and b.restack is True
    assert [e.branch for e in env.rt.state.upstream.stack] == ["team/sprint-10"]


def test_the_end_sync_follows_the_merge_before_adding_the_entry(env: Env, fake: FakeSystem) -> None:
    sync_with_merged_bottom(env, fake, Edge.END)
    env.br.step()
    outcomes = env.outcomes()
    assert outcomes.index("merged") < outcomes.index("pass")


def test_a_rejected_push_at_sync_stops_the_stage(env: Env, fake: FakeSystem) -> None:
    b = sync_with_merged_bottom(env, fake, Edge.END)
    fake.reply(("git", "push"), Done(1, "stale info"))
    env.br.step()
    assert b.hold is BoundaryHold.PUSH_REJECTED and b.stage is Stage.SYNC
    assert "pass" not in env.outcomes()
