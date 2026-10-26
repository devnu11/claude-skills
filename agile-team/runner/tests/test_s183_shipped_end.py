"""s183: an END boundary whose sprint the target already holds closes as shipped (AC1-AC3)."""

from __future__ import annotations

import asyncio
import json

import pytest
from agile_team import boundary as bd
from agile_team import handover
from agile_team.boundary import BoundaryHold, Edge, Stage
from agile_team.po_tools import Tools
from agile_team.router import Router
from agile_team.upstream import PrMode

from .fake_system import Done, FakeSystem
from .s29_helpers import FakePrs
from .test_boundary_runner import Env, entry, pushes
from .test_s159_boundary_replay import at, replayed

HEAD = "r" * 40


@pytest.fixture
def cenv(make_runtime) -> Env:
    env = Env(make_runtime)
    env.prs = FakePrs()
    env.rt.prs = env.prs
    env.rt.state.upstream.team_branch = "main"
    return env


MERGE_BASE = ("git", "merge-base")
FETCH = ("git", "fetch")


def shipped(fake: FakeSystem, sha: str = HEAD) -> None:
    """The target's merge base with HEAD is ``sha``."""
    fake.reply(MERGE_BASE, Done(0, sha + "\n"))


def calls(env: Env, name: str) -> list[tuple]:
    return [c for c in env.prs.calls if c[0] == name]


def report_text() -> str:
    return bd.SHIPPED_REPORT.format(sprint=1, target="origin/main", sha=HEAD)


def run_to_end(env: Env) -> dict:
    env.drive()
    return env.events()[-1].data


# ---------- AC1: shipped ----------


def test_shipped_end_pushes_nothing_and_creates_no_pr_ac1(cenv: Env, fake: FakeSystem) -> None:
    shipped(fake)
    own = entry(1)
    replayed(cenv, own)
    cenv.drive()
    assert pushes(fake) == []
    assert calls(cenv, "create") == [] and calls(cenv, "edit") == []


def test_shipped_end_finishes_with_the_report_ac1(cenv: Env, fake: FakeSystem) -> None:
    shipped(fake)
    own = entry(1)
    replayed(cenv, own)
    cenv.drive()
    up = cenv.rt.state.upstream
    assert cenv.rt.state.boundary is None and up.closed == 1
    assert up.report == report_text()
    assert own.mode is PrMode.CLOSED


def test_shipped_done_event_has_note_sha_target_and_no_ci_ac1(cenv: Env, fake: FakeSystem) -> None:
    shipped(fake)
    replayed(cenv, entry(1))
    data = run_to_end(cenv)
    assert data["outcome"] == "done"
    assert data["note"] == report_text()
    assert data["sha"] == HEAD and data["target"] == "origin/main"
    assert "ci" not in data


def test_shipped_closes_the_open_pr_once_with_the_note_ac1(cenv: Env, fake: FakeSystem) -> None:
    shipped(fake)
    replayed(cenv, entry(1))
    cenv.drive()
    [(_, number, note)] = calls(cenv, "close")
    assert number == 7
    assert note == bd.SHIPPED_PR_NOTE.format(target="origin/main", sha=HEAD)


def test_shipped_without_a_pr_makes_no_close_call_ac1(cenv: Env, fake: FakeSystem) -> None:
    shipped(fake)
    own = entry(1)
    replayed(cenv, own)
    own.pr, own.url = 0, ""
    cenv.drive()
    assert calls(cenv, "close") == [] and own.mode is PrMode.CLOSED


def test_shipped_with_gh_missing_makes_no_gh_call_ac1(cenv: Env, fake: FakeSystem) -> None:
    shipped(fake)
    cenv.prs.reason = "gh is not installed"
    own = entry(1)
    replayed(cenv, own)
    cenv.drive()
    assert cenv.prs.calls == [] and own.mode is PrMode.CLOSED
    assert cenv.rt.state.boundary is None


def test_shipped_leaves_an_already_closed_pr_alone_ac1(cenv: Env, fake: FakeSystem) -> None:
    shipped(fake)
    own = entry(1)
    replayed(cenv, own)
    own.mode = PrMode.CLOSED
    cenv.drive()
    assert calls(cenv, "close") == []


def test_the_po_hand_over_says_the_sprint_is_already_on_the_target_ac1(
    cenv: Env, fake: FakeSystem
) -> None:
    shipped(fake)
    replayed(cenv, entry(1))
    cenv.drive()
    assert f"Review: {report_text()}" in Router(cenv.rt)._sprint_end().lines


