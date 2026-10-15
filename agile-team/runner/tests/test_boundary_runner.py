"""s29 U1-U22: the BoundaryRunner on a scripted git, a fake PR service and fake checks."""

import json

import pytest
from agile_team import boundary as bd
from agile_team import system
from agile_team.boundary import BoundaryHold, Edge, Stage, StepKind
from agile_team.boundary_runner import BoundaryRunner
from agile_team.events import EventKind
from agile_team.gates import StoryState, StoryStatus
from agile_team.upstream import Pr, PrMode, PrState, Rebase, SyncOutcome

from .conftest import FakeRunner
from .fake_system import FAKE_HEAD, Done, FakeSystem
from .s29_helpers import FakePrs

NEW = "n3w0000000000000000000000000000000000000"
GOOD_COVERAGE = "TOTAL 100 0 100%"
GREEN = {"pytest --cov": (0, GOOD_COVERAGE)}


class PrefixRunner(FakeRunner):
    """A FakeRunner keyed on the start of a command: python commands carry the report option."""

    def __call__(self, command: str) -> tuple[int, str]:
        self.calls.append(command)
        hits = [k for k in self.results if command.startswith(k)]
        return self.results[max(hits, key=len)] if hits else (0, "")


class Env:
    """A runtime, its fake checks and PR service, and the BoundaryRunner under test."""

    def __init__(self, make_runtime, results=None):
        self.runner = PrefixRunner(results or GREEN)
        self.runner_for = lambda path: self.runner
        self.prs = FakePrs()
        self.rt = make_runtime(prs=self.prs, shell=lambda path: self.runner_for(path))
        self.br = BoundaryRunner(self.rt)
        self.rt.state.sprint = 1
        self.rt.state.stories["s1"] = StoryState(
            "s1", "One", "done", status=StoryStatus.DONE, sprint=1
        )

    def open(self, edge: Edge, **kw) -> bd.Boundary:
        self.rt.state.boundary = bd.Boundary(edge, self.rt.state.sprint, **kw)
        return self.rt.state.boundary

    def as_built(self, entry: bd.StackEntry) -> bd.StackEntry:
        """Mark ``entry`` as pushed as built at its head, HEAD there, and main unmoved (s151)."""
        entry.pushed = entry.as_is = entry.head
        self.rt.git.head = lambda: entry.head
        self.rt.upstream.rebase_onto = lambda old: Rebase(SyncOutcome.CURRENT)
        return entry

    def events(self) -> list:
        return [e for e in self.rt.events.events() if e.kind == EventKind.BOUNDARY]

    def outcomes(self) -> list[str]:
        return [e.data["outcome"] for e in self.events()]

    def drive(self) -> list[dict]:
        """Run boundary steps until none is due; return the reports."""
        reports = []
        while (due := self.br.due()) is not None and due.kind is StepKind.BOUNDARY:
            reports.append(self.br.step())
        return reports


@pytest.fixture
def env(make_runtime) -> Env:
    return Env(make_runtime)


# ----- U4 skip --------------------------------------------------------------

NO_REMOTE = ("git", "remote", "get-url")
OLD = "0ld0000000000000000000000000000000000000"


def test_no_remote_skips_the_start_boundary(env: Env, fake: FakeSystem) -> None:
    fake.reply(NO_REMOTE, Done(2))
    env.open(Edge.START)
    [report] = env.drive()
    assert env.rt.state.boundary is None
    [event] = env.events()
    assert event.data["outcome"] == "skipped" and event.data["note"] == "no remote 'origin'"
    assert event.role == "runner"
    assert report["role"] == "runner" and report["status"] == "boundary"
    assert report["boundary"] == event.data
    assert bd.Stage.CHECK not in [e.data["stage"] for e in env.events()]


def test_sync_off_skips(env: Env) -> None:
    env.rt.config.upstream.remote = ""
    env.rt.upstream.settings.remote = ""
    env.open(Edge.START)
    env.drive()
    assert env.events()[0].data["note"] == bd.SYNC_OFF


