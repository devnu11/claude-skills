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

from . import stages, system
from .commands import DEFAULT_TIMEOUT_S
from .providers import DEFAULT as DEFAULT_PROVIDER
from .providers import Billing, Provider, ProviderKind

CONFIG_NAME = ".agile-team.toml"
TEAM_DIR = ".team"
RUN_DIR = ".team/run"
STORIES_DIR = ".team/stories"
REQUIREMENTS_DIR = "requirements"
DEFAULT_KEY_FILE = ".team/run/api-key"
CADENCES = ("sprint", "until-blocker")
API_KEY_AUTH, LOGIN_AUTH = "api-key", "login"
AUTH_MODES = (API_KEY_AUTH, LOGIN_AUTH)
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
DASHBOARD_TOKEN = "[dashboard] token must be a string"
DASHBOARD_COLLAPSE = "[dashboard] collapse_under_s must be a number of seconds, 0 or more"
GLOB_KEYS = ("source", "tests", "e2e", "ci")
UNKNOWN_DELIVERY = "delivery {name!r} is not a configured [[delivery]]; use one of: {names}"
NO_DELIVERY = (
    "delivery {name!r} is not a configured [[delivery]]; .agile-team.toml configures none, "
    "so leave delivery empty or ask the human to add a [[delivery]]"
)


class ConfigError(Exception):
    """Raised when the config file is missing or cannot be parsed."""


@dataclass(frozen=True)
class Targeted:
    """How the runner runs named tests under ``root`` (s69 T1)."""

    root: str
    command: str

    def holds(self, path: str) -> bool:
        """``root`` is "" or ``path`` is under it."""
        return not self.root or path.startswith(self.root.rstrip("/") + "/")

    def relative(self, path: str) -> str:
        """``path`` with ``root/`` removed."""
        return path.removeprefix(self.root.rstrip("/") + "/") if self.root else path


@dataclass
class Toolchain:
    """Per-repo commands and the globs that role scopes resolve against."""

    preset: str = ""
    commands: dict[str, str] = field(default_factory=dict)
    pragma: str = ""
    globs: dict[str, list[str]] = field(default_factory=dict)
    targeted: list[Targeted] = field(default_factory=list)

    def targeted_for(self, path: str) -> Targeted | None:
        """The row with the longest root that holds ``path`` (R4)."""
        rows = [row for row in self.targeted if row.holds(path)]
        return max(rows, key=lambda row: len(row.root), default=None)


DEFAULT_CI_TIMEOUT_S = 1800.0


@dataclass
class Gates:
    """Thresholds and switches for the story pipeline."""

    coverage: float = 95.0
    round_cap: int = 3
    steps: list[str] = field(default_factory=lambda: list(PIPELINE_STEPS))
    repeat: int = 2
    backstop: int = 4
    command_timeout_s: float = DEFAULT_TIMEOUT_S
    ci_timeout_s: float = DEFAULT_CI_TIMEOUT_S


@dataclass
class Delivery:
    """One way a customer reaches the product (see ``sandbox.DELIVERY_KINDS``).

    ``probe``: path joined to ``url`` that must answer 200 before a service counts as up.
    ``seed``: repo-relative directory whose files the runner plants in the presentation
    workspace where missing; absent = the kind's default (``seeds.DEFAULT_SEEDS``),
    ``""`` = none (s105).
    """

    name: str
    kind: str
    prepare: str = ""
    url: str = ""
    commands: list[str] = field(default_factory=list)
    bin: list[str] = field(default_factory=list)
    e2e: str = ""
    seed: str | None = None
    probe: str = ""


@dataclass
class UpstreamSettings:
    """Where the team syncs from and pushes review branches to; an empty remote turns it off."""

    remote: str = "origin"
    branch: str = "main"
    prefix: str = "team/sprint-"


@dataclass
class Team:
    """Run-level settings chosen during ``init``."""

    docs_dir: str = "docs"
    artifacts: str = "committed"
    key_file: str = DEFAULT_KEY_FILE
    cadence: str = "sprint"
    budget_usd: float = 20.0
    manager_every_pct: int = 25
    auth: str = API_KEY_AUTH


@dataclass
class HealthLimits:
    """``[health]``: when the live meter turns amber or red, and the heartbeat pace (s44)."""

    beat_s: float = 20.0
    stale_s: float = 90.0
    amber_tool_s: float = 180.0
    amber_quiet_s: float = 300.0
    red_quiet_s: float = 600.0


@dataclass
class DashboardSettings:
    """``[dashboard]``: a fixed write token for presentations (s83 B19); empty means random."""

    token: str = ""
    collapse_under_s: float = 0.1


@dataclass(frozen=True)
class Tool:
    """``[[tool]]``: a repo's own named tool, owned by DevOps (s99 RS11)."""

    name: str
    description: str = ""
    command: str = ""


