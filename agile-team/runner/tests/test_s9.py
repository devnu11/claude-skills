"""s9: an interrupted step's edits are saved in a reverted commit; a dead run is not 'running'."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from agile_team import cli, events, gates, halt, po_tools, recovery, salvage
from agile_team import state as state_mod
from agile_team.dashboard import snapshot
from agile_team.dispatch import StepRequest
from agile_team.git_ops import Git, GitError
from agile_team.po_tools import Start, StartMode
from agile_team.salvage import Cause, Cut, InFlight, Interruption
from agile_team.state import RunState, RunStatus

from .conftest import FakeQuery, git
from .test_cli import any_tool, start_args
from .test_halt import (
    LIMIT_REASON,
    PoCallingRole,
    Router,
    crash_log,
    limit_error,
    notes,
)

STEP = InFlight("developer-cli", "s1", "build it\nsecond line")


def dirty(repo: Path) -> None:
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "app.py").write_text("x = 2\n")  # tracked, changed
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "new.md").write_text("new\n")  # untracked


def dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def run_dir_of(repo: Path) -> Path:
    path = repo / ".team" / "run"
    path.mkdir(parents=True, exist_ok=True)
    return path


def open_story(rt, step="design", **kw):
    rt.state.stories["s1"] = gates.StoryState("s1", "Add todo", step, sprint=1, **kw)
    return rt.state.stories["s1"]


def run_step(rt, role="architect", brief="go", story="s1"):
    return asyncio.run(rt.run_role(StepRequest(role, brief, story)))


# ----- salvage: pure helpers ---------------------------------------------------------


def test_label_with_and_without_story() -> None:
    assert salvage.label("developer-cli", "s1") == "developer-cli on s1"
    assert salvage.label("manager", None) == "manager"


def test_cause_values_and_run_ending() -> None:
    assert {c.value for c in Cause} == {"error", "limit", "crash", "sigterm", "killed"}
    assert frozenset(Cause) - {Cause.ERROR} == salvage.RUN_ENDING
    for kind in halt.HaltKind:
        assert Cause(kind.value)


def test_po_turn_constant() -> None:
    assert InFlight("product-owner", None, "the PO's own turn") == salvage.PO_TURN


def test_interruption_turns_loaded_cause_into_enum() -> None:
    found = Interruption("r", "s1", "b", "limit", "abc")  # type: ignore[arg-type]
    assert found.cause is Cause.LIMIT and found.label == "r on s1"


def test_note_suffix() -> None:
    found = Interruption("developer-cli", "s7", "b", Cause.LIMIT, "3f2a")
    assert salvage.note_suffix(found) == (
        "; developer-cli on s7's edits are saved in 3f2a (git cherry-pick -n 3f2a)"
    )
    assert salvage.note_suffix(None) == ""
    assert salvage.note_suffix(Interruption("r", None, "b", Cause.LIMIT, None)) == ""


def test_offer_text_is_exact() -> None:
    found = Interruption("developer-cli", "s1", "b", Cause.KILLED, "abc123")
    assert salvage.offer(found) == (
        "Interrupted work: an earlier developer-cli on s1 step was cut off (killed). "
        "Its edits are saved in commit abc123 and reverted. "
        "Reuse them with `git cherry-pick -n abc123` and check them before you build "
        "on them; files outside your write scope are quarantined again."
    )


def test_resume_section_empty_and_filled() -> None:
    assert salvage.resume_section([]) == ""
    a = Interruption("developer-cli", "s1", "one\ntwo", Cause.LIMIT, "abc")
    b = Interruption("manager", None, "m", Cause.KILLED, None)
    text = salvage.resume_section([a, b])
    assert text.startswith(
        "## Interrupted steps\n\nThe runner saved each cut-off step's edits in a commit "
        "and reverted it.\n\n- "
    )
    tail = text.split("\n\n")[-1]
    assert (
        "- developer-cli on s1 (limit): edits saved in abc; reuse with `git cherry-pick -n abc`"
        in text
    )
    assert "Brief: one\n    two" in text
    assert "- manager (killed): no edits\n  Brief: m" in text
    assert tail.startswith("Re-run each step.")


# ----- salvage: save_tree / capture (I3, I4) -----------------------------------------


def test_save_tree_commits_everything_then_reverts(configured: Path) -> None:
    dirty(configured)
    g = Git(configured)
    before = g.head()
    sha = salvage.save_tree(g, Cut(Cause.LIMIT, STEP))
    assert sha and g.is_clean()
    assert g.subject(sha) == "chore(team): interrupted step by developer-cli on s1"
    assert "cause: limit" in git(configured, "log", "-1", "--format=%B", sha)
    names = git(configured, "show", "--name-only", "--format=", sha).split()
    assert sorted(names) == ["docs/new.md", "src/app.py"]
    assert git(configured, "rev-list", "--count", f"{before}..HEAD").strip() == "2"
    assert (configured / "src" / "app.py").read_text() == "x = 1\n"
    assert not (configured / "docs" / "new.md").exists()


def test_save_tree_clean_returns_none(configured: Path) -> None:
    g = Git(configured)
    head = g.head()
    assert salvage.save_tree(g, Cut(Cause.ERROR, STEP)) is None
    assert g.head() == head


def test_capture_nothing_when_idle_and_clean(configured: Path) -> None:
    assert salvage.capture(Git(configured), Cut(Cause.LIMIT, None)) is None


def test_capture_in_flight_clean_has_no_sha(configured: Path) -> None:
    found = salvage.capture(Git(configured), Cut(Cause.CRASH, STEP))
    assert found == Interruption("developer-cli", "s1", STEP.brief, Cause.CRASH, None)


def test_capture_dirty_without_step_is_the_po(configured: Path) -> None:
    dirty(configured)
    found = salvage.capture(Git(configured), Cut(Cause.SIGTERM, None))
    assert found is not None and found.sha
    assert (found.role, found.story) == ("product-owner", None)


# ----- state (I7, I12, I13, I15) -----------------------------------------------------


def test_interrupt_records_by_cause() -> None:
    st = RunState(in_flight=STEP)
    st.stories["s1"] = gates.StoryState("s1", "t", "design")
    limit = Interruption("developer-cli", "s1", "b", Cause.LIMIT, "abc")
    st.interrupt(limit)
    assert st.in_flight is None and st.interrupted == [limit]
    assert st.stories["s1"].interrupted == limit


def test_interrupt_error_is_not_listed_for_the_po() -> None:
    st = RunState()
    st.stories["s1"] = gates.StoryState("s1", "t", "design")
    err = Interruption("architect", "s1", "b", Cause.ERROR, "abc")
    st.interrupt(err)
    assert st.interrupted == [] and st.stories["s1"].interrupted == err


def test_interrupt_without_sha_keeps_earlier_offer() -> None:
    st = RunState()
    st.stories["s1"] = gates.StoryState("s1", "t", "design")
    first = Interruption("architect", "s1", "b", Cause.ERROR, "abc")
    st.interrupt(first)
    st.interrupt(Interruption("architect", "s1", "b", Cause.LIMIT, None))
    assert st.stories["s1"].interrupted == first


def test_interrupt_unknown_story_is_fine() -> None:
    st = RunState()
    st.interrupt(Interruption("architect", "zz", "b", Cause.LIMIT, "abc"))
    assert len(st.interrupted) == 1


def test_runner_pid_cases(tmp_path: Path) -> None:
    assert state_mod.runner_pid(tmp_path) is None
    pid = tmp_path / state_mod.PID_FILE
    for text, want in [("abc", None), ("0", None), ("-5", None), ("123", 123), ("", None)]:
        pid.write_text(text)
        assert state_mod.runner_pid(tmp_path) == want


def test_pid_alive_maps_errors(monkeypatch) -> None:
    def kill(exc):
        def fake(pid, sig):
            if exc:
                raise exc

        return fake

    monkeypatch.setattr(os, "kill", kill(ProcessLookupError()))
    assert state_mod.pid_alive(5) is False
    monkeypatch.setattr(os, "kill", kill(PermissionError()))
    assert state_mod.pid_alive(5) is True
    monkeypatch.setattr(os, "kill", kill(None))
    assert state_mod.pid_alive(5) is True


def test_shown_status(tmp_path: Path) -> None:
    running = RunState(status=RunStatus.RUNNING)
    assert state_mod.shown_status(tmp_path, running) is RunStatus.INTERRUPTED
    (tmp_path / state_mod.PID_FILE).write_text(str(dead_pid()))
    assert state_mod.shown_status(tmp_path, running) is RunStatus.INTERRUPTED
    assert state_mod.runner_alive(tmp_path) is False
    (tmp_path / state_mod.PID_FILE).write_text(str(os.getpid()))
    assert state_mod.shown_status(tmp_path, running) is RunStatus.RUNNING
    assert state_mod.runner_alive(tmp_path) is True
    idle = RunState(status=RunStatus.IDLE)
    assert state_mod.shown_status(tmp_path, idle) is RunStatus.IDLE
    assert RunStatus.INTERRUPTED.value == "interrupted"


def test_state_round_trip_and_legacy(tmp_path: Path) -> None:
    st = RunState(in_flight=STEP)
    found = Interruption("developer-cli", "s1", "b", Cause.LIMIT, "abc")
    st.interrupted = [found]
    st.stories["s1"] = gates.StoryState("s1", "t", "design", interrupted=found)
    state_mod.save(tmp_path, st)
    back = state_mod.load(tmp_path)
    assert back.in_flight == STEP and back.interrupted == [found]
    assert back.stories["s1"].interrupted == found
    assert back.stories["s1"].interrupted.cause is Cause.LIMIT
    data = json.loads((tmp_path / "state.json").read_text())
    for key in ("in_flight", "interrupted"):
        data.pop(key)
    data["stories"]["s1"].pop("interrupted")
    (tmp_path / "state.json").write_text(json.dumps(data))
    old = state_mod.load(tmp_path)
    assert old.in_flight is None and old.interrupted == []
    assert old.stories["s1"].interrupted is None


# ----- recovery (I8, I9) -------------------------------------------------------------


def test_salvager_saves_records_and_emits(configured: Path) -> None:
    dirty(configured)
    run_dir = run_dir_of(configured)
    st = RunState(in_flight=STEP)
    found = recovery.Salvager(Git(configured), run_dir).save(st, Cause.LIMIT)
    assert found and found.sha and st.interrupted == [found] and st.in_flight is None
    log = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    kinds = [e for e in log if e["kind"] == "step-interrupted"]
    assert kinds[0]["role"] == "developer-cli" and kinds[0]["story"] == "s1"
    assert kinds[0]["data"] == {"cause": "limit", "commit": found.sha, "brief": STEP.brief}
    assert events.EventKind.STEP_INTERRUPTED.value == "step-interrupted"


def test_salvager_survives_git_error(configured: Path, monkeypatch) -> None:
    dirty(configured)
    run_dir = run_dir_of(configured)

    def boom(self, paths, message):
        raise GitError("nope")

    monkeypatch.setattr(Git, "commit", boom)
    st = RunState(in_flight=STEP)
    assert recovery.Salvager(Git(configured), run_dir).save(st, Cause.LIMIT) is None
    assert st.interrupted == [] and not Git(configured).is_clean()
    assert "GitError" in (run_dir / halt.CRASH_LOG).read_text()


def test_recover_killed_saves_the_tree(configured: Path) -> None:
    run_dir = run_dir_of(configured)
    dirty(configured)
    state_mod.save(run_dir, RunState(status=RunStatus.RUNNING, in_flight=STEP))
    found = recovery.recover_killed(run_dir, Git(configured))
    assert found and found.cause is Cause.KILLED and found.sha
    assert Git(configured).is_clean()
    saved = state_mod.load(run_dir)
    assert saved.in_flight is None and saved.interrupted == [found]
    assert saved.status is RunStatus.RUNNING  # never rewritten to interrupted


def test_recover_killed_does_nothing_when_run_is_alive_or_idle(configured: Path) -> None:
    run_dir = run_dir_of(configured)
    dirty(configured)
    state_mod.save(run_dir, RunState(status=RunStatus.IDLE))
    assert recovery.recover_killed(run_dir, Git(configured)) is None
    state_mod.save(run_dir, RunState(status=RunStatus.RUNNING, in_flight=STEP))
    (run_dir / state_mod.PID_FILE).write_text(str(os.getpid()))
    assert recovery.recover_killed(run_dir, Git(configured)) is None
    assert not Git(configured).is_clean()


# ----- cli: start --resume (I9) ------------------------------------------------------


@pytest.mark.parametrize("pid", ["dead", "missing"])
def test_resume_after_kill_recovers_and_passes_preflight(
    configured: Path, key_home: Path, capsys, monkeypatch, pid: str
) -> None:
    any_tool(monkeypatch)
    run_dir = run_dir_of(configured)
    state_mod.save(run_dir, RunState(status=RunStatus.RUNNING, in_flight=STEP))
    if pid == "dead":
        (run_dir / state_mod.PID_FILE).write_text(str(dead_pid()))
    dirty(configured)
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery()) == 0
    sha = state_mod.load(run_dir).stories.get("s1")
    err = capsys.readouterr().err
    assert (
        "agile-team start: the last run was killed; developer-cli on s1's edits are saved in "
        in err
    )
    assert err.strip().endswith("(reverted)") and sha is None
    assert Git(configured).is_clean()


def refused(configured: Path, key_home: Path, *extra: str) -> int:
    head = Git(configured).head()
    with pytest.raises(cli.CliError, match="dirty"):
        cli.cmd_start(start_args(configured, key_home, *extra), FakeQuery())
    return int(Git(configured).head() == head)


def test_dirty_tree_still_refused_when_idle(configured: Path, key_home: Path, monkeypatch) -> None:
    any_tool(monkeypatch)
    state_mod.save(run_dir_of(configured), RunState(status=RunStatus.IDLE))
    dirty(configured)
    assert refused(configured, key_home, "--resume")


def test_dirty_tree_refused_with_live_pid(configured: Path, key_home: Path, monkeypatch) -> None:
    any_tool(monkeypatch)
    run_dir = run_dir_of(configured)
    state_mod.save(run_dir, RunState(status=RunStatus.RUNNING, in_flight=STEP))
    (run_dir / state_mod.PID_FILE).write_text(str(os.getpid()))
    dirty(configured)
    assert refused(configured, key_home, "--resume")


def test_dirty_tree_refused_on_plain_start(configured: Path, key_home: Path, monkeypatch) -> None:
    any_tool(monkeypatch)
    run_dir = run_dir_of(configured)
    state_mod.save(run_dir, RunState(status=RunStatus.RUNNING, in_flight=STEP))
    (run_dir / state_mod.PID_FILE).write_text(str(dead_pid()))
    dirty(configured)
    assert refused(configured, key_home, "--task", "t")


# ----- dispatch: in flight, landing, halts, errors (I1, I2, I5, I6) ------------------


def test_in_flight_is_recorded_during_step_and_cleared_after(make_runtime) -> None:
    seen: list = []
    rt_holder: list = []

    def peek():
        seen.append(state_mod.load(rt_holder[0].config.run_dir).in_flight)

    rt = make_runtime(FakeQuery(action=peek))
    rt_holder.append(rt)
    open_story(rt)
    run_step(rt, brief="design it")
    assert seen == [InFlight("architect", "s1", "design it")]
    assert rt.state.in_flight is None
    assert state_mod.load(rt.config.run_dir).in_flight is None


def test_refused_step_never_sets_in_flight(make_runtime) -> None:
    rt = make_runtime()
    rt.state.status = RunStatus.BLOCKED
    run_step(rt, story=None)
    assert rt.state.in_flight is None


def test_settle_clears_story_offer(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    story.interrupted = Interruption("architect", "s1", "b", Cause.KILLED, "abc")
    run_step(rt)
    assert story.interrupted is None


def raising_action(rt_holder: list, exc: BaseException):
    def act():
        (rt_holder[0].config.repo / "docs").mkdir(exist_ok=True)
        (rt_holder[0].config.repo / "docs" / "half.md").write_text("half\n")
        (rt_holder[0].config.repo / "src" / "app.py").write_text("x = 9\n")
        raise exc

    return act


def test_limit_in_role_step_saves_edits_and_extends_note(make_runtime) -> None:
    holder: list = []
    rt = make_runtime(FakeQuery(action=raising_action(holder, limit_error())))
    holder.append(rt)
    story = open_story(rt)
    head = rt.git.head()
    report = run_step(rt, brief="design it")
    assert report["status"] == "halted"
    assert rt.git.is_clean()
    found = rt.state.interrupted[0]
    assert found.cause is Cause.LIMIT and found.sha and story.interrupted == found
    assert (story.step, story.rounds, story.commit) == ("design", 0, None)
    assert git(rt.config.repo, "rev-list", "--count", f"{head}..HEAD").strip() == "2"
    (note,) = notes(rt)
    assert note.text == (
        f"{LIMIT_REASON}; run `agile-team start --resume` after the reset"
        f"; architect on s1's edits are saved in {found.sha} (git cherry-pick -n {found.sha})"
    )
    saved = state_mod.load(rt.config.run_dir)
    assert saved.in_flight is None and saved.interrupted == [found]
    assert not any(e.kind == events.EventKind.QUARANTINE for e in rt.events.events())


def test_second_halt_records_and_posts_nothing(make_runtime) -> None:
    holder: list = []
    rt = make_runtime(FakeQuery(action=raising_action(holder, limit_error())))
    holder.append(rt)
    open_story(rt)
    run_step(rt)
    rt.halt_run(halt.Halt(halt.HaltKind.CRASH, "crashed: X"))
    assert len(rt.state.interrupted) == 1 and len(notes(rt)) == 1


@pytest.mark.parametrize("kind", [halt.HaltKind.SIGTERM, halt.HaltKind.CRASH])
def test_top_level_halt_saves_tree_with_its_cause(make_runtime, kind) -> None:
    rt = make_runtime()
    open_story(rt)
    rt.state.in_flight = STEP
    dirty(rt.config.repo)
    rt.halt_run(halt.Halt(kind, "why"))
    assert rt.git.is_clean()
    assert rt.state.interrupted[0].cause is Cause(kind.value)


def test_halt_without_edits_or_step_records_nothing(make_runtime) -> None:
    rt = make_runtime()
    rt.halt_run(halt.Halt(halt.HaltKind.LIMIT, LIMIT_REASON))
    assert rt.state.interrupted == []
    assert notes(rt)[0].text.endswith("after the reset")


def test_halt_survives_git_failure(make_runtime, monkeypatch) -> None:
    rt = make_runtime()
    rt.state.in_flight = STEP
    dirty(rt.config.repo)

    def boom(self, paths, message):
        raise GitError("nope")

    monkeypatch.setattr(Git, "commit", boom)
    rt.halt_run(halt.Halt(halt.HaltKind.LIMIT, LIMIT_REASON))
    assert rt.state.status is RunStatus.BLOCKED and not rt.git.is_clean()
    assert rt.state.interrupted == [] and "GitError" in crash_log(rt)
    assert notes(rt)[0].text.endswith("after the reset")


def test_error_in_role_step_saves_edits_and_still_raises(make_runtime) -> None:
    holder: list = []
    rt = make_runtime(FakeQuery(action=raising_action(holder, ValueError("boom"))))
    holder.append(rt)
    story = open_story(rt)
    with pytest.raises(ValueError, match="boom"):
        run_step(rt)
    assert rt.git.is_clean()
    assert story.interrupted and story.interrupted.cause is Cause.ERROR
    assert rt.state.interrupted == [] and rt.state.in_flight is None
    assert notes(rt) == []


# ----- the offer in the next brief (I10) ---------------------------------------------


@pytest.mark.parametrize("cause", list(Cause))
def test_next_brief_offers_the_saved_commit_until_the_step_settles(
    make_runtime, cause: Cause
) -> None:
    rt = make_runtime()
    open_story(rt)
    rt.state.in_flight = STEP
    dirty(rt.config.repo)
    state_mod.save(rt.config.run_dir, rt.state)
    rt.save_interrupted(cause)
    sha = state_mod.load(rt.config.run_dir).stories["s1"].interrupted.sha
    found = rt.state.stories["s1"].interrupted
    for role in ("architect", "developer-cli"):
        assert salvage.offer(found) in rt.plan(StepRequest(role, "go", "s1")).prompt
    assert f"git cherry-pick -n {sha}" in rt.plan(StepRequest("architect", "go", "s1")).prompt
    run_step(rt)
    assert "Interrupted work" not in rt.plan(StepRequest("architect", "go", "s1")).prompt


def test_later_interruption_without_edits_keeps_the_offer(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    rt.state.in_flight = STEP
    dirty(rt.config.repo)
    first = rt.save_interrupted(Cause.KILLED)
    rt.state.in_flight = STEP
    rt.save_interrupted(Cause.LIMIT)
    assert story.interrupted == first
    assert salvage.offer(first) in rt.plan(StepRequest("architect", "go", "s1")).prompt


# ----- PO resume prompt (I11) --------------------------------------------------------


class RecordingPo(PoCallingRole):
    """A PO that records every prompt it receives."""

    def __call__(self, *, prompt, options):
        self.prompts = [*getattr(self, "prompts", []), prompt]
        return self._gen()


def resume_with_pending(make_runtime, task: str, session: str | None = "po-sess"):
    holder: list = []
    po = RecordingPo(holder, steps=0)
    rt = make_runtime(Router(po, FakeQuery()))
    holder.append(rt)
    rt.state.po_session = session
    rt.state.interrupted = [Interruption("developer-cli", "s1", "build it", Cause.LIMIT, "abc")]
    asyncio.run(po_tools.run_po(rt, Start(task, StartMode.RESUME)))
    return rt, po.prompts


def test_resume_without_task_gets_po_turn_with_section(make_runtime) -> None:
    rt, prompts = resume_with_pending(make_runtime, "")
    first = prompts[0]
    assert "## Interrupted steps" in first
    assert "developer-cli on s1 (limit)" in first and "git cherry-pick -n abc" in first
    assert "Brief: build it" in first
    assert rt.state.interrupted == []
    assert state_mod.load(rt.config.run_dir).interrupted == []


def test_resume_with_task_puts_section_after_the_human_message(make_runtime) -> None:
    _, prompts = resume_with_pending(make_runtime, "nudge")
    assert prompts[0].index("nudge") < prompts[0].index("## Interrupted steps")


def test_first_prompt_without_session_gets_section(make_runtime) -> None:
    _, prompts = resume_with_pending(make_runtime, "do it", session=None)
    assert prompts[0].index("Task from the human") < prompts[0].index("## Interrupted steps")


def test_joined_skips_empty_parts() -> None:
    assert po_tools._joined("a", "", "b") == "a\n\nb"
    assert po_tools._joined("a", "") == "a"


# ----- status and snapshot (I13, I14) ------------------------------------------------


def test_status_report_with_dead_pid_is_interrupted(configured: Path) -> None:
    from agile_team import config as config_mod

    config = config_mod.load(configured)
    found = Interruption("developer-cli", "s1", "b", Cause.LIMIT, "abc")
    st = RunState(status=RunStatus.RUNNING, in_flight=STEP, interrupted=[found])
    state_mod.save(config.run_dir, st)
    (config.run_dir / state_mod.PID_FILE).write_text(str(dead_pid()))
    report = cli.status_report(config)
    assert (report["status"], report["running"]) == ("interrupted", False)
    assert report["in_flight"]["role"] == "developer-cli"
    assert report["interrupted"][0]["sha"] == "abc"
    keys = list(report)
    assert keys[keys.index("running") + 1 : keys.index("running") + 3] == [
        "in_flight",
        "interrupted",
    ]
    assert json.loads((config.run_dir / "state.json").read_text())["status"] == "running"


def test_status_report_live_and_idle(configured: Path) -> None:
    from agile_team import config as config_mod

    config = config_mod.load(configured)
    state_mod.save(config.run_dir, RunState(status=RunStatus.RUNNING))
    assert cli.status_report(config)["status"] == "interrupted"
    (config.run_dir / state_mod.PID_FILE).write_text(str(os.getpid()))
    live = cli.status_report(config)
    assert (live["status"], live["running"]) == ("running", True)
    state_mod.save(config.run_dir, RunState(status=RunStatus.IDLE))
    idle = cli.status_report(config)
    assert idle["status"] == "idle" and idle["in_flight"] is None and idle["interrupted"] == []


def test_snapshot_run_status_follows_shown_status(configured: Path) -> None:
    from agile_team import config as config_mod
    from agile_team.roles import RoleBook

    config = config_mod.load(configured)
    state_mod.save(config.run_dir, RunState(status=RunStatus.RUNNING))
    snap = snapshot.build(config, RoleBook.for_repo(configured, config.roles))
    assert snap["run"]["status"] == "interrupted"
