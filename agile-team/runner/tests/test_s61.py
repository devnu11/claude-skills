"""s61: the runner halts when the checkout changes under it (K1-K10)."""

import asyncio
import json
import os
import subprocess
from dataclasses import asdict
from importlib import resources
from pathlib import Path

import pytest
from agile_team import checkout, cli, events, halt, po_tools, recovery, router
from agile_team import state as state_mod
from agile_team.dispatch import StepRequest
from agile_team.git_ops import Git
from agile_team.halt import Halt, HaltKind
from agile_team.po_tools import PoRun, Start, Tools
from agile_team.relay import Note
from agile_team.salvage import Cause
from agile_team.state import CheckoutRecord, RunState, RunStatus

from .conftest import FakeQuery, FakeRunner, git
from .pipeline_helpers import Script, add_story, build
from .test_cli import any_tool, start_args
from .test_halt import notes
from .test_s9 import STEP, dirty, run_dir_of

TEST_CMD = "pytest"
DESIGN = "docs/architecture.md"


def sha7(repo: Path) -> str:
    return git(repo, "rev-parse", "--short=7", "HEAD").strip()


def refs(repo: Path) -> str:
    return git(repo, "log", "--all", "--format=%H")


def commit_file(repo: Path, name: str = "foreign.txt") -> None:
    (repo / name).write_text("x\n")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"foreign {name}")


def write_design(repo: Path, text: str) -> None:
    """Write the design file, creating ``docs/`` (the scratch repo has none)."""
    (repo / DESIGN).parent.mkdir(exist_ok=True)
    (repo / DESIGN).write_text(text)


def detach(repo: Path) -> None:
    git(repo, "checkout", "-q", "--detach")


def switch(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "other")


def reset(repo: Path) -> None:
    git(repo, "reset", "-q", "--hard", "HEAD~1")


def start_rebase(repo: Path) -> None:
    """A rebase stopped on a conflict; HEAD is detached, a rebase is in progress."""
    git(repo, "checkout", "-q", "-b", "other", "HEAD~1")
    (repo / "src" / "app.py").write_text("x = 3\n")
    git(repo, "commit", "-q", "-am", "theirs")
    subprocess.run(["git", "rebase", "main"], cwd=repo, capture_output=True, check=False)


def with_two_commits(repo: Path) -> None:
    (repo / "src" / "app.py").write_text("x = 2\n")
    git(repo, "commit", "-q", "-am", "two")


CASES = {
    "detached": detach,
    "switched": switch,
    "reset": reset,
    "foreign-commit": commit_file,
    "rebase": start_rebase,
}


def open_checkout_questions(rt):
    return [m for m in rt.relay.open_questions() if m.text.startswith(checkout.CHECKOUT_HEAD)]


# ----- state, halt, dashboard table -------------------------------------------------


def test_record_text() -> None:
    assert CheckoutRecord("main", "a" * 40).text() == "main at aaaaaaa"


def test_status_value_and_halted() -> None:
    assert RunStatus("checkout-changed") is RunStatus.CHECKOUT_CHANGED
    assert RunState(status=RunStatus.CHECKOUT_CHANGED).halted()
    assert not RunState(status=RunStatus.RUNNING).halted()


