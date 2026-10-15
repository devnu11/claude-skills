"""s152: the sprint start rebases once more, and its check failures become known failures."""

from __future__ import annotations

import pytest
from agile_team import boundary as bd
from agile_team import boundary_runner as br
from agile_team import handover
from agile_team.boundary import Edge, Stage, StepKind
from agile_team.boundary_runner import BoundaryRunner
from agile_team.fullcheck import CheckReport, CheckResult, FullCheck
from agile_team.upstream import Rebase, SyncOutcome

from .fake_system import FAKE_HEAD
from .test_boundary_runner import Env, posted

OLD, MOVED = "c" * 40, "d" * 40
TWO = ("tests/test_x.py::test_a", "tests/test_x.py::test_b")


@pytest.fixture
def env(make_runtime) -> Env:
    return Env(make_runtime)


def failing(name: str, *ids: str) -> CheckResult:
    return CheckResult(FullCheck(name, f"run {name}"), 1, "exit 1", "tail text", failed=ids)


def passing(name: str) -> CheckResult:
    return CheckResult(FullCheck(name, f"run {name}"), 0, "", "")


def fail_checks(env: Env, *results: CheckResult) -> None:
    report = CheckReport(results)
    env.br._run_checks = lambda path: report


def start_sync(env: Env, behind: int, result: Rebase) -> list[str]:
    """Open a start boundary at sync with a scripted ``behind`` and ``rebase_onto``."""
    calls: list[str] = []
    env.rt.upstream.behind = lambda: behind

    def rebase_onto(old: str) -> Rebase:
        calls.append(old)
        return result

    env.rt.upstream.rebase_onto = rebase_onto
    env.open(Edge.START)
    return calls


# ----- AC1.1 -------------------------------------------------------------------


def test_ac1_1_a_start_sync_rebases_and_remaps_the_hashes(env: Env) -> None:
    story = env.rt.state.stories["s1"]
    story.commit = OLD
    calls = start_sync(env, 1, Rebase(SyncOutcome.REBASED, sha=NEW_SHA, moved={OLD: MOVED}))
    env.br.step()
    b = env.rt.state.boundary
    assert len(calls) == 1 and story.commit == MOVED
    assert b.sync_from == "" and b.stage is Stage.CHECK
    event = env.events()[-1].data
    assert event["outcome"] == "rebased" and event["rewritten"] >= 1
    assert event["sha"] == NEW_SHA


def test_ac1_1_a_branch_already_on_the_target_is_left_alone(env: Env) -> None:
    calls = start_sync(env, 0, Rebase(SyncOutcome.CURRENT))
    env.br.step()
    event = env.events()[-1].data
    assert calls == []
    assert event["outcome"] == "current" and event["behind"] == 0
    assert event["note"] == br.START_CURRENT.format(target="origin/main")
    assert env.rt.state.boundary.stage is Stage.CHECK


def test_ac1_1_a_pinned_sync_from_still_rebases_when_not_behind(env: Env) -> None:
    story = env.rt.state.stories["s1"]
    story.commit = OLD
    calls = start_sync(env, 0, Rebase(SyncOutcome.REBASED, sha=NEW_SHA, moved={OLD: MOVED}))
    env.rt.state.boundary.sync_from = "e" * 40
    env.br.step()
    assert calls == ["e" * 40] and story.commit == MOVED
    assert env.rt.state.boundary.sync_from == ""


def test_ac1_1_a_rebase_that_finds_nothing_to_do_says_current(env: Env) -> None:
    start_sync(env, 2, Rebase(SyncOutcome.CURRENT))
    env.br.step()
    assert env.events()[-1].data["outcome"] == "current"
    assert env.rt.state.boundary.stage is Stage.CHECK


def test_ac1_1_a_start_conflict_holds_nothing_and_tells_the_liaison(env: Env) -> None:
    result = Rebase(SyncOutcome.CONFLICT, files=("a.py", "b.py"), commit=OLD, subject="Add x")
    start_sync(env, 1, result)
    before = env.rt.git.head()
    env.br.step()
    b = env.rt.state.boundary
    text = br.START_CONFLICT.format(
        sprint=1,
        team="main",
        target="origin/main",
        commit=OLD[:12],
        subject="Add x",
        files="a.py, b.py",
    )
    event = env.events()[-1].data
    assert event["outcome"] == "conflict" and event["note"] == text
    assert event["files"] == ["a.py", "b.py"] and event["commit"] == OLD[:12]
    assert event["subject"] == "Add x" and not event.get("hold")
    assert b.hold is None and b.failure is None and b.sync_from == ""
    assert b.stage is Stage.CHECK and env.rt.git.head() == before
    assert text in posted(env)


