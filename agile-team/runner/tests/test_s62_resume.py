"""s62: ``start --resume`` saves the edits a checkout halt left behind (R1-R4)."""

import asyncio
from pathlib import Path

import pytest
from agile_team import checkout, cli, recovery, system
from agile_team import state as state_mod
from agile_team.git_ops import Git
from agile_team.po_tools import PoRun, Start
from agile_team.salvage import Cause
from agile_team.state import RunState, RunStatus

from .conftest import FakeQuery
from .fake_system import FAKE_IDS, FakeSystem
from .pipeline_helpers import Script, build
from .test_cli import any_tool, start_args
from .test_s9 import STEP, dead_pid, dirty, refused, run_dir_of
from .test_s61 import detach, git, stored, switch


@pytest.fixture(autouse=True)
def tracked(configured: Path, fake: FakeSystem) -> None:
    """Model the repo: branch, HEAD, commits and the reflog follow git commands."""
    fake.track()


HALTED = "agile-team start: the last run halted (checkout) before its edits were saved; "


def test_recover_cut_is_the_renamed_entry_point() -> None:
    assert not hasattr(recovery, "recover_killed")


def test_save_interrupted_on_a_moved_checkout_keeps_the_cause(make_runtime) -> None:
    rt = make_runtime()
    rt.record_checkout()
    rt.state.in_flight = STEP
    dirty(rt.config.repo)
    detach(rt.config.repo)
    before = git(rt.config.repo, "log", "--all", "--format=%H")
    assert rt.save_interrupted(Cause.CHECKOUT) is None
    assert rt.state.unsaved is Cause.CHECKOUT
    assert git(rt.config.repo, "log", "--all", "--format=%H") == before


def test_a_matching_checkout_does_not_set_unsaved(make_runtime) -> None:
    rt = make_runtime()
    rt.record_checkout()
    rt.state.in_flight = STEP
    dirty(rt.config.repo)
    assert rt.save_interrupted(Cause.LIMIT) is not None
    assert rt.state.unsaved is None


def test_halt_run_persists_the_unsaved_cause(make_runtime) -> None:
    from agile_team.halt import Halt, HaltKind

    rt = make_runtime()
    rt.record_checkout()
    rt.state.in_flight = STEP
    dirty(rt.config.repo)
    detach(rt.config.repo)
    rt.halt_run(Halt(HaltKind.CHECKOUT, "moved"))
    assert state_mod.load(rt.config.run_dir).unsaved is Cause.CHECKOUT


def test_recover_cut_saves_for_an_unsaved_cause(configured: Path) -> None:
    run_dir = run_dir_of(configured)
    dirty(configured)
    st = RunState(
        status=RunStatus.STOPPED,
        in_flight=STEP,
        unsaved=Cause.CHECKOUT,
        checkout=checkout.recorded(Git(configured)),
    )
    state_mod.save(run_dir, st)
    found = recovery.recover_cut(run_dir, Git(configured))
    assert found and found.cause is Cause.CHECKOUT and found.sha
    assert Git(configured).is_clean()
    saved = state_mod.load(run_dir)
    assert saved.unsaved is None and saved.interrupted == [found]
    assert saved.checkout == checkout.recorded(Git(configured))


def test_recover_cut_prefers_killed(configured: Path) -> None:
    run_dir = run_dir_of(configured)
    dirty(configured)
    st = RunState(status=RunStatus.RUNNING, in_flight=STEP, unsaved=Cause.CHECKOUT)
    state_mod.save(run_dir, st)
    system.write_text(run_dir / state_mod.PID_FILE, str(dead_pid()))
    found = recovery.recover_cut(run_dir, Git(configured))
    assert found and found.cause is Cause.KILLED


def test_recover_cut_does_nothing_without_a_cause(configured: Path) -> None:
    run_dir = run_dir_of(configured)
    dirty(configured)
    state_mod.save(run_dir, RunState(status=RunStatus.STOPPED))
    assert recovery.recover_cut(run_dir, Git(configured)) is None
    assert not Git(configured).is_clean()


