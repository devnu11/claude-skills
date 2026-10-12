"""s41: what a role's Bash may signal (K1-K5)."""

import os
import subprocess
from pathlib import Path

import pytest
from agile_team import guard, kill_check
from agile_team.guard import Scope


@pytest.fixture
def scope(tmp_path: Path) -> Scope:
    return Scope("developer", tmp_path, ["**"])


@pytest.fixture
def same_group():
    proc = subprocess.Popen(["sleep", "30"])
    yield proc
    proc.kill()
    proc.wait()


@pytest.fixture
def own_group():
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    yield proc
    proc.kill()
    proc.wait()


def _runner(target: str) -> str:
    return kill_check.RUNNER_DENIED.format(target=target)


# 13
def test_killing_the_runner_pid_is_denied(scope: Scope) -> None:
    pid = os.getpid()
    assert guard.check_bash(scope, f"kill {pid}") == _runner(str(pid))


def test_killing_a_same_group_child_is_denied(scope: Scope, same_group) -> None:
    pid = same_group.pid
    assert guard.check_bash(scope, f"kill -9 {pid}") == _runner(str(pid))


@pytest.mark.parametrize(
    ("template", "target"),
    [
        ("kill -- -{pgrp}", "-{pgrp}"),
        ("kill 0", "0"),
        ("kill -- -1", "-1"),
        ("/bin/kill -s TERM {pid}", "{pid}"),
        ("sudo kill {pid}", "{pid}"),
        ("timeout 5 kill -TERM {pid}", "{pid}"),
        ("echo hi && kill {pid}", "{pid}"),
    ],
)
def test_runner_targets_are_denied(scope: Scope, template: str, target: str) -> None:
    ids = {"pid": os.getpid(), "pgrp": os.getpgrp()}
    got = guard.check_bash(scope, template.format(**ids))
    assert got == _runner(target.format(**ids))


# 14
@pytest.mark.parametrize(
    ("command", "word"),
    [
        ("pkill -f pytest", "pkill"),
        ("killall python", "killall"),
        ("/usr/bin/pkill x", "pkill"),
    ],
)
def test_kill_by_name_is_denied(scope: Scope, command: str, word: str) -> None:
    assert guard.check_bash(scope, command) == kill_check.BY_NAME_DENIED.format(word=word)


# 15
@pytest.mark.parametrize(
    "command",
    [
        "kill $(pgrep -f pytest)",
        "kill `cat p`",
        'kill "$(cat p)"',
        "pgrep x | xargs kill",
        "pgrep x | xargs -r kill -9",
    ],
)
def test_run_time_targets_are_denied(scope: Scope, command: str) -> None:
    assert guard.check_bash(scope, command) == kill_check.AT_RUN_TIME_DENIED


# 16
def test_safe_kills_pass(scope: Scope, own_group) -> None:
    reaped = subprocess.Popen(["true"])
    reaped.wait()
    commands = [
        "kill $PID",
        "kill $!",
        "kill %1",
        f"kill {own_group.pid}",
        f"kill {reaped.pid}",
        "kill -l",
        'ps aux | grep "[p]ytest"',
        "pgrep -f pytest",
        "grep -n kill foo.py",
        "git log --grep kill",
    ]
    for command in commands:
        assert guard.check_bash(scope, command) is None, command


# 17
@pytest.mark.parametrize(
    ("args", "targets"),
    [
        (["-9", "1", "2"], ["1", "2"]),
        (["-s", "TERM", "3"], ["3"]),
        (["-n", "9", "3"], ["3"]),
        (["--", "-4"], ["-4"]),
        (["-9", "--", "-4"], ["-4"]),
        ([], []),
    ],
)
def test_kill_targets(args: list[str], targets: list[str]) -> None:
    assert kill_check.kill_targets(args) == targets


def test_kill_denial_ignores_segments_without_kill() -> None:
    assert kill_check.kill_denial(["ls", "-l"]) is None


# 18
def test_the_git_rule_reports_first(scope: Scope) -> None:
    command = f"git commit -m x && kill {os.getpid()}"
    got = guard.check_bash(scope, command)
    assert got is not None and got != _runner(str(os.getpid()))


# K5
def test_prompt_tells_roles_not_to_kill_by_name() -> None:
    shared = Path(kill_check.__file__).parent / "roles" / "_shared.md"
    text = shared.read_text()
    assert "Stop only what you started" in text and "pkill" in text
