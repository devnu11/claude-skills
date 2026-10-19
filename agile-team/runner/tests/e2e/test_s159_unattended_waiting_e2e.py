"""s159 AC11.6 end to end: the real ``unattended`` package watches a run whose heartbeat waits.

The driver runs in the unattended project's own environment with a fake clock and a recording
notifier. It writes the heartbeat file the way a waiting ``agile-team start`` does.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
RUNNER = ROOT / "unattended" / "runner"
DRIVER = r"""
import json, sys
from pathlib import Path
from unattended import notify
from unattended.limits import Bounds
from unattended.store import JobHome, JobKind, JobState, Spec
from unattended.watch import RunWatch

home = Path(sys.argv[1])
calls = []
notify.spawn = calls.append
work = home / "work"
work.mkdir(parents=True)
spec = Spec(JobKind.COMMAND, str(work), command="true")
job = JobHome(home / "jobs").create(JobState("job", spec))
job.update(lambda st: setattr(st, "bounds", Bounds(idle_stop=60.0)))


class Clock:
    now = 1000.0
    def __call__(self):
        return self.now


clock = Clock()
watch = RunWatch(job, clock)


def beat(progress, waiting=None):
    data = {"at": clock.now, "progress": progress}
    if waiting:
        data["waiting"] = waiting
    watch.heartbeat.write_text(json.dumps(data))


def tick(seconds, progress, waiting=None):
    clock.now += seconds
    beat(progress, waiting)
    return watch.check()


def waiting_notices():
    return [c for c in calls if c.env.get("UNATTENDED_TRIGGER") == "waiting"]


out = {}
tick(10, 1, "waiting for the human")
out["first"] = [c.env["UNATTENDED_REASON"] for c in waiting_notices()]
for _ in range(10):
    tick(30, 1, "waiting for the human")
out["after_long_wait"] = len(waiting_notices())
out["idle_stop_started_while_waiting"] = watch.idle_stop is not None
tick(10, 2, "waiting for an answer")
out["after_progress"] = len(waiting_notices())
for _ in range(5):
    tick(30, 2)
out["idle_stop_without_waiting"] = watch.idle_stop is not None
print(json.dumps(out))
"""


def drive(home: Path) -> dict:
    cmd = ["uv", "run", "--directory", str(RUNNER), "python", "-c", DRIVER, str(home)]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not RUNNER.is_dir(), reason="unattended runner not in this checkout")
def test_ac11_6_one_waiting_notice_with_the_reason_and_no_idle_stop(tmp_path: Path) -> None:
    out = drive(tmp_path)
    assert out["first"] == ["waiting for the human"]
    assert out["after_long_wait"] == 1
    assert out["idle_stop_started_while_waiting"] is False


@pytest.mark.skipif(not RUNNER.is_dir(), reason="unattended runner not in this checkout")
def test_ac11_6_a_second_notice_only_after_progress_and_idle_stop_applies_without_waiting(
    tmp_path: Path,
) -> None:
    out = drive(tmp_path)
    assert out["after_progress"] == 2
    assert out["idle_stop_without_waiting"] is True
