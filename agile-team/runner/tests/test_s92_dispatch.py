"""s92 checklist 18-27: the gate routes, fix steps run and settle, the router picks them."""

import asyncio
import json

import pytest
from agile_team import git_check, owners
from agile_team.boundary import StepKind
from agile_team.dispatch import StepRequest
from agile_team.gates import StoryState, StoryStatus
from agile_team.owners import Fix, FixRecord, Item, Source
from agile_team.router import SENT_BACK_LINES, Router, standard_brief
from agile_team.state import RunState

from .conftest import FakeRunner, handoff
from .fake_system import Done
from .pipeline_helpers import Script, add_story, write_file

E2E_FILE = "tests/e2e/test_git.py"
UNIT_FILE = "tests/test_limits.py"
LISTING = f"src/a.py\n{UNIT_FILE}\ntests/test_x.py\n{E2E_FILE}\n"
E2E_FAIL = f"FAILED {E2E_FILE}::test_keep - AssertionError\n1 failed in 0.4s"
UNIT_FAIL = "FAILED tests/test_x.py::test_a - AssertionError\n1 failed in 0.1s"
LINT_UNIT = f"{UNIT_FILE}:8:1: I001 unsorted imports"
LINT_SRC = "src/a.py:3:1: F401 unused import"
GREEN = (0, "TOTAL 100%")
DIFF_CHANGED = "--- a/f\n+++ b/f\n-    assert f(1) == 1\n+    assert f(1) == 2\n"


@pytest.fixture(autouse=True)
def tracked(configured, fake) -> None:
    """A modelled working tree and no remote, so sprint boundaries are skipped."""
    fake.track()
    fake.reply(("git", "remote", "get-url"), Done(2))


class WritingScript(Script):
    """A Script whose roles can write a file in the step before they answer."""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.writes: dict[str, tuple[str, str]] = {}

    async def _gen(self, role):
        if role in self.writes:
            write_file(self.rt, *self.writes[role])
        async for message in super()._gen(role):
            yield message


def runtime(make_runtime, coverage=GREEN, lint=None, replies=None, files=(), **kw):
    results = {"pytest --cov": coverage, "git ls-files": (0, LISTING)}
    results["ruff check ."] = lint or (0, "")
    script = WritingScript(replies or {})
    rt = make_runtime(script, runner=FakeRunner(results), **kw)
    script.rt = rt
    add_story(rt, "s1", "implement", files=list(files))
    return rt, script


def run(rt, role, kind=StepKind.ROLE):
    return asyncio.run(rt.run_role(StepRequest(role, "go", "s1", kind)))


def fix_step(rt, role):
    return run(rt, role, StepKind.GATE_FIX)


def events_of(rt, kind):
    return [e for e in rt.events.events() if e.kind == kind]


def story_of(rt):
    return rt.state.stories["s1"]


def next_work(rt):
    return Router(rt).next_work()


# ---- 18: AC6, the s65 case ---------------------------------------------------


def test_an_e2e_only_failure_routes_without_a_round_or_a_dispute(make_runtime) -> None:
    rt, _ = runtime(make_runtime, coverage=(1, E2E_FAIL))
    gate = run(rt, "developer")["gate"]
    s = story_of(rt)
    assert gate["verdict"] == "route" and gate["rounds"] == 0 and gate["now_at"] == "implement"
    assert gate["fixes"] == [{"role": "integration-tester", "files": [E2E_FILE]}]
    assert (s.rounds, s.step, s.disputes) == (0, "implement", 0)
    assert events_of(rt, "test-dispute") == [] and rt.state.manager_due == []


def test_the_router_runs_the_fix_step_then_the_developer(make_runtime) -> None:
    rt, _ = runtime(make_runtime, coverage=(1, E2E_FAIL))
    run(rt, "developer")
    work = next_work(rt)
    assert (work.role, work.kind, work.story.id) == ("integration-tester", StepKind.GATE_FIX, "s1")
    report = fix_step(rt, "integration-tester")
    s = story_of(rt)
    assert s.fixes == [] and (s.step, s.rounds) == ("implement", 0) and "gate" not in report
    after = next_work(rt)
    assert (after.role, after.kind) == ("developer", StepKind.ROLE)
    assert SENT_BACK_LINES["route"].format(reason=s.previous.reason) in after.brief


