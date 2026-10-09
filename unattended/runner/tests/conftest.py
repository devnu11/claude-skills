"""Shared fixtures: jobs in a scratch job home."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from unattended.store import Job, JobHome, JobKind, JobState, Spec

MakeJob = Callable[[Spec], Job]


@pytest.fixture
def make_job(tmp_path: Path) -> MakeJob:
    """Create a job named ``job`` in ``tmp_path/jobs`` with the given spec."""

    def make(spec: Spec) -> Job:
        return JobHome(tmp_path / "jobs").create(JobState("job", spec))

    return make


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


def command_spec(workdir: Path, command: str, resume_command: str = "") -> Spec:
    return Spec(JobKind.COMMAND, str(workdir), command=command, resume_command=resume_command)
