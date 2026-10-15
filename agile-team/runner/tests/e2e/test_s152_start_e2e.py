"""s152 AC1.1 end to end: the start ``sync`` step against real git in scratch repos.

Neither ``behind`` nor ``rebase_onto`` is stubbed; the repos live under ``tmp_path``.
"""

from __future__ import annotations

import pytest
from agile_team.boundary import Edge, Stage
from agile_team.boundary_runner import START_CURRENT
from agile_team.git_ops import Git

from ..test_boundary_runner import Env
from .test_s59_rebase_e2e import World, is_ancestor, make_world, state_with


@pytest.fixture
def repos(tmp_path) -> World:
    return make_world(tmp_path)


def start_env(make_runtime, repos: World, commits: list[str]) -> Env:
    """An Env whose runtime reads and rebases the real team clone."""
    env = Env(make_runtime)
    env.rt.upstream = repos.upstream()
    env.rt.git = Git(repos.team)
    env.rt.state.upstream = state_with(commits).upstream
    env.rt.state.stories["s1"] = state_with(commits).stories["s1"]
    env.rt.state.stories["s1"].sprint = 1
    env.open(Edge.START)
    return env


def head(repos: World) -> str:
    return Git(repos.team).head()


def test_ac1_1_a_start_sync_rebases_real_commits_onto_moved_main(make_runtime, repos):
    mine = repos.commit(repos.team, "src/mine.txt", "m\n", "team work")
    repos.commit(repos.other, "src/theirs.txt", "t\n", "main moves")
    repos.push_main()
    env = start_env(make_runtime, repos, [mine])
    env.br.step()
    story = env.rt.state.stories["s1"]
    b = env.rt.state.boundary
    assert is_ancestor(repos.team, "origin/main")
    assert story.commit != mine and is_ancestor(repos.team, story.commit)
    assert story.commit == head(repos)
    event = env.events()[-1].data
    assert event["outcome"] == "rebased" and event["rewritten"] >= 1
    assert b.sync_from == "" and b.stage is Stage.CHECK


def test_ac1_1_a_start_sync_leaves_a_branch_already_on_main_alone(make_runtime, repos):
    before = head(repos)
    env = start_env(make_runtime, repos, [before])
    env.br.step()
    event = env.events()[-1].data
    assert head(repos) == before
    assert event["outcome"] == "current"
    assert event["note"] == START_CURRENT.format(target="origin/main")
    assert env.rt.state.boundary.stage is Stage.CHECK


def test_ac1_1_a_usual_start_with_commits_already_on_main_as_copies(make_runtime, repos):
    mine = repos.commit(repos.team, "src/mine.txt", "m\n", "team work")
    repos.copy_to_main([mine])
    repos.push_main()
    env = start_env(make_runtime, repos, [mine])
    env.br.step()
    b = env.rt.state.boundary
    assert is_ancestor(repos.team, "origin/main")
    assert head(repos) == Git(repos.team).run("rev-parse", "origin/main").strip()
    assert env.events()[-1].data["outcome"] == "rebased"
    assert b.hold is None and b.failure is None and b.stage is Stage.CHECK