# ---- 19: AC6, the s48 case ---------------------------------------------------


def test_lint_in_a_touched_unit_test_file_routes_to_the_unit_tester(make_runtime) -> None:
    rt, _ = runtime(make_runtime, lint=(1, LINT_UNIT), files=[UNIT_FILE])
    gate = run(rt, "developer")["gate"]
    assert (gate["verdict"], gate["rounds"]) == ("route", 0)
    assert [f.role for f in story_of(rt).fixes] == ["unit-tester"]


def test_lint_in_an_untouched_file_passes(make_runtime) -> None:
    rt, _ = runtime(make_runtime, lint=(1, LINT_UNIT))
    assert run(rt, "developer")["gate"]["verdict"] == "pass"
    assert story_of(rt).fixes == []


# ---- 20: AC6, the own cases --------------------------------------------------


def test_a_failing_unit_test_bounces_with_a_round_and_no_fixes(make_runtime) -> None:
    rt, _ = runtime(make_runtime, coverage=(1, UNIT_FAIL))
    gate = run(rt, "developer")["gate"]
    s = story_of(rt)
    assert (gate["verdict"], gate["now_at"], s.rounds, s.fixes) == ("bounce", "implement", 1, [])


def test_lint_in_the_developers_own_file_passes(make_runtime) -> None:
    rt, _ = runtime(make_runtime, lint=(1, LINT_SRC), files=["src/a.py"])
    assert run(rt, "developer")["gate"]["verdict"] == "pass"
    assert story_of(rt).fixes == []


# ---- 21: AC3, fix steps run in pipeline order --------------------------------


def test_fix_steps_run_unit_tester_then_integration_tester_then_developer(make_runtime) -> None:
    rt, _ = runtime(make_runtime, coverage=(1, E2E_FAIL), lint=(1, LINT_UNIT), files=[UNIT_FILE])
    run(rt, "developer")
    seen = []
    for _ in range(2):
        work = next_work(rt)
        seen.append((work.role, work.kind))
        fix_step(rt, work.role)
    assert seen == [("unit-tester", StepKind.GATE_FIX), ("integration-tester", StepKind.GATE_FIX)]
    assert next_work(rt).role == "developer"


# ---- 22: AC4, the fix brief ---------------------------------------------------


def test_the_fix_brief_lists_only_that_roles_items(make_runtime) -> None:
    rt, _ = runtime(make_runtime, coverage=(1, E2E_FAIL), lint=(1, LINT_UNIT), files=[UNIT_FILE])
    run(rt, "developer")
    unit = next_work(rt).brief
    assert UNIT_FILE in unit and E2E_FILE not in unit and "I001 unsorted imports" in unit
    fix_step(rt, "unit-tester")
    e2e = next_work(rt).brief
    assert E2E_FILE in e2e and "AssertionError" in e2e and UNIT_FILE not in e2e
    assert "Gate fix on story s1" in e2e


def test_a_foreign_dispute_brief_cites_the_rule(make_runtime) -> None:
    dispute = {"test": f"{E2E_FILE}::test_keep", "rule": "s65 G9", "reason": "lay_out never wipes"}
    replies = {"developer": [handoff("changes_requested", summary="why", dispute=dispute)]}
    rt, _ = runtime(make_runtime, replies=replies)
    write_file(rt, E2E_FILE, "def test_keep():\n    assert f(1) == 1\n")
    rt.git.commit([E2E_FILE], "test file")
    rt.pipeline.checks.run.results[f"git ls-files -- {E2E_FILE} '*/{E2E_FILE}'"] = (0, E2E_FILE)
    gate = run(rt, "developer")["gate"]
    assert gate["verdict"] == "route" and story_of(rt).disputes == 0
    assert "Design rule the failing step cited: s65 G9: lay_out never wipes" in next_work(rt).brief