def test_legacy_state_loads_without_checkout(tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text(json.dumps({"status": "idle"}))
    assert state_mod.load(tmp_path).checkout is None


def test_checkout_round_trips(tmp_path: Path) -> None:
    state_mod.save(tmp_path, RunState(checkout=CheckoutRecord("main", "f" * 40)))
    assert state_mod.load(tmp_path).checkout == CheckoutRecord("main", "f" * 40)


def test_halt_table_and_budget_advice() -> None:
    assert halt.HALTS[HaltKind.CHECKOUT] == halt.HaltRule(
        RunStatus.CHECKOUT_CHANGED, "question", 78, halt.CHECKOUT_ADVICE
    )
    assert (
        f"put the checkout back, or keep it with `agile-team accept-checkout`, then {halt.RESUME}"
    ) == halt.CHECKOUT_ADVICE
    assert halt.BUDGET_ADVICE == (
        "raise team.budget_usd in .agile-team.toml and commit it, run "
        "`agile-team accept-checkout`, then run `agile-team start --resume`"
    )
    assert Cause("checkout") is Cause.CHECKOUT
    assert events.EventKind.CHECKOUT.value == "checkout"


def test_dashboard_shows_the_status_red() -> None:
    page = resources.files("agile_team.dashboard").joinpath("index.html").read_text()
    assert '"checkout-changed": "critical"' in page


# ----- checkout.py units -------------------------------------------------------------


def test_read_attached_and_detached(configured: Path) -> None:
    g = Git(configured)
    found = checkout.read(g)
    assert (found.branch, found.head, found.operation) == ("main", g.head(), None)
    detach(configured)
    assert checkout.read(g).branch is None


@pytest.mark.parametrize(("path", "name"), checkout.OPERATIONS)
def test_read_names_each_operation(configured: Path, path: str, name: str) -> None:
    git_dir = Path(git(configured, "rev-parse", "--absolute-git-dir").strip())
    (git_dir / path).write_text("x")
    assert checkout.read(Git(configured)).operation == name
    assert checkout.operation(Git(configured)) == name


def test_operation_is_none_on_a_clean_repo(configured: Path) -> None:
    assert checkout.operation(Git(configured)) is None


def found(branch="main", head="a" * 40, operation=None) -> checkout.Found:
    return checkout.Found(branch, head, operation)


def test_matches_table() -> None:
    rec = CheckoutRecord("main", "a" * 40)
    assert checkout.matches(None, found())
    assert not checkout.matches(None, found(branch=None))
    assert not checkout.matches(None, found(operation="rebase"))
    assert checkout.matches(rec, found())
    assert not checkout.matches(rec, found(branch="other"))
    assert not checkout.matches(rec, found(head="b" * 40))
    assert not checkout.matches(rec, found(operation="merge"))


def test_found_text() -> None:
    assert found().text() == "main at aaaaaaa"
    assert found(branch=None).text() == "detached HEAD at aaaaaaa"
    assert found(operation="rebase").text() == "main at aaaaaaa with a rebase in progress"


def reason(expected, now, move="m") -> str:
    return checkout.Drift(expected, now, move).reason()


def test_drift_reason_exact() -> None:
    rec = CheckoutRecord("main", "a" * 40)
    assert reason(rec, found(branch=None, head="b" * 40), "HEAD@{1} checkout: x") == (
        "checkout changed: expected main at aaaaaaa; found detached HEAD at bbbbbbb; "
        "last HEAD move: HEAD@{1} checkout: x"
    )
    assert reason(None, found(branch=None)) == (
        "checkout changed: expected a branch with no git operation in progress; "
        "found detached HEAD at aaaaaaa; last HEAD move: m"
    )
    assert reason(rec, found(operation="rebase"), checkout.NO_MOVE) == (
        "checkout changed: expected main at aaaaaaa; found main at aaaaaaa "
        "with a rebase in progress; last HEAD move: no reflog entry"
    )
    assert reason(rec, found(branch="other")).startswith(
        "checkout changed: expected main at aaaaaaa; found other at aaaaaaa;"
    )


def test_drift_halt_is_a_checkout_halt() -> None:
    drift = checkout.Drift(None, found(branch=None), "m")
    assert drift.halt() == Halt(HaltKind.CHECKOUT, drift.reason())


def test_last_move_names_the_checkout(configured: Path) -> None:
    detach(configured)
    assert "checkout: moving from main to" in checkout.last_move(Git(configured))


def test_last_move_without_a_reflog_entry(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q")
    assert checkout.last_move(Git(empty)) == checkout.NO_MOVE


def test_check_none_when_matching_and_drift_when_not(configured: Path) -> None:
    g = Git(configured)
    rec = checkout.recorded(g)
    assert rec == CheckoutRecord("main", g.head())
    assert checkout.check(g, rec) is None
    detach(configured)
    drift = checkout.check(g, rec)
    assert drift and drift.found.branch is None and "checkout: moving" in drift.move


def test_recorded_on_a_detached_head_never_matches(configured: Path) -> None:
    detach(configured)
    g = Git(configured)
    assert checkout.recorded(g).branch == ""
    assert checkout.check(g, checkout.recorded(g)) is not None


def test_answer_open_answers_only_checkout_questions(make_runtime) -> None:
    rt = make_runtime()
    mine = rt.relay.post(Note("question", checkout.CHECKOUT_HEAD + "x"))
    other = rt.relay.post(Note("question", "Which DB?"))
    checkout.answer_open(rt.relay, "restored: main at abc1234")
    answers = rt.relay.answers()
    assert answers[mine.id].text == "restored: main at abc1234" and other.id not in answers


# ----- Runtime: record, then change, then run a step --------------------------------


def armed(make_runtime, query=None, before=None):
    """A runtime whose record matches the repo; ``before`` changes the repo after recording."""
    rt = make_runtime(query or FakeQuery(action=lambda: pytest.fail("a step ran")))
    repo = rt.config.repo
    if before is with_two_commits or before is reset:
        with_two_commits(repo)
    rt.record_checkout()
    return rt


def step(rt, role="architect"):
    return asyncio.run(rt.run_role(StepRequest(role, "go")))


@pytest.mark.parametrize("case", CASES)
def test_a_changed_checkout_halts_before_the_step(make_runtime, case: str) -> None:
    rt = armed(make_runtime, before=CASES[case])
    repo = rt.config.repo
    CASES[case](repo)
    before = refs(repo)
    report = step(rt)
    assert report["status"] == "halted" and report["role"] == "architect"
    assert report["reason"].startswith(checkout.CHECKOUT_HEAD)
    assert report["next"] == "the run is stopping; end your turn"
    assert rt.state.status is RunStatus.CHECKOUT_CHANGED
    assert rt.state.status_reason == report["reason"]
    [question] = open_checkout_questions(rt)
    assert question.text == Halt(HaltKind.CHECKOUT, report["reason"]).message()
    assert refs(repo) == before
    kinds = {e.kind for e in rt.events.events()}
    assert not kinds & {"quarantine", "gate", "step-end"}
    assert not (rt.config.run_dir / halt.CRASH_LOG).exists()
    assert state_mod.load(rt.config.run_dir).status is RunStatus.CHECKOUT_CHANGED


def test_the_halt_posts_one_question_and_later_steps_are_refused(make_runtime) -> None:
    rt = armed(make_runtime)
    detach(rt.config.repo)
    step(rt)
    again = step(rt)
    assert again["status"] == "refused"
    assert again["reason"].startswith("the run is checkout-changed (checkout changed: ")
    assert len(notes(rt)) == 1


def test_a_move_during_the_step_halts_without_committing(make_runtime) -> None:
    holder: list = []

    def act() -> None:
        write_design(holder[0].config.repo, "design\n")
        detach(holder[0].config.repo)

    rt = make_runtime(FakeQuery(cost=0.25, action=act))
    holder.append(rt)
    rt.record_checkout()
    before = refs(rt.config.repo)
    report = step(rt)
    assert report["status"] == "halted"
    assert rt.ledger.total() == pytest.approx(0.25)
    assert (rt.config.repo / DESIGN).read_text() == "design\n"
    assert not Git(rt.config.repo).is_clean()
    assert refs(rt.config.repo) == before
    assert rt.state.in_flight is not None
    assert not (rt.config.run_dir / halt.CRASH_LOG).exists()
    assert rt.state.status is RunStatus.CHECKOUT_CHANGED


def test_a_move_between_commit_and_gate_halts_the_gate(make_runtime, monkeypatch) -> None:
    rt = make_runtime(FakeQuery(action=lambda: write_design(rt.config.repo, "d\n")))
    rt.state.sprint = 1
    add_story(rt, "s1", "design")
    rt.record_checkout()
    real = rt.settle_tree

    def settle_then_move(plan):
        out = real(plan)
        detach(rt.config.repo)
        return out

    monkeypatch.setattr(rt, "settle_tree", settle_then_move)
    called = []
    monkeypatch.setattr(rt.pipeline, "evaluate", lambda *a: called.append(a))
    report = asyncio.run(rt.run_role(StepRequest("architect", "go", "s1")))
    assert report["status"] == "halted" and called == []
    assert rt.state.status is RunStatus.CHECKOUT_CHANGED


def test_save_interrupted_is_a_no_op_on_a_moved_checkout(make_runtime) -> None:
    rt = armed(make_runtime)
    rt.state.in_flight = STEP
    dirty(rt.config.repo)
    detach(rt.config.repo)
    before = refs(rt.config.repo)
    assert rt.save_interrupted(Cause.ERROR) is None
    assert refs(rt.config.repo) == before and rt.state.interrupted == []


def test_save_interrupted_on_a_match_saves_and_records(make_runtime) -> None:
    rt = armed(make_runtime)
    rt.state.in_flight = STEP
    dirty(rt.config.repo)
    saved = rt.save_interrupted(Cause.LIMIT)
    assert saved and saved.sha
    live = checkout.recorded(rt.git)
    assert rt.state.checkout == live
    assert state_mod.load(rt.config.run_dir).checkout == live


def test_a_normal_step_moves_the_record_to_its_commit(make_runtime) -> None:
    rt = make_runtime(FakeQuery(action=lambda: write_design(rt.config.repo, "d\n")))
    rt.record_checkout()
    old = rt.state.checkout.head
    report = step(rt)
    assert report["commit"] and rt.git.head() != old
    assert rt.state.checkout == CheckoutRecord("main", rt.git.head())
    assert state_mod.load(rt.config.run_dir).checkout.head == rt.git.head()


def test_the_first_passing_check_records_the_live_checkout(make_runtime) -> None:
    rt = make_runtime(FakeQuery())
    assert rt.state.checkout is None
    assert rt.checkout_moved() is None
    assert rt.state.checkout == CheckoutRecord("main", rt.git.head())


def test_the_first_check_halts_on_a_detached_head_without_a_record(make_runtime) -> None:
    rt = make_runtime(FakeQuery())
    detach(rt.config.repo)
    found_halt = rt.checkout_moved()
    assert found_halt and found_halt.kind is HaltKind.CHECKOUT
    assert rt.state.status is RunStatus.CHECKOUT_CHANGED and rt.state.checkout is None


def test_verify_checkout_raises_with_the_halt(make_runtime) -> None:
    rt = armed(make_runtime)
    detach(rt.config.repo)
    with pytest.raises(checkout.CheckoutChanged) as caught:
        rt.verify_checkout()
    assert caught.value.halt.kind is HaltKind.CHECKOUT


# ----- Router, PoRun, pass_tests, boundary, recovery ---------------------------------


def test_a_move_during_a_wait_poll_halts_the_run(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1", "implement")
    rt.relay.post(Note("question", "Which DB?", ["s1"]))
    rt.state.delivered = []
    rt.record_checkout()

    async def sleep(_s: float) -> None:
        detach(rt.config.repo)

    asyncio.run(router.Router(rt, sleep=sleep).advance())
    assert rt.state.status is RunStatus.CHECKOUT_CHANGED
    assert rt.halted_by and rt.halted_by.kind is HaltKind.CHECKOUT


def test_a_move_before_a_po_turn_means_no_po_query(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script)
    rt.record_checkout()
    detach(rt.config.repo)
    asyncio.run(po_tools.run_po(rt, Start("go")))
    assert script.po_prompts == []
    assert rt.state.status is RunStatus.CHECKOUT_CHANGED


def test_a_move_during_the_po_turn_halts_at_settle_with_no_commit(make_runtime) -> None:
    async def move(rt) -> None:
        write_design(rt.config.repo, "po edit\n")
        detach(rt.config.repo)

    script = Script(po=[move])
    rt = build(make_runtime, script)
    rt.record_checkout()
    before = refs(rt.config.repo)
    asyncio.run(PoRun(rt, Start("go")).run())
    assert refs(rt.config.repo) == before
    assert rt.state.status is RunStatus.CHECKOUT_CHANGED
    assert not (rt.config.run_dir / halt.CRASH_LOG).exists()


def test_pass_tests_on_a_moved_checkout_runs_no_gate(make_runtime) -> None:
    runner = FakeRunner({TEST_CMD: (0, "ok")})
    rt = make_runtime(runner=runner)
    rt.state.sprint = 1
    add_story(rt, "s1", "tests")
    rt.record_checkout()
    detach(rt.config.repo)
    out = asyncio.run(Tools(rt).pass_tests({"story": "s1", "reason": "r"}))
    report = json.loads(out["content"][0]["text"])
    assert report["status"] == "halted" and report["reason"].startswith(checkout.CHECKOUT_HEAD)
    assert runner.calls == [] and rt.state.stories["s1"].step == "tests"


def test_recover_killed_records_the_head_after_its_salvage(configured: Path) -> None:
    run_dir = run_dir_of(configured)
    dirty(configured)
    state_mod.save(run_dir, RunState(status=RunStatus.RUNNING, in_flight=STEP))
    recovery.recover_killed(run_dir, Git(configured))
    saved = state_mod.load(run_dir)
    assert saved.checkout == CheckoutRecord("main", Git(configured).head())


# ----- CLI --------------------------------------------------------------------------


def stored(repo: Path, **kw) -> Path:
    run_dir = run_dir_of(repo)
    state_mod.save(run_dir, RunState(checkout=checkout.recorded(Git(repo)), **kw))
    return run_dir


def test_resume_on_a_changed_checkout_exits_78(
    configured: Path, key_home: Path, capsys, monkeypatch
) -> None:
    any_tool(monkeypatch)
    run_dir = stored(configured, status=RunStatus.RUNNING, in_flight=STEP)
    (run_dir / state_mod.PID_FILE).write_text("999999999")
    dirty(configured)
    detach(configured)
    before = refs(configured)
    q = FakeQuery()
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), q) == 78
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1
    assert err[0].startswith("agile-team start: checkout changed: expected main at ")
    assert err[0].endswith(halt.CHECKOUT_ADVICE)
    saved = state_mod.load(run_dir)
    assert saved.status is RunStatus.CHECKOUT_CHANGED and saved.interrupted == []
    assert q.calls == [] and refs(configured) == before
    # a second resume exits 78 again, with still one open question
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), q) == 78
    from agile_team.relay import Relay

    assert len(Relay(run_dir).open_questions()) == 1


