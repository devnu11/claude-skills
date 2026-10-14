"""The team's presentation of a story to the Customer Proxy.

Where it lives, what it must hold, and the copy into the Proxy's sandbox.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from . import sandbox, story_spec, system
from .config import Config, Environment
from .gates import READY, Outcome, StoryState, Verdict
from .git_ops import Git
from .seeds import Seeds, seed_dir

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
    "document": Recipe(Need.WORKSPACE),
}
NO_GUIDE_TEXT = "{path} is missing or empty; write the customer's guide there"
NO_WORKSPACE_TEXT = "{path} is missing; put the demo or evidence files the customer tries there"
EMPTY_TEXT = "{path} is empty; put the demo or evidence files the customer tries there"
HOLLOW_TEXT = (
    "{path} holds only {held}; add the demo or evidence files themselves, "
    "for example {path}/DEMO.md"
)
GAP_LINE = "story {story} has no presentation for acceptance environment '{environment}': {gap}"
LAYOUT_HEAD = (
    "## Presentations to build\n\n"
    "One presentation per acceptance environment this story's ACs name. Each guide covers only\n"
    "that environment's ACs. Except for `manual`, its workspace/ must hold the demo or evidence\n"
    "files themselves, not only the empty git repo."
)
LAYOUT_LINE = "- {name} ({kind}): {path}/ ({acs})"
STOP_HELD = "story {story} presentation did not stop: {held}"
TRIAL_VERDICTS = {sandbox.NotUp: Verdict.BOUNCE, sandbox.PortBusy: Verdict.HOLD}


@dataclass(frozen=True)
class Showing:
    """One story's presentation to one acceptance environment (AE1)."""

    story: str
    environment: Environment


class Gap(StrEnum):
    """What can be missing from a showing, in the order it is checked (AE3)."""

    NO_GUIDE = "no_guide"
    NO_WORKSPACE = "no_workspace"
    EMPTY = "empty"
    HOLLOW = "hollow"


GAPS: dict[Gap, str] = {
    Gap.NO_GUIDE: NO_GUIDE_TEXT,
    Gap.NO_WORKSPACE: NO_WORKSPACE_TEXT,
    Gap.EMPTY: EMPTY_TEXT,
    Gap.HOLLOW: HOLLOW_TEXT,
}


def story_root(config: Config, story_id: str) -> Path:
    """The dir holding ``story_id``'s showing dirs."""
    return config.run_dir / PRESENTATION_DIR / story_id


def source_dir(config: Config, showing: Showing) -> Path:
    """Where the integration-tester builds ``showing``."""
    return story_root(config, showing.story) / showing.environment.name


def workspace_of(config: Config, showing: Showing) -> Path:
    """The git workspace inside ``showing``'s dir."""
    return source_dir(config, showing) / WORKSPACE


def showings(config: Config, story_id: str) -> list[Showing]:
    """One showing per environment the story's ACs name, in config order."""
    names = story_spec.environment_names(config, story_id)
    return [Showing(story_id, config.environment(n)) for n in names]  # type: ignore[arg-type]


def recipe_of(environment: Environment) -> Recipe:
    """The recipe of an environment's kind."""
    return PRESENTATIONS[environment.kind]


def presented_source(config: Config, showing: Showing | None) -> Path | None:
    """The showing's dir when it exists, else ``None``."""
    if showing is None:
        return None
    source = source_dir(config, showing)
    return source if system.is_dir(source) else None


@dataclass
class Trial:
    """Starts a story's services from its presentations, as the Proxy will get them."""

    config: Config
    prepare: sandbox.PrepareFn = field(default_factory=lambda: sandbox.Preparer().prepare)

    def liveness(self, story: StoryState) -> Outcome:
        """Try each service showing in config order; the first failure is the result (AE4)."""
        live = [
            s
            for s in showings(self.config, story.id)
            if recipe_of(s.environment).check is Check.SERVICE
        ]
        passed: list[Outcome] = []
        for showing in live:
            outcome = self._live(showing)
            if outcome.verdict is not Verdict.PASS:
                return outcome
            passed.append(outcome)
        return Outcome(Verdict.PASS, "; ".join(o.reason for o in passed) or READY)

    def _live(self, showing: Showing) -> Outcome:
        order = sandbox.Order(showing.environment, presented_source(self.config, showing))
        try:
            prepared = self.prepare(self.config, order)
        except (sandbox.NotUp, sandbox.PortBusy) as exc:
            reason = f"story {showing.story} presentation is not up: {exc}"
            return Outcome(TRIAL_VERDICTS[type(exc)], reason)
        return _stopped(prepared, showing.story)


