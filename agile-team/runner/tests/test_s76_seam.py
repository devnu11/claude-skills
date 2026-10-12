"""s76: the process, signal and network seam end to end on the fake (J5, J4, J3)."""

from __future__ import annotations

import signal
from pathlib import Path

from agile_team import process_groups, sandbox, system, upstream
from agile_team.commands import NO_HUNG_LINE, TIMED_OUT, CommandShell
from agile_team.config import Delivery
from agile_team.git_ops import Git

from .fake_system import FAKE_IDS, FIRST_CHILD_PID, START_CLOCK, Done, FakeSystem, Hang


def test_git_run_records_the_command_with_options_first(repo: Path, fake: FakeSystem) -> None:
    Git(repo, ("-c", "x=y")).run("status")
    assert fake.commands == [system.Command(("git", "-c", "x=y", "status"), repo)]


def test_upstream_command_runner_gives_127_for_a_missing_binary(
    repo: Path, fake: FakeSystem
) -> None:
    fake.reply(("gh",), FileNotFoundError("gh: not found"))
    assert upstream.command_runner(repo)(["gh", "pr", "list"]) == (127, "gh: not found")


def test_upstream_command_runner_joins_stdout_and_stderr_and_passes_the_timeout(
    repo: Path, fake: FakeSystem
) -> None:
    fake.reply(("gh",), Done(2, "out ", "err"))
    assert upstream.command_runner(repo)(["gh", "pr", "list"]) == (2, "out err")
    assert fake.commands == [system.Command(("gh", "pr", "list"), repo, upstream.GH_TIMEOUT)]


def test_a_command_shell_run_of_a_hung_child_times_out_kills_its_group_and_keeps_the_output(
    repo: Path, fake: FakeSystem
) -> None:
    fake.reply(("sleep",), Hang("so far\n"))
    code, out = CommandShell(repo, 1.5).run("sleep 30")
    assert code == TIMED_OUT
    assert out.splitlines()[0] == "so far"
    assert out.splitlines()[-1] == NO_HUNG_LINE
    assert [(n, g, s) for n, g, s in fake.signals] == [("killpg", FIRST_CHILD_PID, signal.SIGKILL)]
    assert fake.clock == START_CLOCK + 1.5
    assert fake.commands == [system.ShellCommand("sleep 30", repo)]


def test_sandbox_env_reads_the_fake_environment(fake: FakeSystem, scratch: Path) -> None:
    fake.env.update({"PATH": "/usr/bin", "HOME": "/fake/home"})
    env = sandbox.sandbox_env(Delivery("x", "package", bin=["b"]), scratch)
    assert env["HOME"] == "/fake/home"
    assert env["PATH"].endswith(":/usr/bin") and env["PATH"].startswith(str(scratch / "b"))


def test_runner_ids_come_from_the_seam() -> None:
    assert process_groups.RunnerIds.current() == process_groups.RunnerIds(*FAKE_IDS)