def test_restoring_the_branch_resumes_and_answers_the_question(
    configured: Path, key_home: Path, monkeypatch
) -> None:
    from agile_team.relay import Relay

    any_tool(monkeypatch)
    run_dir = stored(configured)
    detach(configured)
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery()) == 78
    git(configured, "checkout", "-q", "main")
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery()) == 0
    [(_, answer)] = Relay(run_dir).answers().items()
    assert answer.text == f"restored: main at {sha7(configured)}"


def accept_args(repo: Path, home: Path) -> list[str]:
    return ["--repo", str(repo), "--home", str(home), "accept-checkout"]


def test_accept_checkout_keeps_the_new_head(
    configured: Path, key_home: Path, capsys, monkeypatch
) -> None:
    from agile_team.relay import Relay

    any_tool(monkeypatch)
    run_dir = stored(configured, status=RunStatus.IDLE)
    old = state_mod.load(run_dir).checkout
    commit_file(configured)
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery()) == 78
    capsys.readouterr()
    assert cli.main(accept_args(configured, key_home)) == 0
    new = CheckoutRecord("main", Git(configured).head())
    assert capsys.readouterr().out.strip() == f"accepted checkout main at {sha7(configured)}"
    saved = state_mod.load(run_dir)
    assert saved.checkout == new and saved.status is RunStatus.STOPPED
    assert saved.status_reason == (
        f"checkout accepted: main at {sha7(configured)}; run `agile-team start --resume`"
    )
    log = events.EventLog(run_dir / events.EVENTS)
    [event] = [e for e in log.events() if e.kind == "checkout"]
    assert event.data == {"action": "accepted", "from": asdict(old), "to": asdict(new)}
    [(_, answer)] = Relay(run_dir).answers().items()
    assert answer.text == f"accepted: main at {sha7(configured)}"
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery()) == 0


