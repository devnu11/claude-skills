"""The team's presentation of a story to the Customer Proxy.

Where it lives, what it must hold, and the copy into the Proxy's sandbox.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from . import sandbox, system
from .config import Config
from .gates import READY, Outcome, StoryState, Verdict
from .git_ops import Git

PRESENTATION_DIR = "presentation"
GUIDE = "PRESENTATION.md"
WORKSPACE = "workspace"


class Need(StrEnum):
    """What the team must hand over besides the guide."""

    WORKSPACE = "workspace"
    GUIDE_ONLY = "guide-only"


class Check(StrEnum):
    """How "presentation ready" is checked: files only, or files plus a live service."""

    FILES = "files"
    SERVICE = "service"


@dataclass(frozen=True)
class Recipe:
    """One row of ``PRESENTATIONS``: what to hand over and how to check it."""

    need: Need
    check: Check = Check.FILES


PRESENTATIONS: dict[str, Recipe] = {
    "package": Recipe(Need.WORKSPACE),
    "script": Recipe(Need.WORKSPACE),
    "web": Recipe(Need.WORKSPACE, Check.SERVICE),
    "library": Recipe(Need.WORKSPACE),
    "harness": Recipe(Need.WORKSPACE),
    "manual": Recipe(Need.GUIDE_ONLY),
}
STOP_HELD = "story {story} presentation did not stop: {held}"
TRIAL_VERDICTS = {sandbox.NotUp: Verdict.BOUNCE, sandbox.PortBusy: Verdict.HOLD}


def source_dir(config: Config, story_id: str) -> Path:
    """Where the integration-tester builds ``story_id``'s presentation."""
    return config.run_dir / PRESENTATION_DIR / story_id


def recipe_of(config: Config, story: StoryState) -> Recipe:
    """The story's delivery recipe (guide only when none is configured)."""
    delivery = config.delivery(story.delivery)
    return PRESENTATIONS[delivery.kind] if delivery else Recipe(Need.GUIDE_ONLY)


def presented_source(config: Config, story: StoryState | None) -> Path | None:
    """The story's presentation dir when it exists, else ``None``."""
    if story is None:
        return None
    source = source_dir(config, story.id)
    return source if system.is_dir(source) else None


@dataclass
class Trial:
    """Starts a story's service from its presentation, as the Proxy will get it, and probes it."""

    config: Config
    prepare: sandbox.PrepareFn = field(default_factory=lambda: sandbox.Preparer().prepare)

    def liveness(self, story: StoryState) -> Outcome:
        """Pass a file-only delivery; for a service, start it, probe it and stop it."""
        delivery = self.config.delivery(story.delivery)
        if delivery is None or recipe_of(self.config, story).check is Check.FILES:
            return Outcome(Verdict.PASS, READY)
        return self._try(sandbox.Order(delivery, presented_source(self.config, story)), story)

    def _try(self, order: sandbox.Order, story: StoryState) -> Outcome:
        try:
            prepared = self.prepare(self.config, order)
        except (sandbox.NotUp, sandbox.PortBusy) as exc:
            reason = f"story {story.id} presentation is not up: {exc}"
            return Outcome(TRIAL_VERDICTS[type(exc)], reason)
        return _stopped(prepared, story)


def _stopped(prepared: sandbox.Prepared, story: StoryState) -> Outcome:
    """PASS once the service is stopped and its port is free; HOLD if the port stays in use."""
    held = prepared.stop()
    if held:
        return Outcome(Verdict.HOLD, STOP_HELD.format(story=story.id, held=held))
    return Outcome(Verdict.PASS, f"{READY}; {prepared.probe_url()} answered")


def workspace_of(config: Config, story_id: str) -> Path:
    """The git workspace inside ``story_id``'s presentation dir."""
    return source_dir(config, story_id) / WORKSPACE


def copied_workspace(root: Path) -> Path:
    """Where ``copy_into`` puts the workspace under the sandbox ``root``."""
    return root / PRESENTATION_DIR / WORKSPACE


def lay_out(config: Config, story: StoryState) -> Path:
    """Create the presentation dir and git workspace when missing; keep what is there (s65)."""
    if not sandbox.SAFE_NAME.fullmatch(story.id):
        raise sandbox.SandboxError(f"story id {story.id!r} must match {sandbox.SAFE_NAME.pattern}")
    source = source_dir(config, story.id)
    system.make_dirs(source)
    if recipe_of(config, story).need is Need.WORKSPACE:
        _ensure_workspace(source / WORKSPACE)
    return source


def _ensure_workspace(workspace: Path) -> None:
    # Its own .git, or every git command in it would climb to the team's repo.
    system.make_dirs(workspace)
    if not system.exists(workspace / ".git"):
        Git(workspace).run("init", "-q")


def missing(config: Config, story: StoryState) -> str | None:
    """Why the story's presentation is incomplete, or ``None`` when it is ready."""
    source = source_dir(config, story.id)
    if not _guide_written(source):
        return _reason(config, source / GUIDE, story)
    if recipe_of(config, story).need is Need.WORKSPACE and not _has_content(source / WORKSPACE):
        return _reason(config, source / WORKSPACE, story)
    return None


def _reason(config: Config, path: Path, story: StoryState) -> str:
    rel = path.relative_to(config.repo).as_posix()
    return f"story {story.id} has no presentation: {rel} is missing or empty"


def _guide_written(source: Path) -> bool:
    guide = source / GUIDE
    return system.is_file(guide) and bool(system.read_text(guide).strip())


def _has_content(workspace: Path) -> bool:
    return system.is_dir(workspace) and any(p.name != ".git" for p in system.list_dir(workspace))


def copy_into(source: Path, root: Path) -> Path:
    """Copy the presentation into the sandbox ``root``; symlinks stay links."""
    target = root / PRESENTATION_DIR
    system.copy_tree(source, target)
    return target


def prompt_section(copied: Path | None) -> str:
    """The Proxy's prompt section naming the copy and quoting its guide."""
    if copied is None:
        return ""
    return (
        "## What the team presents\n\n"
        f"The team's presentation is in {copied}. The customer's workspace is "
        f"`{WORKSPACE}/` in it. If the presentation is missing or broken, return "
        "`changes_requested` with `next_role: integration-tester`.\n\n"
        f"{GUIDE}:\n\n{system.read_text(copied / GUIDE).strip()}"
    )
