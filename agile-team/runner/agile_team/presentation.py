"""The team's presentation of a story to the Customer Proxy.

Where it lives, what it must hold, and the copy into the Proxy's sandbox.
"""

from __future__ import annotations

import shutil
from enum import StrEnum
from pathlib import Path

from . import sandbox
from .config import Config
from .gates import StoryState
from .git_ops import Git

PRESENTATION_DIR = "presentation"
GUIDE = "PRESENTATION.md"
WORKSPACE = "workspace"


class Need(StrEnum):
    """What the team must hand over besides the guide."""

    WORKSPACE = "workspace"
    GUIDE_ONLY = "guide-only"


PRESENTATIONS: dict[str, Need] = {
    "package": Need.WORKSPACE,
    "script": Need.WORKSPACE,
    "web": Need.WORKSPACE,
    "library": Need.WORKSPACE,
    "harness": Need.WORKSPACE,
    "manual": Need.GUIDE_ONLY,
}


def source_dir(config: Config, story_id: str) -> Path:
    """Where the integration-tester builds ``story_id``'s presentation."""
    return config.run_dir / PRESENTATION_DIR / story_id


def need_of(config: Config, story: StoryState) -> Need:
    """What the story's delivery needs presented (guide only when none is configured)."""
    delivery = config.delivery(story.delivery)
    return PRESENTATIONS[delivery.kind] if delivery else Need.GUIDE_ONLY


def lay_out(config: Config, story: StoryState) -> Path:
    """Wipe and recreate the story's presentation dir, with a git workspace when needed."""
    if not sandbox.SAFE_NAME.fullmatch(story.id):
        raise sandbox.SandboxError(f"story id {story.id!r} must match {sandbox.SAFE_NAME.pattern}")
    source = sandbox.fresh_dir(source_dir(config, story.id))
    if need_of(config, story) is Need.WORKSPACE:
        _init_workspace(source / WORKSPACE)
    return source


def _init_workspace(workspace: Path) -> None:
    # Its own .git, or every git command in it would climb to the team's repo.
    workspace.mkdir()
    Git(workspace).run("init", "-q")


def missing(config: Config, story: StoryState) -> str | None:
    """Why the story's presentation is incomplete, or ``None`` when it is ready."""
    source = source_dir(config, story.id)
    if not _guide_written(source):
        return _reason(config, source / GUIDE, story)
    if need_of(config, story) is Need.WORKSPACE and not _has_content(source / WORKSPACE):
        return _reason(config, source / WORKSPACE, story)
    return None


def _reason(config: Config, path: Path, story: StoryState) -> str:
    rel = path.relative_to(config.repo).as_posix()
    return f"story {story.id} has no presentation: {rel} is missing or empty"


def _guide_written(source: Path) -> bool:
    guide = source / GUIDE
    return guide.is_file() and bool(guide.read_text().strip())


def _has_content(workspace: Path) -> bool:
    return workspace.is_dir() and any(p.name != ".git" for p in workspace.iterdir())


def copy_into(source: Path, root: Path) -> Path:
    """Copy the presentation into the sandbox ``root``; symlinks stay links."""
    return Path(shutil.copytree(source, root / PRESENTATION_DIR, symlinks=True))


def prompt_section(copied: Path | None) -> str:
    """The Proxy's prompt section naming the copy and quoting its guide."""
    if copied is None:
        return ""
    return (
        "## What the team presents\n\n"
        f"The team's presentation is in {copied}. The customer's workspace is "
        f"`{WORKSPACE}/` in it. If the presentation is missing or broken, return "
        "`changes_requested` with `next_role: integration-tester`.\n\n"
        f"{GUIDE}:\n\n{(copied / GUIDE).read_text().strip()}"
    )