def test_accept_leaves_another_status_alone(configured: Path, key_home: Path) -> None:
    run_dir = stored(configured, status=RunStatus.BLOCKED)
    commit_file(configured)
    assert cli.main(accept_args(configured, key_home)) == 0
    assert state_mod.load(run_dir).status is RunStatus.BLOCKED


def test_accept_refuses_a_live_runner(configured: Path, key_home: Path, capsys) -> None:
    run_dir = stored(configured, status=RunStatus.RUNNING)
    (run_dir / state_mod.PID_FILE).write_text(str(os.getpid()))
    commit_file(configured)
    before = state_mod.load(run_dir)
    assert cli.main(accept_args(configured, key_home)) == 1
    assert capsys.readouterr().err.strip() == (
        "agile-team accept-checkout: the runner is running; stop it first"
    )
    assert state_mod.load(run_dir) == before


def test_accept_refuses_a_detached_head(configured: Path, key_home: Path, capsys) -> None:
    run_dir = stored(configured)
    detach(configured)
    before = state_mod.load(run_dir)
    assert cli.main(accept_args(configured, key_home)) == 1
    assert capsys.readouterr().err.strip() == (
        f"agile-team accept-checkout: cannot accept detached HEAD at {sha7(configured)}: "
        "check out the team branch and finish or abort any git operation first"
    )
    assert state_mod.load(run_dir) == before


def test_status_json_has_the_checkout(configured: Path, capsys) -> None:
    stored(configured)
    assert cli.main(["--repo", str(configured), "status"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["checkout"] == {"branch": "main", "head": Git(configured).head()}


def test_status_checkout_is_null_without_a_record(configured: Path, capsys) -> None:
    assert cli.main(["--repo", str(configured), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["checkout"] is None


def test_accept_checkout_is_a_registered_command() -> None:
    assert "accept-checkout" in [c.name for c in cli.COMMANDS]
