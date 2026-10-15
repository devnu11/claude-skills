"""Notices: tell whoever watches a job that something needs a look.

Every notice is a ``notify`` event in ``events.jsonl``, the channel a watching
session reads (``unattended wait --until-notice``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .store import Job, JobStatus


class Trigger(StrEnum):
    """Why a notice fires."""

    IDLE = "idle"
    HUNG = "hung"
    IDLE_STOP = "idle-stop"


@dataclass(frozen=True)
class Notice:
    """One notice: its trigger, the job's status then, and why."""

    trigger: Trigger
    status: JobStatus
    reason: str


def post(job: Job, notice: Notice) -> None:
    """Log ``notice`` as a ``notify`` event."""
    job.event(
        "notify", {"trigger": notice.trigger, "status": notice.status, "reason": notice.reason}
    )
