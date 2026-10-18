"""s108 M3/M3a (AC5): the sprint-start sync fetches; s152 makes it rebase (test_s152_start.py)."""

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
from .test_boundary_runner import Env, entry

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


# ----- s152: the start rebases (see test_s152_start.py) ------------------------


def test_no_stack_entry_is_dropped_at_start(env: Env, fake: FakeSystem) -> None:
    stack = [entry(9), entry(10)]
    env.rt.state.upstream.stack = stack
    env.rt.state.upstream.team_branch = "main"
    env.rt.upstream.behind = lambda: 0
    env.open(Edge.START)
    env.drive()
    assert "merged" not in env.outcomes()
    assert [e.sprint for e in env.rt.state.upstream.stack] == [9, 10]


# ----- stages ----------------------------------------------------------------


def test_the_end_stage_order_is_push_ci_replay_push_replayed_ci_replayed() -> None:
    assert bd.EDGE_STAGES[Edge.END] == (
        Stage.SYNC,
        Stage.CHECK,
        Stage.PUSH,
        Stage.CI,
        Stage.REPLAY,
        Stage.PUSH_REPLAYED,
        Stage.CI_REPLAYED,
    )


def test_the_start_stage_order_is_sync_check_push_replayed_open() -> None:
    assert bd.EDGE_STAGES[Edge.START] == (
        Stage.SYNC,
        Stage.CHECK,
        Stage.PUSH_REPLAYED,
        Stage.OPEN,
    )


def test_the_end_only_stages_are_skipped_at_start() -> None:
    b = bd.Boundary(Edge.START, 1, stage=Stage.CHECK)
    assert bd.next_stage(b) is Stage.PUSH_REPLAYED
    assert bd.next_stage(bd.Boundary(Edge.START, 1, stage=Stage.OPEN)) is None


def test_the_end_edge_runs_the_end_stages_in_order() -> None:
    assert list(bd.EDGE_STAGES[Edge.END][2:]) == [
        Stage.PUSH,
        Stage.CI,
        Stage.REPLAY,
        Stage.PUSH_REPLAYED,
        Stage.CI_REPLAYED,
    ]
    assert bd.next_stage(bd.Boundary(Edge.END, 1, stage=Stage.CHECK)) is Stage.PUSH


def test_every_stage_has_a_runner_and_a_stage_row() -> None:
    assert set(br.STAGE_RUNNERS) == set(bd.Stage)
    assert br.STAGE_RUNNERS[Stage.OPEN] is br.BoundaryRunner._open
    assert br.STAGE_RUNNERS[Stage.REPLAY] is br.BoundaryRunner._replay
    assert br.STAGE_RUNNERS[Stage.PUSH_REPLAYED] is br.BoundaryRunner._push_replayed
    assert br.STAGE_RUNNERS[Stage.CI_REPLAYED] is br.BoundaryRunner._check_replayed_ci
    for stage in bd.Stage:
        assert stages.BOUNDARY[stage.value] in stages.STAGES
    assert stages.BOUNDARY["replay"] is stages.Name.BOUNDARY_REPLAY
    assert stages.BOUNDARY["push-replayed"] is stages.Name.BOUNDARY_PUSH_REPLAYED
    assert stages.BOUNDARY["ci-replayed"] is stages.Name.BOUNDARY_CI_REPLAYED
    assert stages.BOUNDARY["open"] is stages.Name.BOUNDARY_OPEN


def test_the_removed_follow_names_are_gone() -> None:
    assert not hasattr(br, "CI_AFTER_FOLLOW") and not hasattr(br, "SYNC_STOPS")
    assert not hasattr(bd, "RESTACK_ONLY") and not hasattr(bd, "RESTACKED_UPDATE")
