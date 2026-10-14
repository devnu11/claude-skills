"""What a CI check means for the sprint: the job data GitHub gives, and the kind of each check."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Bucket(StrEnum):
    """``gh``'s bucket for one check."""

    PASS = "pass"
    FAIL = "fail"
    PENDING = "pending"
    SKIPPING = "skipping"
    CANCEL = "cancel"


FAILING = frozenset({Bucket.FAIL, Bucket.CANCEL})
PASSING = frozenset({Bucket.PASS, Bucket.SKIPPING})


class CheckKind(StrEnum):
    """What one check says about the sprint."""

    GREEN = "green"
    SKIPPED = "skipped"
    PENDING = "pending"
    STALE = "stale"
    OURS = "ours"
    INFRA = "infra"
    MAIN = "main"
    RERUN = "rerun"


RUNNER_STEPS = ("Set up job", "Complete job")
FAILED_STEPS = ("failure", "cancelled", "timed_out")
NOT_RUN = ("", "skipped")
BUCKET_KIND = {
    Bucket.PASS: CheckKind.GREEN,
    Bucket.SKIPPING: CheckKind.SKIPPED,
    Bucket.PENDING: CheckKind.PENDING,
    Bucket.FAIL: CheckKind.OURS,
    Bucket.CANCEL: CheckKind.OURS,
}
CONCLUSION_BUCKET = {
    "success": Bucket.PASS,
    "skipped": Bucket.SKIPPING,
    "neutral": Bucket.SKIPPING,
    "cancelled": Bucket.CANCEL,
    "": Bucket.PENDING,
}


@dataclass(frozen=True)
class Step:
    """One step of an Actions job."""

    name: str
    conclusion: str = ""


@dataclass(frozen=True)
class Job:
    """An Actions job as GitHub reports it."""

    id: str
    head: str
    name: str = ""
    steps: tuple[Step, ...] = ()


@dataclass(frozen=True)
class Seen:
    """A check's bucket and the job behind it (None: not an Actions check)."""

    bucket: Bucket
    job: Job | None = None


def job_from(raw: dict[str, Any]) -> Job:
    """A job from GitHub's ``actions/jobs/<id>`` JSON."""
    steps = tuple(
        Step(str(s.get("name", "")), s.get("conclusion") or "") for s in raw.get("steps") or []
    )
    return Job(str(raw["id"]), str(raw["head_sha"]), str(raw.get("name") or ""), steps)


def bucket_of_run(raw: dict[str, Any]) -> Bucket:
    """The bucket of a check run: not completed is pending, an unknown conclusion fails."""
    if raw.get("status") != "completed":
        return Bucket.PENDING
    return CONCLUSION_BUCKET.get(raw.get("conclusion") or "", Bucket.FAIL)


def _counts(step: Step) -> bool:
    return step.conclusion not in NOT_RUN and step.name not in RUNNER_STEPS


def ran(job: Job) -> bool:
    """True when one of our steps ran."""
    return any(_counts(s) for s in job.steps)


def failing_step(job: Job | None) -> str:
    """The name of the job's first failed step, or ``""``."""
    steps = job.steps if job else ()
    return next((s.name for s in steps if s.conclusion in FAILED_STEPS), "")


def _failure_kind(job: Job | None) -> CheckKind:
    return CheckKind.INFRA if job is not None and not ran(job) else CheckKind.OURS


def kind_of(seen: Seen, head: str) -> CheckKind:
    """What the check says: stale, as the bucket says, or whose failure it is."""
    if seen.job is not None and seen.job.head != head:
        return CheckKind.STALE
    if seen.bucket in FAILING:
        return _failure_kind(seen.job)
    return BUCKET_KIND[seen.bucket]


def rerun_key(head: str, label: str) -> str:
    """The key of one re-run: a job at a pushed head."""
    return f"{head} {label}"
