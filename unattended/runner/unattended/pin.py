"""Pinned skills: a prompt job runs the skill versions it started with (``--skill DIR``).

At ``start`` each ``--skill`` directory (one holding ``SKILL.md``) is copied
into the job's ``plugin/skills/<name>/``, beside a ``.claude-plugin/plugin.json``
that makes ``plugin/`` a local plugin, and every run loads that plugin. Edits to
the source, a ``git pull`` or a chezmoi apply mid-job change nothing: resumes
see the same files. Each pin logs a ``pin`` event with the name, the source,
and the source's git commit and whether its tree had uncommitted changes
(``null`` outside git), so a run can be traced to the version it used.

Plugin skills are namespaced (``unattended-pinned:<name>``). A skill of the
same name in the user's own settings still loads beside it unless
``--setting-sources`` leaves the ``user`` layer out.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .store import Job

PLUGIN_DIR = "plugin"
PLUGIN_NAME = "unattended-pinned"
PLUGIN_DESCRIPTION = "Skills an unattended job pinned at its start"
SKILL_FILE = "SKILL.md"
IGNORED = shutil.ignore_patterns(".git", ".venv", "__pycache__", "node_modules", ".*_cache")
GIT_TIMEOUT = 30  # seconds


@dataclass(frozen=True)
class Pin:
    """Where a pinned skill came from: its name, source directory and git state."""

    name: str
    source: str
    commit: str | None
    dirty: bool | None


def find_skill_problems(sources: list[Path]) -> list[str]:
    """Each source that is not a skill directory, and each name used twice."""
    missing = [f"--skill {s}: no {SKILL_FILE} there" for s in sources if not is_skill(s)]
    names = [source.name for source in sources]
    twice = sorted({f"--skill: two skills named {n!r}" for n in names if names.count(n) > 1})
    return missing + twice


def is_skill(source: Path) -> bool:
    """True for a directory holding ``SKILL.md``."""
    return (source / SKILL_FILE).is_file()


def copy_skills(job: Job, sources: list[str]) -> None:
    """Copy each skill into the job's plugin and log where it came from."""
    if not sources:
        return
    root = job.path(PLUGIN_DIR)
    write_manifest(root)
    for source in map(Path, sources):
        shutil.copytree(source, root / "skills" / source.name, ignore=IGNORED)
        job.event("pin", asdict(describe_source(source)))


def write_manifest(root: Path) -> None:
    """The ``plugin.json`` that makes ``root`` a local plugin."""
    manifest = root / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": PLUGIN_NAME, "description": PLUGIN_DESCRIPTION}))


def describe_source(source: Path) -> Pin:
    """``source`` with its git commit and whether the tree under it has changes."""
    commit = run_git(source, "rev-parse", "HEAD")
    status = run_git(source, "status", "--porcelain", "--", ".") if commit else None
    return Pin(source.name, str(source), commit, None if status is None else status != "")


def run_git(source: Path, *argv: str) -> str | None:
    """``git argv`` in ``source``: its stripped output, or None when git fails or is absent."""
    try:
        done = subprocess.run(
            ["git", *argv], cwd=source, capture_output=True, text=True, timeout=GIT_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def build_plugins(job: Job, sources: list[str]) -> list[Any]:
    """The SDK ``plugins`` option: the job's pinned-skill plugin, when it has one."""
    return [{"type": "local", "path": str(job.path(PLUGIN_DIR))}] if sources else []