def test_ac1_1_the_start_tables_map_outcomes_to_handlers() -> None:
    assert {
        SyncOutcome.CONFLICT: BoundaryRunner._start_conflict,
        SyncOutcome.CURRENT: BoundaryRunner._rebase_current,
        SyncOutcome.REBASED: BoundaryRunner._settle_rebase,
    } == br.START_REBASES
    assert br.SYNCS[Edge.START] is BoundaryRunner._start_sync
    assert not hasattr(br, "START_NOTES")


# ----- AC2.1 -------------------------------------------------------------------

NEW_SHA = "f" * 40


def test_ac2_1_a_failing_start_check_holds_nothing(env: Env) -> None:
    fail_checks(env, failing("lint"))
    env.open(Edge.START, stage=Stage.CHECK)
    checked = env.rt.state.upstream.checked
    [report] = env.drive()
    assert env.rt.state.boundary is None
    assert env.br.due() is None
    assert env.rt.state.manager_due == []
    assert env.rt.state.upstream.checked == checked
    assert report["boundary"]["outcome"] == "done"


def test_ac2_1_a_failing_end_check_still_asks_for_a_team_fix(env: Env) -> None:
    fail_checks(env, failing("lint"))
    env.open(Edge.END, stage=Stage.CHECK)
    env.br.step()
    b = env.rt.state.boundary
    assert b.failure.case is bd.FixCase.TEAM_CHECK
    assert env.br.due().kind is StepKind.TEAM_FIX


def test_ac2_1_the_check_tables_map_edges_to_handlers() -> None:
    assert {
        Edge.START: BoundaryRunner._known_failures,
        Edge.END: BoundaryRunner._team_fix,
    } == br.CHECK_FAILURES


def test_ac2_1_a_passing_start_check_still_passes(env: Env) -> None:
    fail_checks(env, passing("lint"))
    env.open(Edge.START, stage=Stage.CHECK)
    env.drive()
    assert env.rt.state.upstream.checked == FAKE_HEAD
    assert "known_failures" not in env.events()[-1].data


# ----- AC2.2 -------------------------------------------------------------------


def test_ac2_2_the_done_event_records_the_failed_test_ids(env: Env) -> None:
    fail_checks(env, passing("lint"), failing("pytest", *TWO))
    env.open(Edge.START, stage=Stage.CHECK)
    env.drive()
    event = env.events()[-1].data
    assert event["outcome"] == "done"
    assert event["known_failures"] == list(TWO)
    assert event["sha"] == FAKE_HEAD and "tail text" in event["reason"]
    assert event["checks"][1]["passed"] is False


def test_ac2_2_a_check_without_failed_cases_is_named(env: Env) -> None:
    fail_checks(env, failing("lint"))
    env.open(Edge.START, stage=Stage.CHECK)
    env.drive()
    assert env.events()[-1].data["known_failures"] == ["lint"]


def test_ac2_2_the_note_counts_the_failures_and_goes_to_the_liaison(env: Env) -> None:
    fail_checks(env, failing("pytest", *TWO))
    env.open(Edge.START, stage=Stage.CHECK)
    env.drive()
    text = br.KNOWN_FAILURES_NOTE.format(
        sprint=1, count=2, team="main", sha=FAKE_HEAD[:12], ids=", ".join(TWO)
    )
    assert env.events()[-1].data["note"] == text
    assert text in posted(env)


# ----- AC2.3 -------------------------------------------------------------------


def test_ac2_3_the_report_hands_the_failures_to_the_po(env: Env) -> None:
    fail_checks(env, failing("pytest", *TWO))
    env.open(Edge.START, stage=Stage.CHECK)
    [report] = env.drive()
    assert handover.Trigger.KNOWN_FAILURES in handover.triggers(report)
    [line] = [
        ln for ln in handover.report_lines(report, None) if "request_story" in ln and "known" in ln
    ]
    assert TWO[0] in line and TWO[1] in line and "2 known failures" in line
    assert "tail text" in line and FAKE_HEAD[:12] in line


def test_ac2_3_a_passing_start_check_raises_no_known_failures(env: Env) -> None:
    fail_checks(env, passing("lint"))
    env.open(Edge.START, stage=Stage.CHECK)
    [report] = env.drive()
    assert handover.Trigger.KNOWN_FAILURES not in handover.triggers(report)


def test_ac2_3_known_failures_trigger_value() -> None:
    assert handover.Trigger.KNOWN_FAILURES == "known_failures"


# ----- AC3.1 -------------------------------------------------------------------


def test_ac3_1_every_ac_id_has_a_test() -> None:
    names = [n for n in globals() if n.startswith("test_ac")]
    for ac in ("ac1_1", "ac2_1", "ac2_2", "ac2_3"):
        assert any(n.startswith(f"test_{ac}_") for n in names)
