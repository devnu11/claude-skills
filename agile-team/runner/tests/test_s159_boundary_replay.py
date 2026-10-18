"""s159 slice 6: the open, replay and push-replayed stages and follow_remote (R3, R5, R7, R9)."""

from __future__ import annotations

import pytest
from agile_team import boundary as bd
from agile_team.boundary import BoundaryHold, Edge, FixCase, Stage
from agile_team.ci import CiResult, CiVerdict
from agile_team.upstream import PrMode, PrState, Rebase, SyncOutcome

from .fake_system import FAKE_HEAD, Done, FakeSystem
from .s29_helpers import FakePrs
from .test_boundary_runner import NEW, OLD, Env, entry, pushes


@pytest.fixture
def cenv(make_runtime) -> Env:
    env = Env(make_runtime)
    env.prs = FakePrs()
    env.rt.prs = env.prs
    env.rt.state.upstream.team_branch = "main"
    return env


def at(env: Env, stage: Stage, *entries: bd.StackEntry, edge: Edge = Edge.END) -> bd.Boundary:
    env.rt.state.upstream.stack = list(entries)
    return env.open(edge, stage=stage)


# ---------- the texts (R6) ----------


def test_the_ff_command_is_the_landing_text_r6() -> None:
    assert bd.FF_COMMAND == "git push {remote} {sha}:{target}"


def test_no_text_tells_the_human_to_rebase_and_merge_r6() -> None:
    from agile_team import ci, handover

    modules = (bd, ci, handover)
    texts = [v for m in modules for v in vars(m).values() if isinstance(v, str)]
    assert not [t for t in texts if "Rebase and merge" in t]


def test_superseded_by_text_r5() -> None:
    assert "{url}" in bd.SUPERSEDED_BY and "superseded" in bd.SUPERSEDED_BY


# ---------- the start's open stage (R7, AC2.17) ----------


def test_open_creates_the_remote_branch_and_the_sprint_entry_r7(
    cenv: Env, fake: FakeSystem
) -> None:
    cenv.rt.state.upstream.push = bd.Permission.YES
    at(cenv, Stage.OPEN, edge=Edge.START)
    cenv.drive()
    [entry_] = cenv.rt.state.upstream.stack
    assert entry_.sprint == 1 and entry_.branch == "team/sprint-1"
    assert entry_.start == entry_.end == entry_.head == FAKE_HEAD
    assert entry_.pushed == FAKE_HEAD
    [push] = pushes(fake)
    assert "--force-with-lease=refs/heads/team/sprint-1:" in " ".join(push)


def test_open_defers_the_push_while_permission_is_unasked_r7(cenv: Env, fake: FakeSystem) -> None:
    at(cenv, Stage.OPEN, edge=Edge.START)
    cenv.drive()
    [entry_] = cenv.rt.state.upstream.stack
    assert entry_.pushed == "" and entry_.head == FAKE_HEAD
    assert pushes(fake) == [] and cenv.rt.state.permission_asked


def test_the_ends_sync_reuses_the_opened_entry_r5(cenv: Env) -> None:
    own = entry(1)
    own.start = own.end = own.head = NEW
    at(cenv, Stage.SYNC, own)
    cenv.drive()
    assert len(cenv.rt.state.upstream.stack) == 1
    assert cenv.events()[0].data["note"] == bd.NOTHING_NEW.format(sprint=1)


# ---------- push-replayed (R5) ----------


def replayed(cenv: Env, entry_: bd.StackEntry) -> bd.Boundary:
    entry_.pushed = entry_.as_is = NEW
    entry_.pr, entry_.url, entry_.mode = 7, "https://example/pull/7", PrMode.DRAFT
    cenv.rt.state.upstream.push = bd.Permission.YES
    cenv.rt.git.head = lambda: "r" * 40
    return at(cenv, Stage.PUSH_REPLAYED, entry_)


def test_push_replayed_goes_to_the_next_replay_branch_r5(cenv: Env, fake: FakeSystem) -> None:
    own = entry(1)
    replayed(cenv, own)
    cenv.drive()
    assert own.branch == "team/sprint-1-r1" and own.replays == 1
    assert own.head == "r" * 40 and own.pushed == "r" * 40
    [push] = pushes(fake)
    assert "team/sprint-1-r1" in " ".join(push)