def _stopped(prepared: sandbox.Prepared, story: str) -> Outcome:
    """PASS once the service is stopped and its port is free; HOLD if the port stays in use."""
    held = prepared.stop()
    if held:
        return Outcome(Verdict.HOLD, STOP_HELD.format(story=story, held=held))
    return Outcome(Verdict.PASS, f"{READY}; {prepared.probe_url()} answered")


def copied_workspace(root: Path) -> Path:
    """Where ``copy_into`` puts the workspace under the sandbox ``root``."""
    return root / PRESENTATION_DIR / WORKSPACE


def lay_out(config: Config, story: StoryState) -> Path:
    """Create every showing's dir and git workspace when missing; keep what is there (s65)."""
    if not sandbox.SAFE_NAME.fullmatch(story.id):
        raise sandbox.SandboxError(f"story id {story.id!r} must match {sandbox.SAFE_NAME.pattern}")
    system.make_dirs(story_root(config, story.id))
    for showing in showings(config, story.id):
        _lay_out_one(config, showing)
    return story_root(config, story.id)


def _lay_out_one(config: Config, showing: Showing) -> None:
    system.make_dirs(source_dir(config, showing))
    if recipe_of(showing.environment).need is Need.WORKSPACE:
        _ensure_workspace(workspace_of(config, showing))
        story_seeds(config, showing).plant()


def story_seeds(config: Config, showing: Showing) -> Seeds:
    """The showing environment's seeds for its source workspace (S3a)."""
    return Seeds(seed_dir(config.repo, showing.environment), workspace_of(config, showing))


def _ensure_workspace(workspace: Path) -> None:
    # Its own .git, or every git command in it would climb to the team's repo.
    system.make_dirs(workspace)
    if not system.exists(workspace / ".git"):
        Git(workspace).run("init", "-q")


def missing(config: Config, story: StoryState) -> str | None:
    """Every gap in the story's showings, one line each, or ``None`` when all are ready (AE3)."""
    lines = [_line(s, _gap(config, s)) for s in showings(config, story.id)]
    found = "\n".join(line for line in lines if line)
    return found or None


def _line(showing: Showing, gap: str | None) -> str:
    if gap is None:
        return ""
    return GAP_LINE.format(story=showing.story, environment=showing.environment.name, gap=gap)


def _gap(config: Config, showing: Showing) -> str | None:
    source = source_dir(config, showing)
    if not _guide_written(source):
        return GAPS[Gap.NO_GUIDE].format(path=_rel(config, source / GUIDE))
    if recipe_of(showing.environment).need is not Need.WORKSPACE:
        return None
    return _workspace_gap(config, showing)


def _workspace_gap(config: Config, showing: Showing) -> str | None:
    workspace, seeds = workspace_of(config, showing), story_seeds(config, showing)
    path = _rel(config, workspace)
    if not system.is_dir(workspace):
        return GAPS[Gap.NO_WORKSPACE].format(path=path)
    entries = {p.name for p in system.list_dir(workspace)}
    if not entries:
        return GAPS[Gap.EMPTY].format(path=path)
    if entries <= {".git", *seeds.names()}:
        return GAPS[Gap.HOLLOW].format(path=path, held=_held(entries, seeds))
    return None


def _held(entries: set[str], seeds: Seeds) -> str:
    """What a hollow workspace holds: ``.git`` first, then the seeds sorted."""
    names = [n for n in (".git", *seeds.names()) if n in entries]
    return ", ".join(names)


def _rel(config: Config, path: Path) -> str:
    return path.relative_to(config.repo).as_posix()


def _guide_written(source: Path) -> bool:
    guide = source / GUIDE
    return system.is_file(guide) and bool(system.read_text(guide).strip())


def layout_section(config: Config, story_id: str) -> str:
    """The integration-tester's prompt section naming each showing's dir, kind and ACs (AE10)."""
    found = showings(config, story_id)
    if not found:
        return ""
    ids = _ac_ids(config, story_id)
    lines = [_layout_line(config, s, ids) for s in found]
    return "\n".join([LAYOUT_HEAD, *lines])


def _ac_ids(config: Config, story_id: str) -> dict[str, list[str]]:
    spec = story_spec.read(config, story_id).spec
    ids: dict[str, list[str]] = {}
    for c in spec.criteria if spec else ():
        ids.setdefault(c.environment, []).append(c.id)
    return ids


def _layout_line(config: Config, showing: Showing, ids: dict[str, list[str]]) -> str:
    environment = showing.environment
    return LAYOUT_LINE.format(
        name=environment.name,
        kind=environment.kind,
        path=_rel(config, source_dir(config, showing)),
        acs=", ".join(ids[environment.name]),
    )


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