def test_skip_at_the_end_closes_the_sprint_with_the_skipped_report(
    env: Env, fake: FakeSystem
) -> None:
    fake.reply(NO_REMOTE, Done(2))
    env.open(Edge.END)
    env.drive()
    up = env.rt.state.upstream
    assert up.closed == 1 and env.rt.state.boundary is None
    assert up.report == bd.SKIPPED_REPORT.format(why="no remote 'origin'")


def test_fetch_failure_at_the_end_still_adds_the_entry(env: Env, fake: FakeSystem) -> None:
    fake.reply(("git", "fetch"), Done(1, "gone"))
    fake.reply(("git", "merge-base"), Done(0, OLD + "\n"))
    env.open(Edge.END)
    env.drive()
    [entry] = env.rt.state.upstream.stack
    assert entry.sprint == 1 and entry.start == OLD and entry.end == FAKE_HEAD
    assert env.events()[0].data["outcome"] == "skipped"


# ----- U5 start sync --------------------------------------------------------


def test_start_with_nothing_new_is_current_with_no_commit(env: Env) -> None:
    env.open(Edge.START)
    env.drive()
    assert env.outcomes()[0] == "pass"
    assert env.events()[0].data["note"].startswith("the team branch is current with")
    assert env.rt.state.boundary is None


def test_detached_head_is_an_error_hold(env: Env, fake: FakeSystem) -> None:
    fake.reply(("git", "symbolic-ref"), Done(1))
    env.open(Edge.START)
    [report] = env.drive()
    b = env.rt.state.boundary
    assert b.hold is BoundaryHold.ERROR and bd.DETACHED in b.note + report["boundary"]["reason"]
    assert report["boundary"]["reason"].startswith("UpstreamError: ")


def test_a_stage_exception_holds_with_error_and_writes_crash_log(env: Env) -> None:
    def boom(path):
        raise RuntimeError("shell exploded")

    env.runner_for = boom
    env.open(Edge.START, stage=Stage.CHECK)
    [report] = env.drive()
    assert env.rt.state.boundary.hold is BoundaryHold.ERROR
    assert report["boundary"]["reason"] == "RuntimeError: shell exploded"
    assert "shell exploded" in system.read_text(env.rt.config.run_dir / "crash.log")
    assert env.br.due() is None


# ----- U7/U9/U11/U12 check, fix, escalate -----------------------------------


def fail_lint(env: Env, text: str = "E501 line too long") -> None:
    env.runner.results = {**GREEN, "ruff check .": (1, text)}


def test_team_check_pass_records_head_and_a_second_check_is_skipped(env: Env) -> None:
    env.open(Edge.START, stage=Stage.CHECK)
    env.drive()
    head = FAKE_HEAD
    assert env.rt.state.upstream.checked == head
    calls = len(env.runner.calls)
    env.open(Edge.START, stage=Stage.CHECK)
    env.drive()
    assert len(env.runner.calls) == calls
    assert env.events()[-2].data["note"] == f"already checked at {head}"


def test_failed_check_sets_failure_and_asks_devops_for_a_team_fix(env: Env) -> None:
    fail_lint(env)
    env.open(Edge.START, stage=Stage.CHECK)
    [report] = env.drive()
    b = env.rt.state.boundary
    assert b.failure.case is bd.FixCase.TEAM_CHECK and b.failure.stage is Stage.CHECK
    assert report["boundary"]["outcome"] == "fail"
    assert report["boundary"]["checks"][0] == {
        "name": "lint",
        "passed": False,
        "why": "exit 1",
        "pending": "",
    }
    due = env.br.due()
    assert (due.kind, due.role) == (StepKind.TEAM_FIX, "devops")
    assert due.brief.startswith(bd.FIX_HEADING.format(sprint=1, edge="start", stage="check"))
    assert "E501 line too long" in due.brief


def test_after_fix_counts_a_round_and_the_check_reruns(env: Env) -> None:
    fail_lint(env)
    env.open(Edge.START, stage=Stage.CHECK)
    env.drive()
    env.runner.results = GREEN
    env.br.after_fix({"role": "devops", "status": "done"})
    b = env.rt.state.boundary
    assert (b.rounds, b.failure, b.hold) == (1, None, None)
    env.drive()
    assert env.rt.state.boundary is None and env.outcomes()[-2:] == ["pass", "done"]


