"""s59 R2/R6/R8/R9: the start sync in the BoundaryRunner, with ``rebase_onto`` stubbed."""

import pytest
from agile_team import boundary as bd
from agile_team import rewrite
from agile_team.boundary import BoundaryHold, Edge, Stage
from agile_team.boundary_runner import STAGE_RUNNERS, SYNCS, BoundaryRunner
from agile_team.ci import CiResult, CiVerdict
from agile_team.upstream import Rebase, SyncOutcome, UpstreamError

from .fake_system import FAKE_HEAD
from .test_boundary_runner import Env

FAILED = "f" * 40
NEW_HEAD = "9" * 40


@pytest.fixture
def env(make_runtime) -> Env:
    """An Env whose sprint already has a green as-built push, so the rebase gate (s151) opens."""
    env = Env(make_runtime)
    entry = bd.StackEntry(1, "team/sprint-1", FAKE_HEAD, FAKE_HEAD, head=FAKE_HEAD, pr=1)
    entry.pushed = entry.as_is = FAKE_HEAD
    entry.ci = CiResult(1, "u", FAKE_HEAD, CiVerdict.GREEN)
    env.rt.state.upstream.stack = [entry]
    return env


class Script:
    """A stand-in for ``Upstream.rebase_onto``: gives its results in turn and records ``old``."""

    def __init__(self, *results: Rebase) -> None:
        self.results = list(results)
        self.olds: list[str] = []
        self.log: list[str] = []

    def __call__(self, old: str) -> Rebase:
        self.olds.append(old)
        self.log.clear()
        result = self.results[min(len(self.olds), len(self.results)) - 1]
        if isinstance(result, Exception):
            raise result
        return result


def install(env: Env, monkeypatch: pytest.MonkeyPatch, *results) -> Script:
    script = Script(*results)
    monkeypatch.setattr(env.rt.upstream, "rebase_onto", script)
    return script


def rebased(**moved: str) -> Rebase:
    return Rebase(SyncOutcome.REBASED, sha=NEW_HEAD, moved=moved)


CONFLICT = Rebase(
    SyncOutcome.CONFLICT,
    files=("a/x.py", "b.py"),
    commit=FAILED,
    subject="fix the thing",
    output="CONFLICT",
)


def test_start_only_reports_and_the_rebase_is_its_own_stage() -> None:
    assert SYNCS[Edge.START] is BoundaryRunner._start_sync
    assert STAGE_RUNNERS[Stage.REBASE] is BoundaryRunner._rebase
    assert SYNCS[Edge.END] is BoundaryRunner._end_sync


