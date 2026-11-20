from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from unattended import pin
from unattended.pin import Pin
from unattended.store import EVENTS_FILE, Job

from .conftest import MakeJob
from .test_prompt_job import prompt_spec

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]


@pytest.fixture
def job(make_job: MakeJob, workdir: Path) -> Job:
    return make_job(prompt_spec(workdir))


def make_skill(root: Path, name: str = "triage") -> Path:
    skill = root / name
    (skill / "reference").mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\nv1\n")
    (skill / "reference" / "notes.md").write_text("notes")
    (skill / ".venv").mkdir()
    return skill


def commit_all(repo: Path) -> str:
    subprocess.run([*GIT, "init", "-q"], cwd=repo, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*GIT, "commit", "-qm", "skill"], cwd=repo, check=True)
    done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
    return done.stdout.strip()


def pins(job: Job) -> list[dict[str, Any]]:
    lines = map(json.loads, job.path(EVENTS_FILE).read_text().splitlines())
    return [event for event in lines if event["event"] == "pin"]


def test_problems_name_missing_skills_and_repeated_names(tmp_path: Path) -> None:
    good = make_skill(tmp_path / "a")
    twin = make_skill(tmp_path / "b")
    problems = pin.find_skill_problems([good, twin, tmp_path])
    assert problems == [
        f"--skill {tmp_path}: no SKILL.md there",
        "--skill: two skills named 'triage'",
    ]
    assert pin.find_skill_problems([good]) == []


def test_pinning_copies_the_skill_into_a_local_plugin(job: Job, tmp_path: Path) -> None:
    source = make_skill(tmp_path)
    pin.copy_skills(job, [str(source)])
    (source / "SKILL.md").write_text("v2")
    copy = job.path("plugin") / "skills" / "triage"
    assert "v1" in (copy / "SKILL.md").read_text()
    assert (copy / "reference" / "notes.md").read_text() == "notes"
    assert not (copy / ".venv").exists()
    manifest = json.loads((job.path("plugin") / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "unattended-pinned"


def test_no_skills_makes_no_plugin(job: Job) -> None:
    pin.copy_skills(job, [])
    assert not job.path("plugin").exists()
    assert pin.build_plugins(job, []) == []


def test_the_plugin_option_points_at_the_copy(job: Job) -> None:
    assert pin.build_plugins(job, ["/s"]) == [{"type": "local", "path": str(job.path("plugin"))}]


def test_a_skill_outside_git_has_no_commit(job: Job, tmp_path: Path) -> None:
    source = make_skill(tmp_path)
    pin.copy_skills(job, [str(source)])
    [event] = pins(job)
    assert (event["name"], event["source"]) == ("triage", str(source))
    assert (event["commit"], event["dirty"]) == (None, None)


def test_a_skill_in_git_records_its_commit_and_changes(tmp_path: Path) -> None:
    source = make_skill(tmp_path)
    commit = commit_all(tmp_path)
    assert pin.describe_source(source) == Pin("triage", str(source), commit, False)
    (source / "SKILL.md").write_text("edited")
    assert pin.describe_source(source).dirty is True


def test_git_missing_is_no_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def absent(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", absent)
    assert pin.run_git(tmp_path, "rev-parse", "HEAD") is None