@dataclass
class Config:
    """Parsed ``.agile-team.toml`` for one repo."""

    repo: Path
    team: Team = field(default_factory=Team)
    toolchain: Toolchain = field(default_factory=Toolchain)
    gates: Gates = field(default_factory=Gates)
    upstream: UpstreamSettings = field(default_factory=UpstreamSettings)
    health: HealthLimits = field(default_factory=HealthLimits)
    dashboard: DashboardSettings = field(default_factory=DashboardSettings)
    deliveries: list[Delivery] = field(default_factory=list)
    tools: list[Tool] = field(default_factory=list)
    roles: dict[str, dict[str, Any]] = field(default_factory=dict)
    providers: dict[str, Provider] = field(default_factory=dict)

    @property
    def run_dir(self) -> Path:
        return self.repo / RUN_DIR

    @property
    def stories_dir(self) -> Path:
        """Where story files live."""
        return self.repo / STORIES_DIR

    @property
    def requirements_dir(self) -> Path:
        """Where ``REQ-NNN.md`` files live."""
        return self.repo / self.team.docs_dir / REQUIREMENTS_DIR

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

    def delivery_refusal(self, name: str | None) -> str | None:
        """Why ``name`` cannot be a story's delivery, or None when it can (s64 V1-V5)."""
        if not name or self.delivery(name):
            return None
        names = ", ".join(d.name for d in self.deliveries)
        if names:
            return UNKNOWN_DELIVERY.format(name=name, names=names)
        return NO_DELIVERY.format(name=name)


def config_path(repo: Path) -> Path:
    return repo / CONFIG_NAME


def read_raw(repo: Path) -> dict[str, Any]:
    """Parse the config file into plain TOML data."""
    path = config_path(repo)
    if not system.is_file(path):
        raise ConfigError(f"{CONFIG_NAME} not found in {repo}; run `agile-team init`")
    try:
        return tomllib.loads(system.read_text(path))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{CONFIG_NAME}: {exc}") from exc


def from_raw(repo: Path, raw: dict[str, Any]) -> Config:
    """Build a ``Config`` from parsed TOML data."""
    return Config(
        repo=repo,
        team=_team(raw.get("team", {})),
        toolchain=_toolchain(raw.get("toolchain", {})),
        gates=_section(Gates, raw.get("gates", {})),
        upstream=_upstream(raw.get("upstream", {})),
        health=_section(HealthLimits, raw.get("health", {})),
        dashboard=_dashboard(raw.get("dashboard", {})),
        deliveries=[_delivery(d) for d in raw.get("delivery", [])],
        tools=_tools(raw.get("tool", [])),
        roles=dict(raw.get("roles", {})),
        providers={n: _provider(n, p) for n, p in raw.get("providers", {}).items()},
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
        targeted=[
            Targeted(str(r.get("root", "")), str(r.get("command", "")))
            for r in raw.get("targeted", [])
        ],
    )


def _section[T](cls: type[T], raw: dict[str, Any]) -> T:
    """Build the dataclass ``cls`` from the keys of ``raw`` it declares."""
    return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


def _dashboard(raw: dict[str, Any]) -> DashboardSettings:
    """Build ``[dashboard]``; the token must be a string."""
    settings = _section(DashboardSettings, raw)
    if not isinstance(settings.token, str):
        raise ConfigError(DASHBOARD_TOKEN)
    if not _seconds_ok(settings.collapse_under_s):
        raise ConfigError(DASHBOARD_COLLAPSE)
    return settings


def _seconds_ok(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float) and value >= 0


def _upstream(raw: dict[str, Any]) -> UpstreamSettings:
    return UpstreamSettings(
        **{k: v for k, v in raw.items() if k in UpstreamSettings.__dataclass_fields__}
    )


def _delivery(raw: dict[str, Any]) -> Delivery:
    return Delivery(**{k: v for k, v in raw.items() if k in Delivery.__dataclass_fields__})


def _provider(name: str, raw: dict[str, Any]) -> Provider:
    fields = {k: v for k, v in raw.items() if k in Provider.__dataclass_fields__}
    return Provider(**{**fields, "name": name})


@dataclass(frozen=True)
class Known:
    """Names the config may refer to: resolvable roles and delivery kinds."""

    roles: set[str]
    delivery_kinds: set[str]


Rule = tuple[Callable[[Any], bool], str]

