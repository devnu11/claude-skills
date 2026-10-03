"""Load and validate ``<repo>/.agile-team.toml``.

The file is the single place a repo customizes the team: toolchain commands
and globs, gates, deliveries, budget and per-role overrides. Role prompt
addenda live beside it in ``.team/roles/*.md`` and are handled by ``roles``.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_NAME = ".agile-team.toml"
TEAM_DIR = ".team"
RUN_DIR = ".team/run"
DEFAULT_KEY_FILE = ".team/run/api-key"
CADENCES = ("sprint", "until-blocker")
ARTIFACT_POLICIES = ("committed", "ignored")
PIPELINE_STEPS = (
    "design",
    "tests",
    "implement",
    "quality",
    "review",
    "design-review",
    "e2e",
    "acceptance",
)
TOOLCHAIN_COMMANDS = ("test", "coverage", "lint", "static")
GLOB_KEYS = ("source", "tests", "e2e", "ci")


class ConfigError(Exception):
    """Raised when the config file is missing or cannot be parsed."""


@dataclass
class Toolchain:
    """Per-repo commands and the globs that role scopes resolve against."""

    preset: str = ""
    commands: dict[str, str] = field(default_factory=dict)
    pragma: str = ""
    globs: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Gates:
    """Thresholds and switches for the story pipeline."""

    coverage: float = 95.0
    round_cap: int = 3
    steps: list[str] = field(default_factory=lambda: list(PIPELINE_STEPS))


@dataclass
class Delivery:
    """One way a customer reaches the product (see ``sandbox.DELIVERY_KINDS``)."""

    name: str
    kind: str
    prepare: str = ""
    url: str = ""
    commands: list[str] = field(default_factory=list)
    bin: list[str] = field(default_factory=list)


@dataclass
class Team:
    """Run-level settings chosen during ``init``."""

    docs_dir: str = "docs"
    artifacts: str = "committed"
    key_file: str = DEFAULT_KEY_FILE
    cadence: str = "sprint"
    budget_usd: float = 20.0
    manager_every_pct: int = 25


@dataclass
class Config:
    """Parsed ``.agile-team.toml`` for one repo."""

    repo: Path
    team: Team = field(default_factory=Team)
    toolchain: Toolchain = field(default_factory=Toolchain)
    gates: Gates = field(default_factory=Gates)
    deliveries: list[Delivery] = field(default_factory=list)
    roles: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def run_dir(self) -> Path:
        return self.repo / RUN_DIR

    def placeholders(self) -> dict[str, list[str]]:
        """Values for ``{name}`` placeholders in role glob lists."""
        values = {key: list(self.toolchain.globs.get(key, [])) for key in GLOB_KEYS}
        values["docs"] = [f"{self.team.docs_dir.rstrip('/')}/**"]
        values["config"] = [CONFIG_NAME]
        return values

    def delivery(self, name: str | None) -> Delivery | None:
        """The named delivery, or the first one when ``name`` is empty."""
        if not name:
            return self.deliveries[0] if self.deliveries else None
        return next((d for d in self.deliveries if d.name == name), None)


def config_path(repo: Path) -> Path:
    return repo / CONFIG_NAME


def read_raw(repo: Path) -> dict[str, Any]:
    """Parse the config file into plain TOML data."""
    path = config_path(repo)
    if not path.is_file():
        raise ConfigError(f"{CONFIG_NAME} not found in {repo}; run `agile-team init`")
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{CONFIG_NAME}: {exc}") from exc


def from_raw(repo: Path, raw: dict[str, Any]) -> Config:
    """Build a ``Config`` from parsed TOML data."""
    return Config(
        repo=repo,
        team=_team(raw.get("team", {})),
        toolchain=_toolchain(raw.get("toolchain", {})),
        gates=_gates(raw.get("gates", {})),
        deliveries=[_delivery(d) for d in raw.get("delivery", [])],
        roles=dict(raw.get("roles", {})),
    )


def load(repo: Path) -> Config:
    """Read and parse the config for ``repo``."""
    return from_raw(repo, read_raw(repo))


def _team(raw: dict[str, Any]) -> Team:
    return Team(**{k: v for k, v in raw.items() if k in Team.__dataclass_fields__})


def _toolchain(raw: dict[str, Any]) -> Toolchain:
    commands = {k: raw[k] for k in TOOLCHAIN_COMMANDS if k in raw}
    return Toolchain(
        preset=raw.get("preset", ""),
        commands=commands,
        pragma=raw.get("pragma", ""),
        globs={k: list(v) for k, v in raw.get("globs", {}).items()},
    )


def _gates(raw: dict[str, Any]) -> Gates:
    return Gates(**{k: v for k, v in raw.items() if k in Gates.__dataclass_fields__})


def _delivery(raw: dict[str, Any]) -> Delivery:
    return Delivery(**{k: v for k, v in raw.items() if k in Delivery.__dataclass_fields__})


def validate(config: Config, known_roles: set[str], delivery_kinds: set[str]) -> list[str]:
    """Return human-readable problems with ``config``; empty means valid."""
    problems: list[str] = []
    problems += _validate_team(config.team)
    problems += _validate_toolchain(config.toolchain)
    problems += _validate_gates(config.gates)
    problems += _validate_deliveries(config.deliveries, delivery_kinds)
    problems += _validate_roles(config.roles, known_roles)
    return problems


def _validate_team(team: Team) -> list[str]:
    problems = []
    if team.cadence not in CADENCES:
        problems.append(f"team.cadence must be one of {CADENCES}, got {team.cadence!r}")
    if team.artifacts not in ARTIFACT_POLICIES:
        problems.append(f"team.artifacts must be one of {ARTIFACT_POLICIES}")
    if team.budget_usd <= 0:
        problems.append("team.budget_usd must be positive")
    if not 0 < team.manager_every_pct <= 100:
        problems.append("team.manager_every_pct must be in 1..100")
    return problems


def _validate_toolchain(toolchain: Toolchain) -> list[str]:
    problems = [
        f"toolchain.{name} is not set"
        for name in ("test", "coverage")
        if not toolchain.commands.get(name)
    ]
    problems += [
        f"toolchain.globs.{name} is empty"
        for name in ("source", "tests")
        if not toolchain.globs.get(name)
    ]
    return problems


def _validate_gates(gates: Gates) -> list[str]:
    problems = [
        f"gates.steps has unknown step {s!r}" for s in gates.steps if s not in PIPELINE_STEPS
    ]
    if not 0 <= gates.coverage <= 100:
        problems.append("gates.coverage must be in 0..100")
    if gates.round_cap < 1:
        problems.append("gates.round_cap must be at least 1")
    return problems


def _validate_deliveries(deliveries: list[Delivery], kinds: set[str]) -> list[str]:
    problems = [
        f"delivery {d.name!r} has unknown kind {d.kind!r}"
        for d in deliveries
        if d.kind not in kinds
    ]
    names = [d.name for d in deliveries]
    problems += [
        f"delivery name {n!r} is repeated" for n in sorted(set(names)) if names.count(n) > 1
    ]
    problems += [
        f"delivery {d.name!r} (web) needs a url"
        for d in deliveries
        if d.kind == "web" and not d.url
    ]
    problems += [
        f"delivery {d.name!r} (harness) needs commands"
        for d in deliveries
        if d.kind == "harness" and not d.commands
    ]
    return problems


def _validate_roles(roles: dict[str, dict[str, Any]], known: set[str]) -> list[str]:
    """A config-only role is allowed when it ``extends`` a known role."""
    problems = []
    for name, override in roles.items():
        base = override.get("extends")
        if name in known:
            continue
        if not base:
            problems.append(f"roles.{name} is unknown; set extends or add .team/roles/{name}.md")
        elif base not in known:
            problems.append(f"roles.{name} extends unknown role {base!r}")
    return problems
