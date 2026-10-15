"""s108 M3/M3a (AC5): the sprint-start sync fetches and reports; it changes nothing."""

from __future__ import annotations

import pytest
from agile_team import boundary as bd
from agile_team import boundary_runner as br
from agile_team import stages
from agile_team.boundary import Edge, Stage
from agile_team.config import UpstreamSettings
from agile_team.git_ops import Git
from agile_team.upstream import Upstream

from .fake_system import FAKE_REPO, Done, FakeSystem
from .test_boundary_runner import Env, entry, pushes

H1, H2 = "a1" * 20, "b2" * 20

MUTATING = {"rebase", "reset", "merge", "checkout", "cherry-pick", "branch", "push", "worktree"}


@pytest.fixture
def env(make_runtime) -> Env:
    return Env(make_runtime)


def upstream() -> Upstream:
    return Upstream(Git(FAKE_REPO), UpstreamSettings())


# ----- M3a: Upstream.behind --------------------------------------------------


def test_behind_is_zero_when_the_target_is_an_ancestor(fake: FakeSystem) -> None:
    fake.reply(("rev-list", "--count"), Done(0, "0\n"))
    assert upstream().behind() == 0


def test_behind_counts_the_commits_the_target_gained(fake: FakeSystem) -> None:
    fake.reply(("rev-list", "--count"), Done(0, "2\n"))
    assert upstream().behind() == 2
    [command] = [c for c in fake.commands if "--count" in c.argv]
    assert command.argv[-1] == "HEAD..origin/main"


def test_behind_treats_empty_output_as_zero(fake: FakeSystem) -> None:
    fake.reply(("rev-list", "--count"), Done(0, "\n"))
    assert upstream().behind() == 0


# ----- texts -----------------------------------------------------------------


def test_start_notes_are_exact() -> None:
    assert br.START_NOTES == {
        False: "the team branch is current with {target}",
        True: (
            "{target} moved {count} commits since the last sprint-end rebase; "
            "nothing changes until the next sprint end"
        ),
    }
    assert not hasattr(br, "NOTHING_TO_PUSH")
    assert not hasattr(br, "START_NOTE")


# ----- M3 / AC5: a start sync with main ahead changes nothing ----------------


def start_with_main_ahead(env: Env, fake: FakeSystem, count: int) -> list[str]:
    stack = [entry(9), entry(10)]
    for e, head in zip(stack, (H1, H2), strict=True):
        e.head, e.pushed, e.pr = head, head, e.sprint
    env.rt.state.upstream.stack = stack
    env.rt.state.upstream.team_branch = "main"
    finds: list[str] = []
    env.prs.find = lambda branch: finds.append(branch)
    fake.reply(("rev-list", "--count"), Done(0, f"{count}\n"))
    env.open(Edge.START)
    env.drive()
    return finds


def test_a_start_sync_with_main_ahead_reports_and_changes_nothing(
    env: Env, fake: FakeSystem
) -> None:
    story = env.rt.state.stories["s1"]
    story.commit = "c" * 40
    before = (env.rt.git.head(), story.commit, story.code_commits[:], env.rt.state.checkout)
    finds = start_with_main_ahead(env, fake, 2)
    up = env.rt.state.upstream
    assert [(e.head, e.pushed) for e in up.stack] == [(H1, H1), (H2, H2)]
    assert (env.rt.git.head(), story.commit, story.code_commits, env.rt.state.checkout) == before
    assert env.outcomes() == ["pass", "pass", "done"]
    first = env.events()[0].data
    assert first["note"] == (
        "origin/main moved 2 commits since the last sprint-end rebase; "
        "nothing changes until the next sprint end"
    )
    assert first["behind"] == 2
    assert env.rt.state.boundary is None
    assert finds == [] and env.prs.calls == [] and pushes(fake) == []
    assert not [c for c in fake.commands if MUTATING & set(c.argv)]


def test_a_start_sync_leaves_sync_from_alone(env: Env, fake: FakeSystem) -> None:
    fake.reply(("rev-list", "--count"), Done(0, "3\n"))
    b = env.open(Edge.START)
    env.drive()
    assert b.sync_from == ""


def test_a_start_sync_with_main_not_ahead_says_current(env: Env, fake: FakeSystem) -> None:
    start_with_main_ahead(env, fake, 0)
    first = env.events()[0].data
    assert first["note"] == "the team branch is current with origin/main"
    assert first["behind"] == 0


def test_no_stack_entry_is_dropped_at_start(env: Env, fake: FakeSystem) -> None:
    start_with_main_ahead(env, fake, 2)
    assert "merged" not in env.outcomes()
    assert [e.sprint for e in env.rt.state.upstream.stack] == [9, 10]


# ----- stages ----------------------------------------------------------------


def test_the_stage_order_is_push_ci_rebase_push_rebased_ci_rebased() -> None:
    assert bd.STAGES == (
        Stage.SYNC,
        Stage.CHECK,
        Stage.PUSH,
        Stage.CI,
        Stage.REBASE,
        Stage.PUSH_REBASED,
        Stage.CI_REBASED,
    )


def test_the_end_only_stages_are_skipped_at_start() -> None:
    assert set(bd.STAGES[2:]) == bd.END_ONLY
    b = bd.Boundary(Edge.START, 1, stage=Stage.CHECK)
    assert bd.next_stage(b) is None


def test_the_end_edge_runs_the_five_end_stages_in_order() -> None:
    assert [bd.STAGES[i] for i in range(2, 7)] == [
        Stage.PUSH,
        Stage.CI,
        Stage.REBASE,
        Stage.PUSH_REBASED,
        Stage.CI_REBASED,
    ]
    assert bd.next_stage(bd.Boundary(Edge.END, 1, stage=Stage.CHECK)) is Stage.PUSH


def test_every_stage_has_a_runner_and_a_stage_row() -> None:
    assert set(br.STAGE_RUNNERS) == set(bd.Stage)
    assert br.STAGE_RUNNERS[Stage.PUSH_REBASED] is br.BoundaryRunner._push_rebased
    assert br.STAGE_RUNNERS[Stage.CI_REBASED] is br.BoundaryRunner._ci_rebased
    for stage in bd.Stage:
        assert stages.BOUNDARY[stage.value] in stages.STAGES
    assert stages.BOUNDARY["rebase"] is stages.Name.BOUNDARY_REBASE
    assert stages.BOUNDARY["push-rebased"] is stages.Name.BOUNDARY_PUSH_REBASED
    assert stages.BOUNDARY["ci-rebased"] is stages.Name.BOUNDARY_CI_REBASED


def test_the_removed_follow_names_are_gone() -> None:
    assert not hasattr(br, "CI_AFTER_FOLLOW") and not hasattr(br, "SYNC_STOPS")
    assert not hasattr(bd, "RESTACK_ONLY") and not hasattr(bd, "RESTACKED_UPDATE")