TEAM_RULES: tuple[Rule, ...] = (
    (lambda t: t.cadence in CADENCES, f"team.cadence must be one of {CADENCES}"),
    (lambda t: t.auth in AUTH_MODES, f"team.auth must be one of {AUTH_MODES}"),
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
    (
        lambda t: all("{tests}" in r.command for r in t.targeted),
        "toolchain.targeted commands must hold {tests}",
    ),
)
GATE_RULES: tuple[Rule, ...] = (
    (lambda g: set(g.steps) <= set(PIPELINE_STEPS), f"gates.steps must be among {PIPELINE_STEPS}"),
    (lambda g: 0 <= g.coverage <= 100, "gates.coverage must be in 0..100"),
    (lambda g: g.round_cap >= 1, "gates.round_cap must be at least 1"),
    (lambda g: g.repeat >= 2, "gates.repeat must be at least 2"),
    (lambda g: g.backstop >= 2, "gates.backstop must be at least 2"),
    (lambda g: g.command_timeout_s > 0, "gates.command_timeout_s must be positive"),
    (lambda g: g.ci_timeout_s > 0, "gates.ci_timeout_s must be positive"),
)
HEALTH_KEYS = tuple(HealthLimits.__dataclass_fields__)
HEALTH_RULES: tuple[Rule, ...] = (
    *(
        (lambda h, key=key: getattr(h, key) > 0, f"health.{key} must be positive")
        for key in HEALTH_KEYS
    ),
    (lambda h: h.beat_s < h.stale_s, "health.beat_s must be below health.stale_s"),
    (
        lambda h: max(h.amber_tool_s, h.amber_quiet_s) <= h.red_quiet_s,
        "health.amber_tool_s and health.amber_quiet_s must not exceed health.red_quiet_s",
    ),
)
SAFE_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
UPSTREAM_RULES: tuple[Rule, ...] = (
    (lambda u: not u.remote or bool(u.branch), "upstream.branch must be set"),
    (
        lambda u: bool(SAFE_BRANCH.fullmatch(u.prefix)),
        "upstream.prefix must be a branch name prefix",
    ),
)
DELIVERY_RULES: tuple[Rule, ...] = (
    (lambda d: bool(SAFE_NAME.fullmatch(d.name)), "name must be lowercase letters, digits, - or _"),
    (lambda d: d.kind != "web" or bool(d.url), "(web) needs a url"),
    (lambda d: d.kind != "harness" or bool(d.commands), "(harness) needs commands"),
)
PROVIDER_RULES: tuple[Rule, ...] = (
    (lambda p: p.name != DEFAULT_PROVIDER, "is built in; pick another name"),
    (lambda p: p.kind in set(ProviderKind), f"kind must be one of {tuple(map(str, ProviderKind))}"),
    (lambda p: p.billing in set(Billing), f"billing must be one of {tuple(map(str, Billing))}"),
    (lambda p: p.base_url.startswith(("http://", "https://")), "base_url must be an http(s) URL"),
)
SAFE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")
REPEATED_DELIVERY = "delivery name {name!r} is repeated"
MISSING_ROLE = "roles.{name} is unknown; set extends or add .team/roles/{name}.md"
DANGLING_ROLE = "roles.{name} extends unknown role {base!r}"


def broken(rules: tuple[Rule, ...], subject: Any) -> list[str]:
    """Messages of the rules ``subject`` breaks."""
    return [message for ok, message in rules if not ok(subject)]


TOOL_NAME = re.compile(r"[a-z0-9][a-z0-9_+-]*(\.[a-z0-9][a-z0-9_+-]*)*")
TOOL_RULES: tuple[Rule, ...] = (
    (
        lambda t: bool(TOOL_NAME.fullmatch(t.name)),
        "name must be lowercase letters, digits, -, _, + and dots",
    ),
    (lambda t: not stages.reserved(t.name), "clashes with a built-in name; pick another"),
    (lambda t: bool(t.description.strip()), "needs a description"),
    (lambda t: bool(t.command.strip()), "needs a command"),
)
REPEATED_TOOL = "[[tool]] name {name!r} is repeated"


def _tool(raw: dict[str, Any]) -> Tool:
    return Tool(*(str(raw.get(key, "")) for key in ("name", "description", "command")))


def tool_problems(tools: list[Tool]) -> list[str]:
    """Every way the ``[[tool]]`` rows break the rules, in message order."""
    names = [t.name for t in tools]
    repeated = sorted({n for n in names if names.count(n) > 1})
    problems = [f"[[tool]] {t.name!r} {m}" for t in tools for m in broken(TOOL_RULES, t)]
    return problems + [REPEATED_TOOL.format(name=n) for n in repeated]


def _tools(raw: list[dict[str, Any]]) -> list[Tool]:
    tools = [_tool(row) for row in raw]
    if problems := tool_problems(tools):
        raise ConfigError("; ".join(problems))
    return tools


def validate(config: Config, known: Known) -> list[str]:
    """Return human-readable problems with ``config``; empty means valid."""
    return [
        *broken(TEAM_RULES, config.team),
        *broken(TOOLCHAIN_RULES, config.toolchain),
        *broken(GATE_RULES, config.gates),
        *broken(UPSTREAM_RULES, config.upstream),
        *broken(HEALTH_RULES, config.health),
        *_validate_deliveries(config.deliveries, known.delivery_kinds),
        *_validate_roles(config.roles, known.roles),
        *_validate_providers(config.providers),
    ]


def _validate_providers(providers: dict[str, Provider]) -> list[str]:
    problems = {p.name: broken(PROVIDER_RULES, p) for p in providers.values()}
    return [f"providers.{name} {m}" for name, messages in problems.items() for m in messages]


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
