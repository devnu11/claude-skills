"""Load and validate ``<repo>/.agile-team.toml``.

The file is the single place a repo customizes the team: toolchain commands
and globs, gates, deliveries, budget and per-role overrides. Role prompt
addenda live beside it in ``.team/roles/*.md`` and are handled by ``roles``.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
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


@dataclass(frozen=True)
class Known:
    """Names the config may refer to: resolvable roles and delivery kinds."""

    roles: set[str]
    delivery_kinds: set[str]


Rule = tuple[Callable[[Any], bool], str]

TEAM_RULES: tuple[Rule, ...] = (
    (lambda t: t.cadence in CADENCES, f"team.cadence must be one of {CADENCES}"),
    (
        lambda t: t.artifacts in ARTIFACT_POLICIES,
        f"team.artifacts must be one of {ARTIFACT_POLICIES}",
    ),
    (lambda t: t.budget_usd > 0, "team.budget_usd must be positive"),
    (lambda t: 0 < t.manager_every_pct <= 100, "team.manager_every_pct must be in 1..100"),
)
TOOLCHAIN_RULES: tuple[Rule, ...] = (
    (lambda t: bool(t.commands.get("test")), "toolchain.test is not set"),
    (lambda t: bool(t.commands.get("coverage")), "toolchain.coverage is not set"),
    (lambda t: bool(t.globs.get("source")), "toolchain.globs.source is empty"),
    (lambda t: bool(t.globs.get("tests")), "toolchain.globs.tests is empty"),
)
GATE_RULES: tuple[Rule, ...] = (
    (lambda g: set(g.steps) <= set(PIPELINE_STEPS), f"gates.steps must be among {PIPELINE_STEPS}"),
    (lambda g: 0 <= g.coverage <= 100, "gates.coverage must be in 0..100"),
    (lambda g: g.round_cap >= 1, "gates.round_cap must be at least 1"),
)
DELIVERY_RULES: tuple[Rule, ...] = (
    (lambda d: bool(SAFE_NAME.fullmatch(d.name)), "name must be lowercase letters, digits, - or _"),
    (lambda d: d.kind != "web" or bool(d.url), "(web) needs a url"),
    (lambda d: d.kind != "harness" or bool(d.commands), "(harness) needs commands"),
)
SAFE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")
REPEATED_DELIVERY = "delivery name {name!r} is repeated"
MISSING_ROLE = "roles.{name} is unknown; set extends or add .team/roles/{name}.md"
DANGLING_ROLE = "roles.{name} extends unknown role {base!r}"


def broken(rules: tuple[Rule, ...], subject: Any) -> list[str]:
    """Messages of the rules ``subject`` breaks."""
    return [message for ok, message in rules if not ok(subject)]


def validate(config: Config, known: Known) -> list[str]:
    """Return human-readable problems with ``config``; empty means valid."""
    return [
        *broken(TEAM_RULES, config.team),
        *broken(TOOLCHAIN_RULES, config.toolchain),
        *broken(GATE_RULES, config.gates),
        *_validate_deliveries(config.deliveries, known.delivery_kinds),
        *_validate_roles(config.roles, known.roles),
    ]


def _validate_deliveries(deliveries: list[Delivery], kinds: set[str]) -> list[str]:
    names = [d.name for d in deliveries]
    repeated = sorted({n for n in names if names.count(n) > 1})
    problems = [p for d in deliveries for p in _delivery_problems(d, kinds)]
    return problems + [REPEATED_DELIVERY.format(name=n) for n in repeated]


def _delivery_problems(delivery: Delivery, kinds: set[str]) -> list[str]:
    messages = broken(DELIVERY_RULES, delivery)
    if delivery.kind not in kinds:
        messages.append(f"has unknown kind {delivery.kind!r}")
    return [f"delivery {delivery.name!r} {m}" for m in messages]


def _validate_roles(roles: dict[str, dict[str, Any]], known: set[str]) -> list[str]:
    """A config-only role is allowed when it ``extends`` a known role."""
    bases = {n: o.get("extends") for n, o in roles.items() if n not in known}
    missing = [MISSING_ROLE.format(name=n) for n, b in bases.items() if not b]
    dangling = {n: b for n, b in bases.items() if b and b not in known}
    return missing + [DANGLING_ROLE.format(name=n, base=b) for n, b in dangling.items()]