def test_push_replayed_opens_a_ready_pr_and_closes_the_draft_with_a_link_r5(cenv: Env) -> None:
    own = entry(1)
    replayed(cenv, own)
    cenv.drive()
    [(_, spec)] = [c for c in cenv.prs.calls if c[0] == "create"]
    assert spec.branch == "team/sprint-1-r1" and spec.mode is PrMode.READY
    [(_, number, note)] = [c for c in cenv.prs.calls if c[0] == "close"]
    assert number == 7 and "pull/" in note
    assert own.mode is PrMode.READY and own.pr != 7


def test_a_second_replay_makes_r2_and_never_force_pushes_r5(cenv: Env, fake: FakeSystem) -> None:
    own = entry(1)
    own.branch, own.replays = "team/sprint-1-r1", 1
    replayed(cenv, own)
    cenv.drive()
    assert own.branch == "team/sprint-1-r2" and own.replays == 2
    assert all("--force " not in " ".join(p) for p in pushes(fake))


def bd_pr(number: int, state: PrState):
    from agile_team.upstream import Pr

    return Pr(number, f"https://example/pull/{number}", state, False, "main")


# ---------- the replay stage and ci for drafts (R5) ----------


def test_ci_watches_a_draft_pr_as_well_as_a_ready_one_r5(cenv: Env) -> None:
    own = entry(1)
    own.pr, own.mode = 7, PrMode.DRAFT
    at(cenv, Stage.CI, own)
    assert cenv.br._watched(cenv.rt.state.boundary) == [own]


def test_a_replay_conflict_pins_progress_and_holds_for_devops_r2(
    cenv: Env, fake: FakeSystem
) -> None:
    own = entry(1)
    own.pushed = own.as_is = own.head
    own.ci = CiResult(5, "https://h/5", own.head, CiVerdict.GREEN, [])
    at(cenv, Stage.REPLAY, own)
    cenv.rt.upstream.rebase_onto = lambda old: Rebase(
        SyncOutcome.CONFLICT, files=("a.py",), commit="c1", subject="s"
    )
    cenv.drive()
    b = cenv.rt.state.boundary
    assert b.replay is not None and b.replay.old_head
    assert b.failure is not None and b.failure.case is FixCase.REBASE_CONFLICT
    assert b.stage is Stage.REPLAY and b.failure.files == ["a.py"]


# ---------- follow_remote (R9) ----------


def test_follow_remote_fast_forwards_to_a_moved_remote_head_r9(cenv: Env, fake: FakeSystem) -> None:
    own = entry(1)
    own.pushed = OLD
    b = at(cenv, Stage.CI, own)
    b.hold = BoundaryHold.CI_FAILED
    fake.reply(("ls-remote",), Done(0, f"{NEW}\trefs/heads/team/sprint-1\n"))
    cenv.br.follow_remote()
    assert own.head == own.pushed == NEW
    assert b.hold is None and b.stage is Stage.CI
    assert cenv.outcomes()[-1] == "followed"
    assert any("--ff-only" in c.argv for c in fake.commands)


def test_follow_remote_does_nothing_when_the_remote_is_unchanged_r9(
    cenv: Env, fake: FakeSystem
) -> None:
    own = entry(1)
    own.pushed = OLD
    b = at(cenv, Stage.CI, own)
    b.hold = BoundaryHold.CI_FAILED
    fake.reply(("ls-remote",), Done(0, f"{OLD}\trefs/heads/team/sprint-1\n"))
    cenv.br.follow_remote()
    assert b.hold is BoundaryHold.CI_FAILED and own.pushed == OLD


def test_follow_remote_halts_as_drift_when_it_cannot_fast_forward_r9(
    cenv: Env, fake: FakeSystem
) -> None:
    own = entry(1)
    own.pushed = OLD
    at(cenv, Stage.CI, own).hold = BoundaryHold.CI_FAILED
    fake.reply(("ls-remote",), Done(0, f"{NEW}\trefs/heads/team/sprint-1\n"))
    fake.reply(("--ff-only",), Done(1, "not possible"))
    cenv.br.follow_remote()
    assert cenv.rt.halted_by is not None and cenv.rt.halted_by.kind.value == "checkout"
