"""s43 end to end: a hung test command is killed, named, and bounces the gate."""

from __future__ import annotations

import os
import sys
import textwrap
import time
from pathlib import Path

import pytest
from agile_team import gates
from agile_team.commands import NO_HUNG_LINE, TIMED_OUT, CommandShell
from agile_team.guard import WAIT_DENIED, Scope, check_bash


def hanging_suite(tmp_path: Path) -> str:
    """A tiny pytest-timeout suite whose one test hangs; returns the command."""
    (tmp_path / "test_hang.py").write_text(
        textwrap.dedent(
            """
            import time
            def test_hangs():
                time.sleep(30)
            """
        )
    )
    opts = "-q -p no:cacheprovider -o faulthandler_timeout=0.5"
    return f"{sys.executable} -m pytest {opts} test_hang.py"


def test_real_pytest_hang_is_killed_named_and_bounces_tests_gate(tmp_path: Path) -> None:
    run = CommandShell(tmp_path, 3.0).run
    started = time.monotonic()
    code, out = run(hanging_suite(tmp_path))
    assert code == TIMED_OUT
    assert time.monotonic() - started < 15
    assert "test_hang.py::test_hangs" in out
    outcome = gates.Checks({"test": hanging_suite(tmp_path)}, 95.0, run).tests_red()
    assert outcome.verdict == gates.Verdict.BOUNCE
    assert outcome.reason.startswith("the command did not finish in time:")


def test_timeout_without_a_nameable_test_still_bounces_with_command_and_limit(
    tmp_path: Path,
) -> None:
    code, out = CommandShell(tmp_path, 0.3).run("sleep 30")
    assert code == TIMED_OUT
    lines = out.splitlines()
    assert lines[-1] == NO_HUNG_LINE
    assert "timed out after 0.3s" in lines[-2] and "sleep 30" in lines[-2]
    bounce = gates.timed_out(code, out)
    assert bounce is not None and bounce.verdict == gates.Verdict.BOUNCE


def test_the_whole_group_dies_but_a_foreign_group_survives(tmp_path: Path) -> None:
    import subprocess

    other = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        code, _ = CommandShell(tmp_path, 0.3).run("sleep 30 & echo $! > pid; wait")
        assert code == TIMED_OUT
        child = int((tmp_path / "pid").read_text())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and alive(child):
            time.sleep(0.05)
        assert not alive(child)
        assert other.poll() is None
    finally:
        other.kill()
        other.wait()


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # a zombie still answers signal 0; it is dead for our purposes
    return Path(f"/proc/{pid}").exists() or _ps_state(pid) not in ("", "Z")


def _ps_state(pid: int) -> str:
    import subprocess

    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return out.stdout.strip()[:1]


@pytest.mark.parametrize(
    "command",
    [
        "until grep -q passed /tmp/run.log; do sleep 5; done",
        "while true; do sleep 1; done",
    ],
)
def test_guard_denies_open_wait_loops(tmp_path: Path, command: str) -> None:
    assert check_bash(Scope("developer-cli", tmp_path, []), command) == WAIT_DENIED


def test_guard_allows_bounded_waits(tmp_path: Path) -> None:
    scope = Scope("developer-cli", tmp_path, [])
    ok = "for i in $(seq 60); do sleep 1; done"
    assert check_bash(scope, ok) != WAIT_DENIED