# ---- 23: R17, settling a fix step ---------------------------------------------


def routed(make_runtime, reply):
    rt, script = runtime(
        make_runtime, coverage=(1, E2E_FAIL), replies={"integration-tester": [reply]}
    )
    run(rt, "developer")
    return rt, script


def test_a_fix_that_disagrees_bounces_with_a_round(make_runtime) -> None:
    rt, _ = routed(make_runtime, handoff("changes_requested", summary="not my file"))
    gate = fix_step(rt, "integration-tester")["gate"]
    s = story_of(rt)
    assert (gate["verdict"], gate["now_at"], s.rounds, s.fixes) == ("bounce", "implement", 1, [])
    assert (
        "integration-tester says the failure is not theirs to fix: not my file" in s.previous.reason
    )
    assert next_work(rt).role == "developer"


@pytest.mark.parametrize("status", ["blocked", "failed"])
def test_a_blocked_or_failed_fix_holds_the_story(make_runtime, status) -> None:
    rt, _ = routed(make_runtime, handoff(status, summary="stuck"))
    gate = fix_step(rt, "integration-tester")["gate"]
    assert gate["verdict"] == "hold" and gate["reason"] == f"role reported {status}: stuck"
    assert story_of(rt).fixes == [] and story_of(rt).rounds == 0


def test_a_malformed_fix_handoff_is_settled_as_failed(make_runtime) -> None:
    rt, _ = routed(make_runtime, "no handoff block here")
    report = fix_step(rt, "integration-tester")
    assert report["gate"]["verdict"] == "hold"
    assert report["gate"]["reason"].startswith("role reported failed: ")
    assert story_of(rt).fixes == []


def test_a_done_fix_runs_no_gate_and_leaves_previous_alone(make_runtime) -> None:
    rt, _ = routed(make_runtime, handoff())
    before = story_of(rt).previous
    gates = len(events_of(rt, "gate"))
    fix_step(rt, "integration-tester")
    assert story_of(rt).previous == before
    assert len(events_of(rt, "gate")) == gates
    assert len(events_of(rt, "gate-fix")) == 1


def test_a_fix_step_is_refused_for_the_wrong_role_or_no_queue(make_runtime) -> None:
    rt, _ = routed(make_runtime, handoff())
    assert "next gate fix is for integration-tester" in fix_step(rt, "unit-tester")["reason"]
    fix_step(rt, "integration-tester")
    assert "has no gate fix queued" in fix_step(rt, "integration-tester")["reason"]


# ---- 24: R13, a repeated route escalates ---------------------------------------


def test_the_same_route_twice_in_a_row_escalates(make_runtime) -> None:
    rt, _ = runtime(make_runtime, coverage=(1, E2E_FAIL))
    run(rt, "developer")
    fix_step(rt, "integration-tester")
    gate = run(rt, "developer")["gate"]
    s = story_of(rt)
    assert gate["verdict"] == "escalate" and s.status is StoryStatus.NEEDS_MANAGER
    assert len(events_of(rt, "escalation")) == 1 and s.fixes == [] and s.rounds == 0


# ---- 25: AC5, assertion changes reach the reviewer ------------------------------


def fixed_runtime(make_runtime, fake, diff, **extra):
    reply = handoff("done", **extra)
    rt, script = routed(make_runtime, reply)
    script.writes["integration-tester"] = (E2E_FILE, "def test_keep():\n    assert f(1) == 2\n")
    fake.reply(("git", "diff"), Done(0, diff))
    fix_step(rt, "integration-tester")
    return rt


def review_brief(rt):
    story_of(rt).step = "review"
    work = next_work(rt)
    return standard_brief(rt.config, work)


