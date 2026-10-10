"""Keep-awake inhibitors per platform."""

from __future__ import annotations

import pytest
from unattended import awake
from unattended.awake import detached, inhibitor, keep_awake


@pytest.fixture
def installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(awake.shutil, "which", lambda name: f"/usr/bin/{name}")


@pytest.mark.usefixtures("installed")
def test_macos_uses_caffeinate_on_the_pid() -> None:
    assert inhibitor(42, "darwin") == ["caffeinate", "-i", "-w", "42"]


@pytest.mark.usefixtures("installed")
def test_linux_inhibits_until_the_pid_exits() -> None:
    command = inhibitor(42, "linux")
    assert command is not None
    assert command[0] == "systemd-inhibit"
    assert command[-4:] == ["tail", "--pid=42", "-f", "/dev/null"]


@pytest.mark.usefixtures("installed")
def test_windows_has_no_inhibitor() -> None:
    assert inhibitor(42, "win32") is None


def test_a_missing_tool_means_no_inhibitor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(awake.shutil, "which", lambda name: None)
    assert inhibitor(42, "darwin") is None


@pytest.mark.usefixtures("installed")
def test_keep_awake_spawns_the_inhibitor(
    monkeypatch: pytest.MonkeyPatch, spawned: list[list[str]]
) -> None:
    monkeypatch.setattr(awake.sys, "platform", "darwin")
    monkeypatch.setattr(awake, "inhibitor", lambda pid: ["caffeinate", "-i", "-w", str(pid)])
    assert keep_awake(7) == "caffeinate"
    assert spawned == [["caffeinate", "-i", "-w", "7"]]


def test_keep_awake_without_an_inhibitor(
    monkeypatch: pytest.MonkeyPatch, spawned: list[list[str]]
) -> None:
    monkeypatch.setattr(awake, "inhibitor", lambda pid: None)
    assert keep_awake(7) is None
    assert spawned == []


def test_detached_runs_the_command() -> None:
    assert detached(["true"]).wait(timeout=10) == 0
