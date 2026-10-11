"""s29 U1-U22: the BoundaryRunner over scratch origins, a fake PR service and fake checks."""

import json
from pathlib import Path

import pytest
from agile_team import boundary as bd
from agile_team.boundary import BoundaryHold, Edge, Stage, StepKind
from agile_team.boundary_runner import BoundaryRunner
from agile_team.events import EventKind
from agile_team.gates import StoryState, StoryStatus
from agile_team.upstream import PrMode, PrState

from .conftest import FakeRunner, git
from .s29_helpers import FakePrs, commit, land_upstream, make_origin, rev

GOOD_COVERAGE = "TOTAL 100 0 100%"
GREEN = {"pytest --cov": (0, GOOD_COVERAGE)}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Override: the team repo is a clone of a scratch bare origin."""
    return make_origin(tmp_path)[1]


@pytest.fixture
def origin(tmp_path: Path, repo: Path) -> Path:
    return tmp_path / "origin.git"


class Env:
    """A runtime, its fake checks and PR service, and the BoundaryRunner under test."""

    def __init__(self, make_runtime, results=None):
        self.runner = FakeRunner(results or GREEN)
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


def test_no_remote_skips_the_start_boundary(env: Env) -> None:
    git(env.rt.config.repo, "remote", "remove", "origin")
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


def test_skip_at_the_end_closes_the_sprint_with_the_skipped_report(env: Env) -> None:
    git(env.rt.config.repo, "remote", "remove", "origin")
    env.open(Edge.END)
    env.drive()
    up = env.rt.state.upstream
    assert up.closed == 1 and env.rt.state.boundary is None
    assert up.report == bd.SKIPPED_REPORT.format(why="no remote 'origin'")


def test_fetch_failure_at_the_end_still_adds_the_entry(env: Env, tmp_path: Path) -> None:
    commit(env.rt.config.repo, "mine.txt")
    git(env.rt.config.repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    env.open(Edge.END)
    env.drive()
    [entry] = env.rt.state.upstream.stack
    assert entry.sprint == 1 and entry.end == rev(env.rt.config.repo, "HEAD")
    assert env.events()[0].data["outcome"] == "skipped"


# ----- U5 start sync --------------------------------------------------------


def test_start_merges_upstream_then_checks_and_finishes(
    env: Env, tmp_path: Path, origin: Path
) -> None:
    mine = commit(env.rt.config.repo, "mine.txt")
    land_upstream(tmp_path, origin, "theirs.txt")
    env.open(Edge.START)
    env.drive()
    assert env.outcomes() == ["merged", "pass", "done"]
    assert env.events()[0].data["sha"] == rev(env.rt.config.repo, "HEAD")
    assert env.rt.state.upstream.team_branch == "agile-team"
    assert env.rt.state.boundary is None
    assert git(env.rt.config.repo, "merge-base", "--is-ancestor", mine, "HEAD") == ""
    assert env.rt.state.upstream.stack == []


def test_start_with_nothing_new_is_current_with_no_commit(env: Env) -> None:
    before = rev(env.rt.config.repo, "HEAD")
    env.open(Edge.START)
    env.drive()
    assert env.outcomes()[0] == "current" and rev(env.rt.config.repo, "HEAD") == before
    assert env.rt.state.boundary is None


def test_start_conflict_holds_with_the_files_and_leaves_the_branch(
    env: Env, tmp_path: Path, origin: Path
) -> None:
    repo = env.rt.config.repo
    commit(repo, "base.txt", "mine\n")
    land_upstream(tmp_path, origin, "base.txt", "theirs\n")
    before = rev(repo, "HEAD")
    env.open(Edge.START)
    [report] = env.drive()
    b = env.rt.state.boundary
    assert b.hold is BoundaryHold.SYNC_CONFLICT and report["boundary"]["hold"] == "sync_conflict"
    assert report["boundary"]["files"] == ["base.txt"] and rev(repo, "HEAD") == before
    assert env.br.due() is None
    assert not (repo / ".git" / "MERGE_HEAD").exists()


def test_detached_head_is_an_error_hold(env: Env) -> None:
    git(env.rt.config.repo, "checkout", "-q", "--detach")
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
    assert "shell exploded" in (env.rt.config.run_dir / "crash.log").read_text()
    assert env.br.due() is None


# ----- U7/U9/U11/U12 check, fix, escalate -----------------------------------


def fail_lint(env: Env, text: str = "E501 line too long") -> None:
    env.runner.results = {**GREEN, "ruff check .": (1, text)}


def test_team_check_pass_records_head_and_a_second_check_is_skipped(env: Env) -> None:
    env.open(Edge.START, stage=Stage.CHECK)
    env.drive()
    head = rev(env.rt.config.repo, "HEAD")
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
    assert report["boundary"]["checks"][0] == {"name": "lint", "passed": False, "why": "exit 1"}
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


# ----- U15-U18 review and push ---------------------------------------------


def end_with_commits(env: Env) -> bd.Boundary:
    commit(env.rt.config.repo, "feat.txt")
    return env.open(Edge.END)


def test_end_adds_an_entry_builds_the_branch_and_asks_for_push_permission(
    env: Env, origin: Path
) -> None:
    repo = env.rt.config.repo
    head = commit(repo, "feat.txt")
    env.open(Edge.END)
    env.drive()
    b = env.rt.state.boundary
    [entry] = env.rt.state.upstream.stack
    assert (entry.sprint, entry.branch, entry.end, entry.stories) == (
        1,
        "team/sprint-1",
        head,
        ["s1"],
    )
    assert entry.start == rev(repo, "origin/main") and entry.check is bd.CheckState.PASS
    assert (
        git(repo, "rev-list", "--count", "origin/main..team/sprint-1").strip() == "3"
    )  # feat + 2 setup
    assert rev(repo, "agile-team") == head
    assert b.stage is Stage.PUSH and b.hold is BoundaryHold.PUSH_PERMISSION
    assert env.events()[-1].data["outcome"] == "held" and env.events()[-1].data["branches"] == [
        "team/sprint-1"
    ]
    assert env.rt.state.upstream.last_end == head
    assert env.prs.calls == []
    assert git(origin, "branch", "--list", "team/*").strip() == ""
    assert entry.title == bd.SPRINT_TITLE.format(sprint=1, goal=env.rt.state.goal)


def release_push(env: Env, answer: str) -> None:
    env.rt.state.upstream.push = bd.Permission(answer)
    env.rt.state.boundary.hold = None


def test_permission_yes_pushes_branches_and_opens_pull_requests(env: Env, origin: Path) -> None:
    end_with_commits(env)
    env.drive()
    release_push(env, "yes")
    env.drive()
    repo = env.rt.config.repo
    assert rev(origin, "team/sprint-1") == rev(repo, "team/sprint-1")
    [entry] = env.rt.state.upstream.stack
    assert (
        entry.pushed == entry.head
        and entry.pr == 1
        and entry.mode is PrMode.READY
        and entry.base == "main"
    )
    [(verb, spec)] = env.prs.calls
    assert verb == "create" and spec.base == "main" and spec.mode is PrMode.READY
    assert (
        spec.title == entry.title
        and "Rebase and merge" in spec.body
        and "Stacked on" not in spec.body
    )
    up = env.rt.state.upstream
    assert env.rt.state.boundary is None and up.closed == 1
    assert up.report.startswith("Sprint 1 is up for review: #1 (ready, team/sprint-1)")
    assert env.outcomes()[-2:] == ["pushed", "done"]
    assert any(m.kind == "update" and m.text == up.report for m in env.rt.relay.messages())
    assert rev(origin, "main") == rev(repo, "origin/main")


def test_permission_no_builds_locally_and_reports(env: Env, origin: Path) -> None:
    end_with_commits(env)
    env.rt.state.upstream.push = bd.Permission.NO
    env.drive()
    up = env.rt.state.upstream
    assert env.rt.state.boundary is None and up.closed == 1
    assert up.report.startswith("Sprint 1's review branches are built and checked but not pushed")
    assert bd.NOT_PERMITTED in up.report and "team/sprint-1" in up.report
    assert git(origin, "branch", "--list", "team/*").strip() == "" and env.prs.calls == []
    assert any(m.text == up.report for m in env.rt.relay.messages())
    assert env.outcomes()[-2:] == ["local", "done"]


def test_no_pr_service_is_local_with_that_reason(env: Env, origin: Path) -> None:
    end_with_commits(env)
    env.prs.reason = "gh is not installed"
    env.rt.state.upstream.push = bd.Permission.YES
    env.drive()
    assert "gh is not installed" in env.rt.state.upstream.report
    assert git(origin, "branch", "--list", "team/*").strip() == ""


def test_second_sprint_stacks_drafts_and_pushes_without_asking_again(
    env: Env, origin: Path
) -> None:
    repo = env.rt.config.repo
    env.rt.state.upstream.push = bd.Permission.YES
    commit(repo, "one.txt")
    env.open(Edge.END)
    env.drive()
    env.rt.state.sprint = 2
    env.rt.state.stories["s2"] = StoryState("s2", "Two", "done", status=StoryStatus.DONE, sprint=2)
    commit(repo, "two.txt")
    env.open(Edge.END)
    env.drive()
    e1, e2 = env.rt.state.upstream.stack
    assert e2.start == e1.end and e2.base == "team/sprint-1" and e2.mode is PrMode.DRAFT
    assert e1.mode is PrMode.READY and e1.base == "main"
    creates = [spec for verb, spec in env.prs.calls if verb == "create"]
    assert creates[-1].mode is PrMode.DRAFT and "Stacked on team/sprint-1 (#1)" in creates[-1].body
    assert git(repo, "rev-parse", "team/sprint-2~1").strip() == e1.head
    assert rev(origin, "team/sprint-2") == rev(repo, "team/sprint-2")
    assert env.rt.state.boundary is None


def test_rerunning_the_push_edits_only_what_differs(env: Env) -> None:
    end_with_commits(env)
    env.rt.state.upstream.push = bd.Permission.YES
    env.drive()
    env.prs.calls.clear()
    env.rt.state.upstream.closed = 0
    env.open(Edge.END)
    env.drive()
    assert [c[0] for c in env.prs.calls] in ([], ["edit"])


def test_a_closed_pr_is_left_alone_with_a_note(env: Env) -> None:
    end_with_commits(env)
    env.rt.state.upstream.push = bd.Permission.YES
    env.drive()
    env.prs.set_state("team/sprint-1", PrState.CLOSED)
    env.prs.calls.clear()
    commit(env.rt.config.repo, "more.txt")
    env.rt.state.sprint = 2
    env.open(Edge.END)
    env.drive()
    assert env.rt.state.upstream.stack[0].mode is PrMode.CLOSED
    assert bd.CLOSED_NOTE.format(pr=1, sprint=1, state="closed") in [
        e.data.get("note") for e in env.events()
    ]
    assert not any(c[0] == "edit" and c[1] == 1 for c in env.prs.calls)


def test_rejected_push_holds_and_pushes_nothing_after_it(env: Env, origin: Path) -> None:
    end_with_commits(env)
    git(origin, "branch", "team/sprint-1", "main")
    env.rt.state.upstream.push = bd.Permission.YES
    [*_, report] = env.drive()
    b = env.rt.state.boundary
    assert b.hold is BoundaryHold.PUSH_REJECTED and report["boundary"]["branch"] == "team/sprint-1"
    assert report["boundary"]["reason"] and env.prs.calls == []


def test_a_rebase_merged_sprint_is_dropped_at_the_next_start(
    env: Env, tmp_path: Path, origin: Path
) -> None:
    from .s29_helpers import land_by_rebase

    repo = env.rt.config.repo
    env.rt.state.upstream.push = bd.Permission.YES
    sha = commit(repo, "one.txt")
    env.open(Edge.END)
    env.drive()
    picks = git(repo, "rev-list", "--reverse", f"origin/main..{sha}").split()  # setup + sha
    land_by_rebase(tmp_path, origin, picks, repo)
    env.rt.state.sprint = 2
    env.open(Edge.START)
    env.drive()
    assert env.rt.state.upstream.stack == []
    notes = [e.data.get("note") for e in env.events()]
    assert bd.MERGED_NOTE.format(sprint=1, target="origin/main") in notes


def test_review_conflict_asks_devops_in_the_worktree_and_rerere_replays(
    env: Env, tmp_path: Path, origin: Path
) -> None:
    repo = env.rt.config.repo
    sha = commit(repo, "base.txt", "mine\n", "feat: mine")
    land_upstream(tmp_path, origin, "base.txt", "theirs\n")
    git(repo, "fetch", "-q", "origin")
    env.open(Edge.END, stage=Stage.REVIEW)
    env.rt.state.upstream.stack = [bd.StackEntry(1, "team/sprint-1", rev(repo, "HEAD~1"), sha)]
    env.rt.state.upstream.team_branch = "agile-team"
    env.drive()
    b = env.rt.state.boundary
    assert b.failure.case is bd.FixCase.REVIEW_CONFLICT and b.failure.files == ["base.txt"]
    assert (b.failure.branch, b.failure.commit, b.failure.subject) == (
        "team/sprint-1",
        sha,
        "feat: mine",
    )
    due = env.br.due()
    assert (due.kind, due.role) == (StepKind.REVIEW_FIX, "devops") and "base.txt" in due.brief
    (env.rt.config.run_dir / "review" / "base.txt").write_text("resolved\n")
    env.br.after_fix({"role": "devops", "status": "done"})
    env.drive()
    assert git(repo, "show", "team/sprint-1:base.txt") == "resolved\n"
    assert env.rt.state.boundary.failure is None
    assert env.rt.state.boundary.rounds == 1


def test_review_check_failure_on_the_bottom_or_top_branch(env: Env) -> None:
    end_with_commits(env)

    def on_worktree(path: Path):
        return (
            FakeRunner({**GREEN, "ruff check .": (1, "bad in review")})
            if path.name == "review"
            else env.runner
        )

    env.runner_for = on_worktree
    env.drive()
    b = env.rt.state.boundary
    assert b.failure.case is bd.FixCase.REVIEW_CHECK and b.failure.branch == "team/sprint-1"
    due = env.br.due()
    assert due.kind is StepKind.TEAM_FIX and "bad in review" in due.brief
    assert env.rt.state.upstream.stack[0].check is bd.CheckState.FAIL


def test_bottom_and_top_are_each_checked_once(env: Env) -> None:
    repo = env.rt.config.repo
    seen: list[str] = []

    def spy(path: Path):
        seen.append(path.name)
        return env.runner

    env.runner_for = spy
    env.rt.state.upstream.push = bd.Permission.NO
    commit(repo, "a.txt")
    env.open(Edge.END)
    env.drive()
    assert seen.count("review") == 1


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


def test_a_sprint_start_merge_moves_the_checkout_record(
    env: Env, tmp_path: Path, origin: Path
) -> None:
    """s61 K1: the runner's own sprint-start merge updates the recorded HEAD."""
    land_upstream(tmp_path, origin, "theirs.txt")
    env.rt.record_checkout()
    old = env.rt.state.checkout.head
    env.open(Edge.START)
    env.drive()
    assert env.outcomes()[0] == "merged"
    assert env.rt.state.checkout.head == rev(env.rt.config.repo, "HEAD") != old
