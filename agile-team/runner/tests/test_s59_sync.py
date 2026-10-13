"""s59 R2/R6/R8/R9: the start sync in the BoundaryRunner, with ``rebase_onto`` stubbed."""

import pytest
from agile_team import boundary as bd
from agile_team import rewrite
from agile_team.boundary import BoundaryHold, Edge, StackEntry
from agile_team.boundary_runner import SYNCS, BoundaryRunner
from agile_team.upstream import Rebase, SyncOutcome, UpstreamError

from .fake_system import FAKE_HEAD, Done, FakeSystem
from .test_boundary_runner import Env

FAILED = "f" * 40
NEW_HEAD = "9" * 40


@pytest.fixture
def env(make_runtime) -> Env:
    return Env(make_runtime)


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


def test_start_syncs_with_the_rebase_method_and_end_does_not() -> None:
    assert SYNCS[Edge.START] is BoundaryRunner._rebase
    assert SYNCS[Edge.END] is BoundaryRunner._end_sync


def test_a_conflict_holds_with_files_commit_and_subject(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(env, monkeypatch, CONFLICT)
    env.open(Edge.START)
    [report] = env.drive()
    data = report["boundary"]
    assert env.rt.state.boundary.hold is BoundaryHold.SYNC_CONFLICT
    assert (data["outcome"], data["hold"]) == ("conflict", "sync_conflict")
    assert data["files"] == ["a/x.py", "b.py"]
    assert data["commit"] == FAILED[:12] and len(data["commit"]) == 12
    assert data["subject"] == "fix the thing"
    assert env.br.due() is None


def test_a_conflict_remaps_and_records_nothing(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    install(env, monkeypatch, CONFLICT)
    calls = []
    monkeypatch.setattr(rewrite, "remap_state", lambda *a: calls.append(a) or 0)
    monkeypatch.setattr(env.rt, "record_checkout", lambda: calls.append("record"))
    env.open(Edge.START)
    env.drive()
    assert calls == []


def test_sync_from_is_set_once_and_reused_after_continue(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = install(env, monkeypatch, CONFLICT, Rebase(SyncOutcome.CURRENT))
    b = env.open(Edge.START)
    env.drive()
    assert b.sync_from == FAKE_HEAD
    b.hold = None
    env.drive()
    assert script.olds == [FAKE_HEAD, FAKE_HEAD]


def test_sync_from_is_not_replaced_when_already_set(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = install(env, monkeypatch, Rebase(SyncOutcome.CURRENT))
    env.open(Edge.START, sync_from="1" * 40)
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
    env.open(Edge.START)
    env.drive()
    assert order[:2] == ["save", "rebase"]


def test_nothing_is_saved_before_the_rebase_when_sync_from_is_already_set(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    order = _trace_save_and_rebase(env, monkeypatch)
    env.open(Edge.START, sync_from="1" * 40)
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
    env.open(Edge.START)
    env.drive()
    assert env.outcomes() == ["current", "pass", "done"] and spy == []


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
    env.open(Edge.START)
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
    env.open(Edge.START)
    env.drive()
    first = env.events()[0].data
    assert first["outcome"] == "rebased" and first["sha"] == NEW_HEAD
    assert first["rewritten"] == 2
    assert "merged" not in env.outcomes()
    assert env.outcomes()[-1] == "done"


def test_a_rebased_start_records_the_new_checkout(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(env, monkeypatch, rebased())
    called = []
    monkeypatch.setattr(env.rt, "record_checkout", lambda: called.append(1))
    env.open(Edge.START)
    env.drive()
    assert called


def test_an_entry_emptied_by_the_rebase_is_dropped_after_the_remap(
    env: Env, monkeypatch: pytest.MonkeyPatch, fake: FakeSystem
) -> None:
    # Before the rebase the entry still has a pick; after it, none.
    fake.reply(("git", "log", "--no-merges"), Done(0, "p1\n"))
    fake.reply(("git", "rev-list", "--reverse"), Done(0, "p1\n"), Done(0, ""))
    install(env, monkeypatch, rebased(o6="n9", o7="n9"))
    env.rt.state.upstream.stack = [
        StackEntry(1, "team/sprint-1", "o6", "o7", "Sprint 1", ["s1"], head="h1")
    ]
    env.open(Edge.START)
    env.drive()
    assert env.rt.state.upstream.stack == []
    outcomes = env.outcomes()
    assert outcomes.index("merged") < outcomes.index("rebased")
    note = [e.data["note"] for e in env.events() if e.data["outcome"] == "merged"]
    assert note == [bd.MERGED_NOTE.format(sprint=1, target="origin/main")]


def test_a_failure_of_the_rebase_is_an_error_hold(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(env, monkeypatch, UpstreamError("rebasing x changed paths only one side touched"))
    env.open(Edge.START)
    [report] = env.drive()
    assert env.rt.state.boundary.hold is BoundaryHold.ERROR
    assert "only one side touched" in report["boundary"]["reason"]
