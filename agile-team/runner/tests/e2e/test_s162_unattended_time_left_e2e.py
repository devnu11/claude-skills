"""s162 end to end: the real ``unattended`` CLI prints ``time_left`` beside each deadline."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
RUNNER = ROOT / "unattended" / "runner"
SEED_SOURCE = r"""
import sys, time
from pathlib import Path
from unattended.limits import Bounds
from unattended.store import JobHome, JobKind, JobState, JobStatus, Spec

home = Path(sys.argv[1])
work = home / "work"
work.mkdir(parents=True, exist_ok=True)
now = time.time()
offsets = {"long": 23 * 3600 + 41 * 60 + 30, "short": 41 * 60 + 30, "seconds": 30,
           "past": -600, "none": None}
for name, off in offsets.items():
    spec = Spec(JobKind.COMMAND, str(work), command="true", notify="true")
    job = JobHome(home / ".claude" / "jobs").create(JobState(name, spec))
    deadline = None if off is None else now + off
    job.update(lambda st, d=deadline: (setattr(st, "bounds", Bounds(deadline=d)),
                                       setattr(st, "status", JobStatus.DONE)))
"""
pytestmark = pytest.mark.skipif(not RUNNER.is_dir(), reason="unattended runner not in checkout")


def uv(home: Path, *args: str) -> subprocess.CompletedProcess:
    cmd = ["uv", "run", "--directory", str(RUNNER), *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=home, check=False)


def cli(home: Path, *args: str) -> dict | list:
    done = uv(home, "unattended", "--home", str(home), *args)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    done = uv(tmp_path, "python", "-c", SEED_SOURCE, str(tmp_path))
    assert done.returncode == 0, done.stderr
    return tmp_path


def test_ac1_status_list_and_wait_give_time_left_beside_the_deadline(home: Path) -> None:
    expected = {"long": "23h41m", "short": "41m", "seconds": "0m", "past": "overdue", "none": None}
    listed = {j["name"]: j for j in cli(home, "list")}
    for name, text in expected.items():
        assert cli(home, "status", name)["time_left"] == text
        assert cli(home, "wait", name)["time_left"] == text
        assert listed[name]["time_left"] == text
    keys = list(listed["long"])
    assert keys[keys.index("deadline") + 1] == "time_left"


def test_ac2_no_state_is_written_and_other_fields_unchanged(home: Path) -> None:
    files = sorted((home / ".claude" / "jobs").rglob("*"))
    before = {p: p.read_bytes() for p in files if p.is_file()}
    first = cli(home, "status", "long")
    second = cli(home, "status", "long")
    after = {p: p.read_bytes() for p in files if p.is_file()}
    assert before == after
    assert sorted((home / ".claude" / "jobs").rglob("*")) == files
    assert first == second
    assert "time_left" in first and first["deadline"] is not None
    shutil.rmtree(home, ignore_errors=True)