def test_no_ci_green_rule_fires_for_the_shipped_event_ac1(cenv: Env, fake: FakeSystem) -> None:
    shipped(fake)
    replayed(cenv, entry(1))
    data = run_to_end(cenv)
    [rule] = [r for r in handover.HANDOVERS if r.trigger is handover.Trigger.CI_GREEN]
    assert not rule.applies({"boundary": data})


# ---------- AC2: a boundary held at push-replayed ----------


def held_after_failed_create(cenv: Env) -> bd.StackEntry:
    """The -r1 branch was pushed, the PR create failed, the entry was half-updated."""
    own = entry(1)
    own.branch, own.replays = "team/sprint-1-r1", 1
    replayed(cenv, own)
    own.pushed = own.head = HEAD
    cenv.rt.state.boundary.hold = BoundaryHold.ERROR
    cenv.rt.state.boundary.failure = "No commits between main and team/sprint-1-r1"
    return own


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def test_continue_boundary_closes_a_held_error_as_shipped_ac2(cenv: Env, fake: FakeSystem) -> None:
    shipped(fake)
    own = held_after_failed_create(cenv)
    assert call(Tools(cenv.rt).continue_boundary({"note": ""}))["status"] == "continued"
    cenv.drive()
    assert cenv.rt.state.boundary is None and cenv.rt.state.upstream.closed == 1
    assert own.mode is PrMode.CLOSED
    assert calls(cenv, "edit") == [] and calls(cenv, "create") == []
    assert pushes(fake) == []


def test_the_next_sprint_starts_after_a_shipped_close_ac2(cenv: Env, fake: FakeSystem) -> None:
    from . import story_setup
    from .conftest import write_story

    shipped(fake)
    held_after_failed_create(cenv)
    call(Tools(cenv.rt).continue_boundary({"note": ""}))
    cenv.drive()
    for s in cenv.rt.state.stories.values():
        s.sprint = 1
    write_story(cenv.rt.config, "s2", "cli")
    story_setup.opened(cenv.rt, story_setup.Opening("s2", "Add"))
    out = call(Tools(cenv.rt).start_sprint({"goal": "Next", "stories": ["s2"]}))
    assert out.get("status") != "refused", out
    assert cenv.rt.state.boundary == bd.Boundary(Edge.START, 2)


# ---------- AC3: only part of the sprint is on the target ----------


@pytest.mark.parametrize("printed", [None, "a" * 40])
def test_a_target_lacking_head_still_pushes_the_replay_branch_ac3(
    cenv: Env, fake: FakeSystem, printed: str | None
) -> None:
    if printed:
        fake.reply(MERGE_BASE, Done(0, printed + "\n"))
    own = entry(1)
    replayed(cenv, own)
    cenv.drive()
    assert own.branch == "team/sprint-1-r1" and own.mode is PrMode.READY
    [push] = pushes(fake)
    assert "team/sprint-1-r1" in " ".join(push)
    [(_, spec)] = calls(cenv, "create")
    assert spec.mode is PrMode.READY


def test_a_failed_merge_base_is_not_shipped_ac3(cenv: Env, fake: FakeSystem) -> None:
    fake.reply(MERGE_BASE, Done(1, HEAD + "\n"))
    replayed(cenv, entry(1))
    cenv.drive()
    assert len(pushes(fake)) == 1


def test_an_unchanged_head_still_makes_the_draft_ready_ac3(cenv: Env, fake: FakeSystem) -> None:
    own = entry(1)
    replayed(cenv, own)
    own.pushed = HEAD
    cenv.drive()
    assert pushes(fake) == [] and len(calls(cenv, "edit")) == 1


# ---------- the fetch ----------


def test_a_failed_fetch_at_push_replayed_holds_error(cenv: Env, fake: FakeSystem) -> None:
    fake.reply(FETCH, Done(128, "", "fatal: gone"))
    replayed(cenv, entry(1))
    cenv.drive()
    b = cenv.rt.state.boundary
    assert b.hold is BoundaryHold.ERROR and b.stage is Stage.PUSH_REPLAYED
    assert pushes(fake) == [] and calls(cenv, "create") == []


# ---------- the start edge does not change ----------


def test_the_start_edge_never_asks_for_the_shipped_check(cenv: Env, fake: FakeSystem) -> None:
    shipped(fake)
    cenv.rt.state.upstream.push = bd.Permission.YES
    at(cenv, Stage.OPEN, edge=Edge.START)
    cenv.drive()
    assert cenv.rt.state.boundary is None or cenv.rt.state.boundary.edge is Edge.START