def test_a_named_rule_is_recorded_and_shown_to_the_reviewer(make_runtime, fake) -> None:
    rt = fixed_runtime(make_runtime, fake, DIFF_CHANGED, asserts="s65 G9")
    [record] = story_of(rt).fixed
    assert (record.role, record.files, record.asserts) == (
        "integration-tester",
        [E2E_FILE],
        "s65 G9",
    )
    assert record.changed is True and record.commit
    line = f"- Gate fix by integration-tester (commit {record.commit[:12]}) on {E2E_FILE}: "
    assert line + owners.fix_note(record) in review_brief(rt)
    assert "changed what a test asserts because s65 G9" in review_brief(rt)


def test_changed_assertions_without_a_rule_are_flagged(make_runtime, fake) -> None:
    rt = fixed_runtime(make_runtime, fake, DIFF_CHANGED)
    assert owners.FIX_NOTES[(False, True)] in review_brief(rt)


def test_other_roles_briefs_have_no_fix_lines(make_runtime, fake) -> None:
    rt = fixed_runtime(make_runtime, fake, DIFF_CHANGED)
    story_of(rt).step = "implement"
    assert "Gate fix by" not in next_work(rt).brief


def test_a_fix_with_no_commit_records_no_change(make_runtime) -> None:
    rt, _ = routed(make_runtime, handoff())
    fix_step(rt, "integration-tester")
    [record] = story_of(rt).fixed
    assert (record.commit, record.changed, record.asserts) == (None, False, "")


# ---- 26: R16, a fix step skips role set-ups ------------------------------------


def test_a_gate_fix_step_skips_the_presentation_but_keeps_the_git_env(
    make_runtime, monkeypatch
) -> None:
    rt, _ = routed(make_runtime, handoff())
    laid = []
    monkeypatch.setattr(rt, "_lay_out_presentation", laid.append)
    plan = rt.plan(StepRequest("integration-tester", "go", "s1", StepKind.GATE_FIX))
    assert laid == []
    assert plan.launch.env.get(git_check.CEILING_ENV)
    rt.plan(StepRequest("integration-tester", "go", "s1", StepKind.ROLE))
    assert len(laid) == 1


# ---- 27: story.files and legacy state --------------------------------------------


def test_a_commit_adds_its_paths_to_the_story_files_once(make_runtime) -> None:
    script = WritingScript()
    rt, _ = runtime(make_runtime)
    script.rt = rt
    rt.query_fn = script
    script.writes["developer"] = ("src/a.py", "x = 1\n")
    run(rt, "developer")
    assert story_of(rt).files == ["src/a.py"]
    run(rt, "developer")
    assert story_of(rt).files == ["src/a.py"]


def test_any_role_commit_adds_to_the_story_files(make_runtime) -> None:
    rt, script = runtime(make_runtime, coverage=(1, E2E_FAIL))
    run(rt, "developer")
    script.writes["integration-tester"] = (E2E_FILE, "x = 1\n")
    fix_step(rt, "integration-tester")
    assert E2E_FILE in story_of(rt).files


def test_old_state_loads_with_empty_files_fixes_and_fixed() -> None:
    legacy = {"stories": {"s1": {"id": "s1", "title": "t", "step": "implement", "sprint": 1}}}
    s = RunState.from_json(json.dumps(legacy)).stories["s1"]
    assert (s.files, s.fixes, s.fixed) == ([], [], [])


def test_fixes_and_records_round_trip_through_state_json() -> None:
    item = Item(E2E_FILE, Source.TEST, [E2E_FILE], ["l1"])
    s = StoryState("s1", "T", "implement", sprint=1)
    s.fixes = [Fix("integration-tester", [item], "r", "w")]
    s.fixed = [FixRecord("integration-tester", [E2E_FILE], "abc", "r", True)]
    s.files = [E2E_FILE]
    state = RunState()
    state.stories["s1"] = s
    back = RunState.from_json(state.to_json()).stories["s1"]
    assert (back.fixes, back.fixed, back.files) == (s.fixes, s.fixed, s.files)