def test_recover_cut_leaves_a_live_run_alone(configured: Path) -> None:
    run_dir = run_dir_of(configured)
    dirty(configured)
    state_mod.save(run_dir, RunState(status=RunStatus.RUNNING, in_flight=STEP))
    system.write_text(run_dir / state_mod.PID_FILE, str(FAKE_IDS[0]))
    assert recovery.recover_cut(run_dir, Git(configured)) is None


# ----- cli ---------------------------------------------------------------------------


def halted_with_edits(repo: Path) -> Path:
    """A checkout halt with a step in flight: its edits are unsaved, the checkout moved."""
    run_dir = stored(
        repo, status=RunStatus.CHECKOUT_CHANGED, in_flight=STEP, unsaved=Cause.CHECKOUT
    )
    dirty(repo)
    return run_dir


def test_killed_run_is_saved_before_preflight(
    configured: Path, key_home: Path, capsys, fake: FakeSystem
) -> None:
    any_tool(fake)
    run_dir = run_dir_of(configured)
    state_mod.save(run_dir, RunState(status=RunStatus.RUNNING, in_flight=STEP))
    system.write_text(run_dir / state_mod.PID_FILE, str(dead_pid()))
    dirty(configured)
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery()) == 0
    err = capsys.readouterr().err
    assert "agile-team start: the last run was killed; developer-cli on s1's edits" in err
    assert Git(configured).is_clean()


def test_accepting_then_resuming_saves_the_edits(
    configured: Path, key_home: Path, capsys, fake: FakeSystem
) -> None:
    any_tool(fake)
    run_dir = halted_with_edits(configured)
    switch(configured)
    assert cli.main(["--repo", str(configured), "--home", str(key_home), "accept-checkout"]) == 0
    capsys.readouterr()
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery()) == 0
    err = capsys.readouterr().err
    assert err.startswith(HALTED + "developer-cli on s1's edits are saved in ")
    assert err.strip().endswith("(reverted)")
    assert Git(configured).is_clean()
    saved = state_mod.load(run_dir)
    assert saved.unsaved is None
    assert saved.checkout == checkout.recorded(Git(configured))
    assert "chore(team): interrupted step by developer-cli" in git(configured, "log", "--format=%s")


def test_restoring_the_checkout_then_resuming_saves_the_edits(
    configured: Path, key_home: Path, capsys, fake: FakeSystem
) -> None:
    any_tool(fake)
    run_dir = halted_with_edits(configured)
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery()) == 0
    assert HALTED in capsys.readouterr().err
    assert Git(configured).is_clean() and state_mod.load(run_dir).unsaved is None


def test_a_plain_start_clears_the_flag(make_runtime) -> None:
    rt = build(make_runtime, Script(), steps=["design"])
    rt.state.unsaved = Cause.CHECKOUT
    asyncio.run(PoRun(rt, Start("go")).run())
    assert rt.state.unsaved is None
    assert state_mod.load(rt.config.run_dir).unsaved is None


def test_a_later_resume_refuses_unrelated_edits(
    configured: Path, key_home: Path, fake: FakeSystem
) -> None:
    any_tool(fake)
    run_dir = run_dir_of(configured)
    state_mod.save(run_dir, RunState(status=RunStatus.IDLE, unsaved=None))
    dirty(configured)
    assert refused(configured, key_home, "--resume")


def test_stopped_with_a_dirty_tree_and_no_flag_is_still_refused(
    configured: Path, key_home: Path, fake: FakeSystem
) -> None:
    any_tool(fake)
    stored_run = stored(configured, status=RunStatus.STOPPED)
    assert system.is_dir(stored_run)
    dirty(configured)
    assert refused(configured, key_home, "--resume")


@pytest.mark.parametrize("cause", [Cause.LIMIT, Cause.BUDGET])
def test_other_causes_use_the_generic_lead(cause: Cause) -> None:
    assert cli.RECOVERED_LEAD.format(cause=cause) == (
        f"the last run halted ({cause}) before its edits were saved"
    )
    assert cli.RECOVERED_LEADS == {Cause.KILLED: "the last run was killed"}