def test_a_blocked_fix_holds_the_boundary_with_the_hand_over_reason(env: Env) -> None:
    fail_lint(env)
    env.open(Edge.START, stage=Stage.CHECK)
    env.drive()
    env.br.after_fix({"role": "devops", "status": "blocked", "open_questions": ["which linter?"]})
    b = env.rt.state.boundary
    assert b.hold is not None and b.failure is None
    assert env.br.due() is None


def test_a_halted_fix_changes_nothing(env: Env) -> None:
    fail_lint(env)
    env.open(Edge.START, stage=Stage.CHECK)
    env.drive()
    env.br.after_fix({"role": "devops", "status": "halted"})
    b = env.rt.state.boundary
    assert b.rounds == 0 and b.failure is not None


def test_the_same_failure_twice_escalates_to_the_manager(env: Env) -> None:
    env.open(Edge.START, stage=Stage.CHECK)
    fail_lint(env, "FAILED test_x in 1.2s")
    env.drive()
    first = env.events()[-1].data
    assert first["outcome"] == "fail" and first["count"] == 1
    env.br.after_fix({"role": "devops", "status": "done"})
    fail_lint(env, "FAILED test_x in 9.9s")
    [report] = env.drive()
    b = env.rt.state.boundary
    data = report["boundary"]
    assert data["outcome"] == "escalate" and data["count"] == 2 and len(data["history"]) == 1
    assert b.hold is BoundaryHold.ESCALATED and b.escalated
    assert env.rt.state.manager_due[-1] == bd.BOUNDARY_DUE.format(
        sprint=1, edge="start", count=2, stage="check"
    )
    assert env.br.due() is None


def test_a_different_failure_restarts_the_streak(env: Env) -> None:
    env.open(Edge.START, stage=Stage.CHECK)
    fail_lint(env, "alpha problem")
    env.drive()
    env.br.after_fix({"role": "devops", "status": "done"})
    fail_lint(env, "completely different")
    env.drive()
    b = env.rt.state.boundary
    assert b.hold is None and len(b.streak) == 1 and b.failure is not None


def test_the_round_cap_escalates_even_when_failures_differ(env: Env) -> None:
    env.open(Edge.START, stage=Stage.CHECK, rounds=env.rt.config.gates.round_cap)
    fail_lint(env, "brand new failure")
    [report] = env.drive()
    assert report["boundary"]["outcome"] == "escalate"
    assert env.rt.state.boundary.hold is BoundaryHold.ESCALATED


def test_manager_context_and_review_of_an_escalated_boundary(env: Env) -> None:
    env.open(Edge.START, stage=Stage.CHECK)
    fail_lint(env, "same")
    env.drive()
    env.br.after_fix({"role": "devops", "status": "done"})
    env.drive()
    ctx = json.loads(env.rt._manager_context().split("\n", 1)[1])
    view = ctx["repeated_boundary"]
    assert view["reason"].count("lint failed") == 1 and view["count"] == 2 and view["key"]
    assert len(view["history"]) == 2 and view["events"]


# ----- s151 push as built (the stack is seeded; real git is proven in e2e) ----------


def entry(sprint: int, **kw) -> bd.StackEntry:
    return bd.StackEntry(
        sprint, f"team/sprint-{sprint}", OLD, NEW, f"Sprint {sprint}", ["s1"], head=NEW, **kw
    )


def at_push(env: Env, *entries: bd.StackEntry) -> bd.Boundary:
    env.rt.state.upstream.stack = list(entries)
    env.rt.state.upstream.team_branch = "main"
    return env.open(Edge.END, stage=Stage.PUSH)


def pushes(fake: FakeSystem) -> list:
    return [c.argv for c in fake.commands if c.argv[:2] == ("git", "push")]


def posted(env: Env) -> list[str]:
    return [m.text for m in env.rt.relay.messages()]


def test_the_first_push_asks_for_permission_and_pushes_nothing(env: Env, fake: FakeSystem) -> None:
    b = at_push(env, entry(1))
    env.drive()
    assert b.hold is BoundaryHold.PUSH_PERMISSION
    assert env.events()[-1].data["outcome"] == "held"
    assert env.prs.calls == [] and pushes(fake) == []


