"""Seed files a delivery's presentation workspace needs; the runner plants missing ones (s105)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from . import config, system
from .config import Delivery

SEED_GONE = (
    "seed directory {source} is missing from the repo; restore it or remove "
    "`seed` from the delivery in .agile-team.toml"
)
BROKEN = (
    "workspace/{name} is broken: {error}. Fix it in the presentation's "
    "workspace/, or delete it so the runner seeds a working one"
)
Check = Callable[[Path], str | None]
PACKAGED_SEED: Path = Path(str(resources.files("agile_team") / "dashboard" / "seed"))
DEFAULT_SEEDS: dict[str, Path] = {"web": PACKAGED_SEED}


def config_problem(path: Path) -> str | None:
    """Why ``path`` (an ``.agile-team.toml``) does not load, or ``None`` when it does."""
    try:
        config.load(path.parent)
    except (config.ConfigError, TypeError, AttributeError, ValueError) as exc:
        return str(exc)
    return None


CHECKS: dict[str, Check] = {config.CONFIG_NAME: config_problem}


def seed_dir(repo: Path, delivery: Delivery | None) -> Path | None:
    """The delivery's seed directory per S1: its override, its kind's default, or ``None``."""
    if delivery is None:
        return None
    if delivery.seed is None:
        return DEFAULT_SEEDS.get(delivery.kind)
    # repo / "" is the repo itself, so "" must return before the join.
    return repo / delivery.seed if delivery.seed else None


@dataclass(frozen=True)
class Seeds:
    """One delivery's seed directory and the workspace it seeds."""

    source: Path | None
    workspace: Path

    def names(self) -> list[str]:
        """Names of the regular files directly in ``source``, sorted; [] if none."""
        if self.source is None or not system.is_dir(self.source):
            return []
        return sorted(p.name for p in system.list_dir(self.source) if system.is_file(p))

    def plant(self) -> None:
        """Write each seed file missing from ``workspace`` (S2)."""
        for name in self.names():
            self._plant_one(name)

    def _plant_one(self, name: str) -> None:
        target = self.workspace / name
        if system.exists(target):
            return
        system.make_dirs(self.workspace)
        system.write_text(target, system.read_text(self.source / name))  # type: ignore[operator]

    def problems(self) -> list[str]:
        """``SEED_GONE`` if ``source`` is no dir; else a ``BROKEN`` line per failed check."""
        if self.source is None:
            return []
        if not system.is_dir(self.source):
            return [SEED_GONE.format(source=self.source)]
        found = (self._problem(name) for name in self.names())
        return [line for line in found if line]

    def _problem(self, name: str) -> str | None:
        check, path = CHECKS.get(name), self.workspace / name
        error = check(path) if check and system.exists(path) else None
        return BROKEN.format(name=name, error=error) if error else None
