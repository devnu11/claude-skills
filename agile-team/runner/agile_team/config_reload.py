"""s173: the run follows the committed config (ADR-0094).

``ConfigWatch`` compares the ``.agile-team.toml`` blob at the main checkout's HEAD with
the one the run last took or refused. A new valid blob is swapped in by assignment, so a
running story view keeps its own objects; a bad one changes nothing and is reported once.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import config as config_mod
from . import sandbox
from .commands import CommandRunner
from .events import Event, EventKind
from .gates import Pipeline
from .git_ops import Git, GitError
from .providers import Providers
from .roles import RoleBook
from .upstream import Upstream

if TYPE_CHECKING:
    from .dispatch import Runtime

SECTIONS: tuple[tuple[str, str], ...] = (
    ("team", "team"),
    ("toolchain", "toolchain"),
    ("gates", "gates"),
    ("upstream", "upstream"),
    ("health", "health"),
    ("dashboard", "dashboard"),
    ("environments", "environment"),
    ("tools", "tool"),
    ("roles", "roles"),
    ("providers", "providers"),
)  # (Config field, TOML section name), in event order
BAD_CONFIG = (config_mod.ConfigError, TypeError, AttributeError, ValueError)  # R6


@dataclass(frozen=True)
class ConfigChange:
    """R7: one new committed config blob, taken (``error`` empty) or refused."""

    sha: str
    blob: str
    sections: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def data(self) -> dict[str, Any]:
        """The ``config`` event's data and the report's ``config`` entry."""
        return {"sha": self.sha, "blob": self.blob, "sections": self.sections, "error": self.error}


@dataclass
class LiveConfig:
    """R4: what a run derives from its config, swapped as one."""

    config: config_mod.Config
    book: RoleBook
    pipeline: Pipeline
    providers: Providers
    shell: Callable[[Path], CommandRunner]


def read_blob(git: Git) -> str:
    """R1, R3: the blob id of ``.agile-team.toml`` at HEAD; ``""`` when there is none."""
    code, out = git.attempt("rev-parse", f"HEAD:{config_mod.CONFIG_NAME}")
    return out.strip() if code == 0 else ""


def find_last_change(git: Git) -> str:
    """R7: the commit that last changed ``.agile-team.toml`` at HEAD; ``""`` when none."""
    code, out = git.attempt("log", "-1", "--format=%H", "HEAD", "--", config_mod.CONFIG_NAME)
    return out.strip() if code == 0 else ""


def find_changed_sections(old: config_mod.Config, new: config_mod.Config) -> list[str]:
    """R7: the TOML names of the sections whose parsed value differs, in SECTIONS order."""
    return [name for attr, name in SECTIONS if getattr(old, attr) != getattr(new, attr)]


def check_static(config: config_mod.Config, book: RoleBook) -> list[str]:
    """``config.validate`` against ``book``'s roles and the sandbox's environment kinds."""
    known = config_mod.Known(book.names(), set(sandbox.ENVIRONMENT_KINDS))
    return config_mod.validate(config, known)


def describe_error(exc: Exception) -> str:
    """R6: a ``ConfigError`` message as is, any other class with its name."""
    if isinstance(exc, config_mod.ConfigError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


@dataclass
class ConfigWatch:
    """R2 to R7: notice a new committed config and take it, or report why not."""

    runtime: Runtime

    def update(self) -> ConfigChange | None:
        """The change a new HEAD blob brings, already applied and logged; ``None`` if none."""
        rt = self.runtime
        blob = read_blob(rt.main)
        if rt.config_blob is None:
            rt.config_blob = blob
        if blob == rt.config_blob:
            return None
        rt.config_blob = blob
        return self._record(self._take(blob))

    def _take(self, blob: str) -> ConfigChange:
        sha = find_last_change(self.runtime.main)
        try:
            new = self._read_config(blob)
            live = self.runtime.live_for(new)
        except (*BAD_CONFIG, GitError) as exc:
            return ConfigChange(sha, blob, [], describe_error(exc))
        sections = find_changed_sections(self.runtime.config, new)
        self._apply_live(live, sections)
        return ConfigChange(sha, blob, sections, "")

    def _read_config(self, blob: str) -> config_mod.Config:
        rt = self.runtime
        if not blob:
            raise config_mod.ConfigError(f"{config_mod.CONFIG_NAME} not found at HEAD")
        raw = config_mod.parse_text(rt.main.run("cat-file", "blob", blob))
        return replace(config_mod.from_raw(rt.config.repo, raw), run_home=rt.config.run_home)

    def _apply_live(self, live: LiveConfig, sections: list[str]) -> None:
        rt = self.runtime
        rt.config, rt.book, rt.pipeline = live.config, live.book, live.pipeline
        rt.providers, rt.shell = live.providers, live.shell
        rt.pipeline.checks.stages = rt.stage_log.open
        if "upstream" in sections:
            rt.upstream = Upstream(rt.main, live.config.upstream)

    def _record(self, change: ConfigChange) -> ConfigChange:
        self.runtime.events.emit(Event(EventKind.CONFIG, None, None, change.data))
        return change
