"""Notices: the event, the platform notifiers, --notify, and a real launch."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from unattended import notify
from unattended.notify import Call, Message, Notice, Trigger
from unattended.store import EVENTS_FILE, Job, JobStatus

from .conftest import MakeJob, command_spec

IDLE = Notice(Trigger.IDLE, JobStatus.RUNNING, 'no progress for "20m"')
MESSAGE = Message("nightly", IDLE)


@pytest.fixture
def installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notify.shutil, "which", lambda name: f"/usr/bin/{name}")


def on(monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
    monkeypatch.setattr(notify.sys, "platform", platform)


@pytest.mark.usefixtures("installed")
def test_macos_uses_osascript_with_quoted_text(monkeypatch: pytest.MonkeyPatch) -> None:
    on(monkeypatch, "darwin")
    command = notify.os_notifier("unattended: j", 'say "hi" \\ bye')
    assert command == [
        "osascript", "-e",
        'display notification "say \\"hi\\" \\\\ bye" with title "unattended: j"',
    ]  # fmt: skip


@pytest.mark.usefixtures("installed")
def test_linux_uses_notify_send(monkeypatch: pytest.MonkeyPatch) -> None:
    on(monkeypatch, "linux")
    assert notify.os_notifier("t", "b") == ["notify-send", "t", "b"]


@pytest.mark.usefixtures("installed")
def test_windows_toasts_then_falls_back_to_a_popup(monkeypatch: pytest.MonkeyPatch) -> None:
    on(monkeypatch, "win32")
    command = notify.os_notifier("t", "b")
    assert command is not None and command[:2] == ["powershell", "-NoProfile"]
    script = command[-1]
    assert "ToastNotificationManager" in script and "ContentType = WindowsRuntime" in script
    assert "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell" in script
    assert "Popup($b, 60, $t)" in script
    assert "$env:UNATTENDED_TITLE" in script and "t" not in command[:-1]


@pytest.mark.usefixtures("installed")
def test_other_platforms_have_no_notifier(monkeypatch: pytest.MonkeyPatch) -> None:
    on(monkeypatch, "sunos5")
    assert notify.os_notifier("t", "b") is None


def test_a_missing_tool_means_no_notifier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notify.shutil, "which", lambda name: None)
    on(monkeypatch, "linux")
    assert notify.os_notifier("t", "b") is None


def test_message_text_and_env() -> None:
    assert MESSAGE.title == "unattended: nightly"
    assert MESSAGE.body == 'is idle: no progress for "20m"'
    env = MESSAGE.env()
    assert (env["UNATTENDED_JOB"], env["UNATTENDED_TRIGGER"]) == ("nightly", "idle")
    assert env["UNATTENDED_REASON"] == IDLE.reason


@pytest.mark.usefixtures("installed")
def test_call_for_each_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    on(monkeypatch, "linux")
    assert notify.call_for("none", MESSAGE) is None
    assert notify.call_for("say hi", MESSAGE) == Call("say hi", MESSAGE.env())
    os_call = notify.call_for("", MESSAGE)
    assert os_call is not None and os_call.command[0] == "notify-send"
    assert [notify.named(c) for c in (None, os_call, Call("x", {}))] == [
        None, "notify-send", "command",
    ]  # fmt: skip


def events(job: Job) -> list[dict[str, object]]:
    return [json.loads(line) for line in job.path(EVENTS_FILE).open()]


@pytest.mark.usefixtures("installed")
def test_post_logs_the_event_and_notifies(
    make_job: MakeJob, workdir: Path, monkeypatch: pytest.MonkeyPatch, notified: list[Call]
) -> None:
    on(monkeypatch, "linux")
    job = make_job(command_spec(workdir, "true"))
    notify.post(job, IDLE)
    assert events(job)[-1] == {
        "at": events(job)[-1]["at"], "event": "notify", "trigger": "idle",
        "status": "running", "reason": IDLE.reason, "by": "notify-send",
    }  # fmt: skip
    assert notified[0].command[:2] == ["notify-send", "unattended: job"]


def test_notify_none_keeps_only_the_event(
    make_job: MakeJob, workdir: Path, notified: list[Call]
) -> None:
    spec = command_spec(workdir, "true")
    spec.notify = "none"
    job = make_job(spec)
    notify.post(job, IDLE)
    assert (events(job)[-1]["by"], notified) == (None, [])


def test_launch_runs_a_custom_command_with_the_notice_env(tmp_path: Path) -> None:
    out = tmp_path / "out"
    call = Call(f'echo "$UNATTENDED_JOB $UNATTENDED_TRIGGER" > {out}', MESSAGE.env())
    assert notify.launch(call).wait(timeout=10) == 0
    assert out.read_text() == "nightly idle\n"
    assert notify.launch(Call(["true"], {})).wait(timeout=10) == 0
    assert "UNATTENDED_JOB" not in os.environ