def release_push(env: Env, answer: str) -> None:
    env.rt.state.upstream.push = bd.Permission(answer)
    env.rt.state.boundary.hold = None


def test_permission_yes_pushes_head_as_it_is_to_the_sprints_branch(
    env: Env, fake: FakeSystem
) -> None:
    """AC1.1: the sha of HEAD, no cherry-pick, no rebase, with the lease (absent branch)."""
    b = at_push(env, entry(1))
    env.br.step()
    release_push(env, "yes")
    env.br.step()
    [argv] = pushes(fake)
    assert argv[-1] == f"{FAKE_HEAD}:refs/heads/team/sprint-1"
    assert "--force-with-lease=refs/heads/team/sprint-1:" in argv
    assert not [c for c in fake.commands if {"cherry-pick", "rebase"} & set(c.argv)]
    [e] = env.rt.state.upstream.stack
    assert e.head == e.end == e.pushed == e.as_is == FAKE_HEAD
    assert env.rt.state.upstream.last_end == FAKE_HEAD
    assert b.stage is Stage.CI and env.outcomes()[-1] == "pushed"


def test_the_push_opens_a_ready_pr_onto_the_target(env: Env) -> None:
    """AC1.2: one create, branch <prefix><N>, base [upstream] branch, ready."""
    b = at_push(env, entry(1))
    env.rt.state.upstream.push = bd.Permission.YES
    env.br.step()
    [(_, spec)] = [c for c in env.prs.calls if c[0] == "create"]
    assert spec.branch == "team/sprint-1" and spec.base == "main" and spec.mode is PrMode.READY
    [e] = env.rt.state.upstream.stack
    assert e.pr == 1 and e.mode is PrMode.READY and b.stage is Stage.CI


def test_the_pushed_report_goes_to_the_liaison(env: Env) -> None:
    at_push(env, entry(1))
    env.rt.state.upstream.push = bd.Permission.YES
    env.br.step()
    [text] = [t for t in posted(env) if "as built" in t]
    assert "team/sprint-1" in text and "#1" in text and "only once it is green" in text


def test_an_open_pr_is_reused_not_created(env: Env) -> None:
    env.prs.prs["team/sprint-1"] = Pr(7, "https://h/7", PrState.OPEN, False, "main")
    at_push(env, entry(1))
    env.rt.state.upstream.push = bd.Permission.YES
    env.br.step()
    assert [c for c in env.prs.calls if c[0] in ("create", "edit")] == []
    assert env.rt.state.upstream.stack[0].pr == 7


def test_an_open_draft_pr_is_made_ready(env: Env) -> None:
    env.prs.prs["team/sprint-1"] = Pr(7, "https://h/7", PrState.OPEN, True, "main")
    at_push(env, entry(1))
    env.rt.state.upstream.push = bd.Permission.YES
    env.br.step()
    [(_, number, spec)] = [c for c in env.prs.calls if c[0] == "edit"]
    assert number == 7 and spec.mode is PrMode.READY


def test_a_closed_pr_is_left_alone(env: Env) -> None:
    env.prs.prs["team/sprint-1"] = Pr(7, "https://h/7", PrState.CLOSED, False, "main")
    at_push(env, entry(1))
    env.rt.state.upstream.push = bd.Permission.YES
    env.br.step()
    assert [c for c in env.prs.calls if c[0] in ("create", "edit")] == []
    assert env.rt.state.upstream.stack[0].mode == "closed"


def test_permission_no_finishes_local_and_says_not_rebased(env: Env, fake: FakeSystem) -> None:
    at_push(env, entry(1))
    env.rt.state.upstream.push = bd.Permission.NO
    env.br.step()
    assert pushes(fake) == [] and env.prs.calls == []
    assert env.rt.state.boundary is None and env.outcomes()[-1] == "done"
    report = env.rt.state.upstream.report
    assert "checked but not pushed" in report and "not rebased onto origin/main" in report
    assert bd.NOT_REBASED.format(target="origin/main") in posted(env)[-1]


def test_no_pr_service_finishes_local_with_that_reason(env: Env, fake: FakeSystem) -> None:
    at_push(env, entry(1))
    env.prs.reason = "gh is not installed"
    env.rt.state.upstream.push = bd.Permission.YES
    env.br.step()
    assert "gh is not installed" in env.rt.state.upstream.report
    assert pushes(fake) == [] and env.rt.state.boundary is None


