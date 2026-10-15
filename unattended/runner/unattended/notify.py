"""Notices: tell whoever watches a job that something needs a look.

Every notice goes two ways:

- **the chat:** a ``notify`` event in ``events.jsonl``, which a watching
  session reads through ``unattended wait --until-notice``;
- **an OS notification** from the ``NOTIFIERS`` table, keyed by platform:
  ``osascript`` on macOS, ``notify-send`` on Linux (when on PATH), and on
  Windows a PowerShell toast through the built-in WinRT
  ``ToastNotificationManager`` under PowerShell's own app id, falling back to
  a ``WScript.Shell`` popup that closes itself after 60 s. Other platforms get
  the event only, with ``"by": null``.

``--notify CMD`` replaces the OS notifier with a shell command that gets
``UNATTENDED_JOB``, ``UNATTENDED_TRIGGER`` and ``UNATTENDED_REASON``;
``--notify none`` keeps only the event. Notifiers start detached through
``spawn`` (injectable, like ``awake.spawn``), so the supervisor never waits.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .store import Job, JobStatus

NOTIFY_OFF = "none"
CUSTOM = "command"
TITLE = "unattended: {job}"
POPUP_SECONDS = 60


class Trigger(StrEnum):
    """Why a notice fires."""

    EARLY = "ended-early"
    IDLE = "idle"
    HUNG = "hung"
    DEADLINE = "deadline"
    IDLE_STOP = "idle-stop"
    LIMIT = "limit-reached"


NOTICES: dict[Trigger, str] = {
    Trigger.EARLY: "ended before its deadline",
    Trigger.IDLE: "is idle",
    Trigger.HUNG: "is hung",
    Trigger.DEADLINE: "is being stopped at its deadline",
    Trigger.IDLE_STOP: "is being stopped for making no progress",
    Trigger.LIMIT: "reached a limit",
}


@dataclass(frozen=True)
class Notice:
    """One notice: its trigger, the job's status then, and why."""

    trigger: Trigger
    status: JobStatus
    reason: str


@dataclass(frozen=True)
class Call:
    """A notifier to start: an argv, or a shell command string, and its extra environment."""

    command: list[str] | str
    env: dict[str, str]


def _applescript(text: str) -> str:
    """``text`` as an AppleScript string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


# Title and body come from the environment, so no text is ever pasted into code.
WINDOWS_SCRIPT = f"""
$t = $env:UNATTENDED_TITLE; $b = $env:UNATTENDED_BODY
try {{
  $m = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,
        ContentType = WindowsRuntime]
  $x = $m::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
  $n = $x.GetElementsByTagName('text')
  [void]$n.Item(0).AppendChild($x.CreateTextNode($t))
  [void]$n.Item(1).AppendChild($x.CreateTextNode($b))
  $id = '{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe'
  $m::CreateToastNotifier($id).Show([Windows.UI.Notifications.ToastNotification]::new($x))
}} catch {{
  [void](New-Object -ComObject WScript.Shell).Popup($b, {POPUP_SECONDS}, $t)
}}
"""

NOTIFIERS: dict[str, Callable[[str, str], list[str]]] = {
    "darwin": lambda title, body: [
        "osascript", "-e",
        f"display notification {_applescript(body)} with title {_applescript(title)}",
    ],
    "linux": lambda title, body: ["notify-send", title, body],
    "win32": lambda title, body: [
        "powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
        "-Command", WINDOWS_SCRIPT,
    ],
}  # fmt: skip


def os_notifier(title: str, body: str) -> list[str] | None:
    """The platform's notifier argv, when it has one and its tool is on PATH."""
    make = NOTIFIERS.get(sys.platform)
    command = make(title, body) if make else None
    return command if command and shutil.which(command[0]) else None


@dataclass(frozen=True)
class Message:
    """What one notice says, for one job."""

    job: str
    notice: Notice

    @property
    def title(self) -> str:
        return TITLE.format(job=self.job)

    @property
    def body(self) -> str:
        return f"{NOTICES[self.notice.trigger]}: {self.notice.reason}"

    def env(self) -> dict[str, str]:
        """What every notifier gets: the job, the trigger, the reason, title and body."""
        return {
            "UNATTENDED_JOB": self.job, "UNATTENDED_TRIGGER": self.notice.trigger,
            "UNATTENDED_REASON": self.notice.reason,
            "UNATTENDED_TITLE": self.title, "UNATTENDED_BODY": self.body,
        }  # fmt: skip


def call_for(setting: str, message: Message) -> Call | None:
    """The notifier ``--notify`` asks for: none, a custom command, or the OS's."""
    if setting == NOTIFY_OFF:
        return None
    command = setting or os_notifier(message.title, message.body)
    return Call(command, message.env()) if command else None


def named(call: Call | None) -> str | None:
    """Who delivered a notice, for its event: the tool, ``command``, or None."""
    if call is None:
        return None
    return call.command[0] if isinstance(call.command, list) else CUSTOM


def launch(call: Call) -> subprocess.Popen[bytes]:
    devnull = subprocess.DEVNULL
    return subprocess.Popen(
        call.command, shell=isinstance(call.command, str), env={**os.environ, **call.env},
        stdin=devnull, stdout=devnull, stderr=devnull,
    )  # fmt: skip


Spawn = Callable[[Call], Any]
spawn: Spawn = launch


def post(job: Job, notice: Notice) -> None:
    """Log ``notice`` as a ``notify`` event and start the job's notifier, if any."""
    call = call_for(job.load().spec.notify, Message(job.name, notice))
    job.event("notify", {"trigger": notice.trigger, "status": notice.status,
                         "reason": notice.reason, "by": named(call)})  # fmt: skip
    if call:
        spawn(call)
