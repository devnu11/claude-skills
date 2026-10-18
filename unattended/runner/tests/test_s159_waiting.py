"""s159 I7: the heartbeat's ``waiting`` reason reaches the watch, the notices and the status."""

from __future__ import annotations

import json
from pathlib import Path

from unattended import command_job, notify, probes
from unattended.command_job import RunOutput
from unattended.probes import Reading
from unattended.watch import View


def beat(path: Path, **data: object) -> Reading:
    path.write_text(json.dumps({"at": 5.0, "progress": 3, **data}))
    return probes.heartbeat_reading(path)


def test_a_heartbeat_with_a_waiting_reason_is_read(tmp_path: Path) -> None:
    got = beat(tmp_path / "hb.json", waiting="waiting for the human")
    assert got.waiting == "waiting for the human"
    assert (got.value, got.alive_at) == (3, 5.0)


def test_a_heartbeat_without_waiting_reads_none(tmp_path: Path) -> None:
    assert beat(tmp_path / "hb.json").waiting is None


def test_a_non_text_waiting_is_ignored(tmp_path: Path) -> None:
    assert beat(tmp_path / "hb.json", waiting=7).waiting is None


def test_a_reading_defaults_to_not_waiting() -> None:
    assert Reading(1).waiting is None


def test_the_watch_view_carries_waiting() -> None:
    assert "waiting" in View.__dataclass_fields__
    assert View.__dataclass_fields__["waiting"].default is None


def test_the_waiting_notice_exists_and_reads_as_is_waiting() -> None:
    assert notify.Trigger.WAITING == "waiting"
    assert notify.NOTICES[notify.Trigger.WAITING] == "is waiting"


def test_status_reason_accepts_a_limit_status(tmp_path: Path) -> None:
    path = tmp_path / command_job.STATUS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"status": "limit", "status_reason": "resets 9pm"}))
    assert command_job.status_reason(RunOutput("", tmp_path)) == "resets 9pm"


def test_status_reason_still_accepts_blocked(tmp_path: Path) -> None:
    path = tmp_path / command_job.STATUS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"status": "blocked", "status_reason": "budget"}))
    assert command_job.status_reason(RunOutput("", tmp_path)) == "budget"