def test_only_the_sprints_own_branch_is_pushed(env: Env, fake: FakeSystem) -> None:
    env.rt.state.sprint = 2
    env.rt.state.upstream.push = bd.Permission.YES
    at_push(env, entry(1), entry(2))
    env.br.step()
    [argv] = pushes(fake)
    assert argv[-1].endswith("refs/heads/team/sprint-2")


def test_rejected_push_holds_and_opens_no_pr(env: Env, fake: FakeSystem) -> None:
    b = at_push(env, entry(1))
    fake.reply(("git", "push"), Done(1, "! [rejected]"))
    env.rt.state.upstream.push = bd.Permission.YES
    report = env.br.step()
    assert b.hold is BoundaryHold.PUSH_REJECTED and report["boundary"]["branch"] == "team/sprint-1"
    assert report["boundary"]["reason"] == "! [rejected]" and env.prs.calls == []
    assert len(pushes(fake)) == 1 and b.stage is Stage.PUSH


def test_a_sha_already_pushed_is_not_pushed_again(env: Env, fake: FakeSystem) -> None:
    e = entry(1, pushed=FAKE_HEAD)
    at_push(env, e)
    env.rt.state.upstream.push = bd.Permission.YES
    env.br.step()
    assert pushes(fake) == []


def test_the_end_sync_with_nothing_new_finishes_at_once(env: Env, fake: FakeSystem) -> None:
    env.rt.state.upstream.last_end = FAKE_HEAD
    env.open(Edge.END)
    env.drive()
    assert env.rt.state.boundary is None
    assert env.rt.state.upstream.report == bd.NOTHING_NEW.format(sprint=1)
    assert env.rt.state.upstream.stack == [] and pushes(fake) == []
    assert env.runner.calls == [] and env.prs.calls == []


def test_the_end_sync_supersedes_older_entries(env: Env) -> None:
    older = entry(0, pr=12)
    env.rt.state.upstream.stack = [older]
    env.rt.state.upstream.last_end = OLD
    env.open(Edge.END)
    env.br.step()
    [own] = env.rt.state.upstream.stack
    assert own.sprint == 1 and own.supersedes == [12]
    assert "superseded" in env.outcomes()
    assert not [c for c in env.prs.calls if c[0] not in ("find",)]


def test_a_superseded_entry_without_a_pr_adds_no_number(env: Env) -> None:
    env.rt.state.upstream.stack = [entry(0)]
    env.rt.state.upstream.last_end = OLD
    env.open(Edge.END)
    env.br.step()
    [own] = env.rt.state.upstream.stack
    assert own.supersedes == []


def test_the_pr_body_names_the_superseded_prs(env: Env) -> None:
    env.rt.state.upstream.stack = [entry(0, pr=12), entry(-1, pr=13)]
    env.rt.state.upstream.last_end = OLD
    env.rt.state.upstream.push = bd.Permission.YES
    env.open(Edge.END)
    env.drive()
    [(_, spec)] = [c for c in env.prs.calls if c[0] == "create"]
    assert "#12, #13" in spec.body and "Rebase and merge" in spec.body


def test_open_end_when_the_sprint_is_complete(env: Env) -> None:
    assert env.br.open_end() is True
    assert env.rt.state.boundary.edge is Edge.END and env.rt.state.boundary.sprint == 1


def test_open_end_is_false_when_closed_or_pending_or_unfinished(env: Env) -> None:
    env.rt.state.upstream.closed = 1
    assert env.br.open_end() is False
    env.rt.state.upstream.closed = 0
    env.rt.state.stories["s1"].status = StoryStatus.ACTIVE
    assert env.br.open_end() is False
    env.rt.state.stories["s1"].status = StoryStatus.DONE
    env.open(Edge.START)
    assert env.br.open_end() is False


def test_due_is_none_without_a_boundary_and_a_boundary_step_otherwise(env: Env) -> None:
    assert env.br.due() is None
    env.open(Edge.START)
    assert env.br.due() == bd.Due(StepKind.BOUNDARY, "runner", "")
