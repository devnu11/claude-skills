"""The command's process group per platform: start it, stop it, kill its tree."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Any

import pytest
from unattended import command_job, process_group, store

WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="needs a real Windows")


@pytest.fixture
def windows_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Windows-only constants, so the Windows group can be built anywhere."""
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)


def test_by_session_starts_a_session_and_signals_the_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: sent.append((pid, sig)), raising=False)
    group = process_group.by_session()
    group.terminate(42)
    group.kill(42)
    assert group.spawn == {"start_new_session": True}
    assert sent == [(42, signal.SIGTERM), (42, signal.SIGKILL)]


@pytest.mark.usefixtures("windows_names")
def test_windows_starts_a_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert process_group.current().spawn == {"creationflags": 0x200}


@pytest.mark.usefixtures("windows_names")
def test_windows_ends_the_tree_with_taskkill(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **_: ran.append(argv))
    group = process_group.by_process_group()
    group.terminate(42)
    group.kill(42)
    assert ran == [["taskkill", "/T", "/F", "/PID", "42"]] * 2


def test_other_platforms_use_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert process_group.current().spawn == {"start_new_session": True}


CHILD_SLEEPS = (
    "import subprocess, sys, time; "
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
    "print(child.pid, flush=True); time.sleep(60)"
)


@WINDOWS_ONLY
def test_windows_end_stops_the_whole_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # pragma: no cover -- Windows only
    monkeypatch.setattr(command_job, "TERM_GRACE", 2.0)
    spawn: dict[str, Any] = dict(process_group.current().spawn)
    proc = subprocess.Popen([sys.executable, "-c", CHILD_SLEEPS], stdout=subprocess.PIPE, **spawn)
    assert proc.stdout is not None
    child = int(proc.stdout.readline())
    assert store.alive(child)
    started = time.monotonic()
    command_job.end(proc)
    assert proc.returncode is not None
    assert time.monotonic() - started < 30
    assert not store.alive(child)