def test_a_conflict_reports_files_commit_and_subject_and_holds(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(env, monkeypatch, CONFLICT)
    env.open(Edge.END, stage=Stage.REBASE)
    [report] = env.drive()
    data = report["boundary"]
    assert env.rt.state.boundary.hold is BoundaryHold.SYNC_CONFLICT
    assert data["files"] == ["a/x.py", "b.py"]
    assert data["commit"] == FAILED[:12] and len(data["commit"]) == 12
    assert data["subject"] == "fix the thing"
    assert env.rt.state.boundary.failure is None


def test_a_conflict_remaps_and_records_nothing(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    install(env, monkeypatch, CONFLICT)
    calls = []
    monkeypatch.setattr(rewrite, "remap_state", lambda *a: calls.append(a) or 0)
    monkeypatch.setattr(env.rt, "record_checkout", lambda: calls.append("record"))
    env.open(Edge.END, stage=Stage.REBASE)
    env.drive()
    assert calls == []


def test_sync_from_is_set_once_and_reused_after_continue(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = install(env, monkeypatch, CONFLICT, Rebase(SyncOutcome.CURRENT))
    b = env.open(Edge.END, stage=Stage.REBASE)
    env.drive()
    assert b.sync_from == FAKE_HEAD
    b.hold = None
    env.drive()
    assert script.olds == [FAKE_HEAD, FAKE_HEAD]


def test_sync_from_is_not_replaced_when_already_set(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = install(env, monkeypatch, Rebase(SyncOutcome.CURRENT))
    env.open(Edge.END, stage=Stage.REBASE, sync_from="1" * 40)
    env.drive()
    assert script.olds == ["1" * 40]


def _trace_save_and_rebase(env: Env, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    order: list[str] = []
    monkeypatch.setattr(env.rt, "save", lambda: order.append("save"))

    def rebase(old: str) -> Rebase:
        order.append("rebase")
        return Rebase(SyncOutcome.CURRENT)

    monkeypatch.setattr(env.rt.upstream, "rebase_onto", rebase)
    return order


def test_sync_from_is_saved_before_the_rebase_runs(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    order = _trace_save_and_rebase(env, monkeypatch)
    env.open(Edge.END, stage=Stage.REBASE)
    env.drive()
    assert order[:2] == ["save", "rebase"]


def test_nothing_is_saved_before_the_rebase_when_sync_from_is_already_set(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    order = _trace_save_and_rebase(env, monkeypatch)
    env.open(Edge.END, stage=Stage.REBASE, sync_from="1" * 40)
    env.drive()
    assert order[0] == "rebase"


def test_boundary_defaults_to_an_empty_sync_from() -> None:
    assert bd.Boundary(Edge.START, 1).sync_from == ""
    assert bd.BoundaryOutcome.REBASED == "rebased"
    assert not hasattr(bd, "MERGE_MESSAGE")


def test_current_emits_current_without_remapping(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    install(env, monkeypatch, Rebase(SyncOutcome.CURRENT))
    spy = []
    monkeypatch.setattr(rewrite, "remap_state", lambda *a: spy.append(a) or 0)
    env.open(Edge.END, stage=Stage.REBASE)
    env.drive()
    assert env.outcomes()[:1] == ["current"] and spy == []


def test_rebased_remaps_records_and_saves_before_the_event(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = install(env, monkeypatch, rebased(o1="n1"))
    env.rt.state.stories["s1"].commit = "o1"
    real = rewrite.remap_state
    seen_at: list[tuple[str, bool]] = []

    def note(name: str) -> None:
        script.log.append(name)
        seen_at.append((name, "rebased" in env.outcomes()))

    def remap(state, moved):
        note("remap")
        return real(state, moved)

    monkeypatch.setattr(rewrite, "remap_state", remap)
    monkeypatch.setattr(env.rt, "record_checkout", lambda: note("record_checkout"))
    monkeypatch.setattr(env.rt, "save", lambda: note("save"))
    env.open(Edge.END, stage=Stage.REBASE)
    env.drive()
    assert script.log[:3] == ["remap", "record_checkout", "save"]
    assert [early for name, early in seen_at[:3]] == [False, False, False]
    assert env.rt.state.stories["s1"].commit == "n1"


def test_the_rebased_event_has_the_new_head_and_the_rewrite_count(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(env, monkeypatch, rebased(o1="n1", o2="n2"))
    env.rt.state.stories["s1"].commit = "o1"
    env.rt.state.stories["s1"].code_commits = ["o2"]
    env.open(Edge.END, stage=Stage.REBASE)
    env.drive()
    first = env.events()[0].data
    assert first["outcome"] == "rebased" and first["sha"] == NEW_HEAD
    assert first["rewritten"] == 2
    assert "merged" not in env.outcomes()


def test_a_rebased_end_records_the_new_checkout(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    install(env, monkeypatch, rebased())
    called = []
    monkeypatch.setattr(env.rt, "record_checkout", lambda: called.append(1))
    env.open(Edge.END, stage=Stage.REBASE)
    env.drive()
    assert called


def test_a_failure_of_the_rebase_is_an_error_hold(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(env, monkeypatch, UpstreamError("rebasing x changed paths only one side touched"))
    env.open(Edge.END, stage=Stage.REBASE)
    [report] = env.drive()
    assert env.rt.state.boundary.hold is BoundaryHold.ERROR
    assert "only one side touched" in report["boundary"]["reason"]


def test_sync_from_is_cleared_and_saved_after_rebased(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(env, monkeypatch, rebased())
    b = env.open(Edge.END, stage=Stage.REBASE)
    env.br.step()
    assert b.sync_from == ""


def test_sync_from_is_cleared_after_current(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    install(env, monkeypatch, Rebase(SyncOutcome.CURRENT))
    b = env.open(Edge.END, stage=Stage.REBASE)
    env.br.step()
    assert b.sync_from == ""


def test_a_conflict_keeps_sync_from_and_the_rebase_stage(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(env, monkeypatch, CONFLICT)
    b = env.open(Edge.END, stage=Stage.REBASE)
    env.br.step()
    assert b.sync_from == FAKE_HEAD and b.stage is Stage.REBASE


def test_the_conflict_handover_line_says_the_sprint_end() -> None:
    import inspect

    from agile_team import handover

    source = inspect.getsource(handover)
    assert "sprint {sprint} end: rebasing" in source
    assert "start: rebasing" not in source


def test_a_failed_fetch_at_rebase_holds_an_error(env: Env, fake) -> None:
    from .fake_system import Done

    fake.reply(("git", "fetch"), Done(1, "network down"))
    b = env.open(Edge.END, stage=Stage.REBASE)
    env.br.step()
    assert b.hold is BoundaryHold.ERROR
    assert "network down" in env.events()[-1].data["reason"]
