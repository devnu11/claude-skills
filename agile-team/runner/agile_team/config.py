"""Load and validate ``<repo>/.agile-team.toml``.

The file is the single place a repo customizes the team: toolchain commands
and globs, gates, acceptance environments, budget and per-role overrides. Role prompt
addenda live beside it in ``.team/roles/*.md`` and are handled by ``roles``.
"""

from __future__ import annotations

import re
import shlex
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import stages, system
from .commands import DEFAULT_TIMEOUT_S
from .providers import DEFAULT as DEFAULT_PROVIDER
from .providers import Billing, Provider, ProviderKind
from .roles import retired_sections

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
    "ops-review",
    "tests",
    "implement",
    "quality",
    "review",
    "design-review",
    "e2e",
    "acceptance",
    "land",
)
LAST = ""  # an ALWAYS_STEPS anchor meaning the end of the pipeline
# (step, the step it follows): built-in steps the config cannot remove (s115 P2)
ALWAYS_STEPS: tuple[tuple[str, str], ...] = (("ops-review", "design"), ("land", LAST))
TOOLCHAIN_COMMANDS = ("test", "coverage", "lint", "static")
TEST_COMMANDS = ("test", "coverage")
PLACEHOLDER = re.compile(r"\{report(?::(?P<root>[^{}]*))?\}")
REPORT_ONLY_IN_TESTS = "toolchain.{name}: {{report}} only works in the test and coverage commands"
REPORT_NEEDS_OPTION = "toolchain.{name} uses {{report}}, but [toolchain.report] option is not set"
DASHBOARD_TOKEN = "[dashboard] token must be a string"
DASHBOARD_COLLAPSE = "[dashboard] collapse_under_s must be a number of seconds, 0 or more"
GLOB_KEYS = ("source", "tests", "e2e", "ci")
ENVIRONMENT_SECTION = "environment"
OLD_ENVIRONMENT_NAME = "delivery"  # the alias (s93 E1); the only place the old name appears
RENAMED_SECTIONS: dict[str, str] = {OLD_ENVIRONMENT_NAME: ENVIRONMENT_SECTION}
BOTH_SECTIONS = "[[{new}]] and [[{old}]] are both set; move every [[{old}]] into [[{new}]]"
RENAMED_WARNING = "[[{old}]] is the old name of [[{new}]]; rename the section"


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


class FileCommand(StrEnum):
    """Which per-file command template to use."""

    FIX = "fix"
    LINT = "lint_files"


@dataclass(frozen=True)
class FileCommands:
    """Per-file fix and lint templates (``{root}``, ``{files}``) and the globs they apply to."""

    fix: str = ""
    lint_files: str = ""
    lintable: tuple[str, ...] = ()

    def template(self, kind: FileCommand) -> str:
        """The template for ``kind``."""
        return {FileCommand.FIX: self.fix, FileCommand.LINT: self.lint_files}[kind]


@dataclass(frozen=True)
class ReportOptions:
    """How the test commands write a JUnit report and skip pending ids (s125 P1)."""

    option: str = ""  # {file}
    deselect: str = ""  # {id}
    ignore: str = ""  # {id}

    @property
    def on(self) -> bool:
        """True when the toolchain writes a report."""
        return bool(self.option)


@dataclass
class Toolchain:
    """Per-repo commands and the globs that role scopes resolve against."""

    preset: str = ""
    commands: dict[str, str] = field(default_factory=dict)
    pragma: str = ""
    globs: dict[str, list[str]] = field(default_factory=dict)
    targeted: list[Targeted] = field(default_factory=list)
    files: FileCommands = field(default_factory=FileCommands)
    report: ReportOptions = field(default_factory=ReportOptions)

    def file_runs(self, kind: FileCommand, files: list[str]) -> list[str]:
        """One command per targeted root holding some of ``files``, in first-seen order."""
        template = self.files.template(kind)
        groups: dict[str, list[str]] = {}
        for path in files:
            row = self.targeted_for(path)
            root, name = (row.root, row.relative(path)) if row else ("", path)
            groups.setdefault(root, []).append(name)
        return [_filled(template, (root, names)) for root, names in groups.items() if template]

    def targeted_for(self, path: str) -> Targeted | None:
        """The row with the longest root that holds ``path`` (R4)."""
        rows = [row for row in self.targeted if row.holds(path)]
        return max(rows, key=lambda row: len(row.root), default=None)


def _filled(template: str, group: tuple[str, list[str]]) -> str:
    root, names = group
    quoted = " ".join(shlex.quote(n) for n in names)
    return template.replace("{root}", shlex.quote(root or ".")).replace("{files}", quoted)


PRESETS = Path(__file__).parent / "presets.toml"


def load_presets() -> dict[str, dict[str, Any]]:
    """The packaged stack preset table."""
    return tomllib.loads(system.read_text(PRESETS))


DEFAULT_CI_TIMEOUT_S = 1800.0
DEFAULT_STOP_BUDGET_S = 1800.0


def _insert_at(steps: list[str], anchor: str) -> int:
    if anchor == LAST:
        return len(steps)
    return steps.index(anchor) + 1 if anchor in steps else 0


def pipeline_steps(listed: list[str]) -> list[str]:
    """The run's steps: ``listed`` with each ALWAYS_STEPS step right after its anchor, or first."""
    always = {step for step, _ in ALWAYS_STEPS}
    steps = [s for s in listed if s not in always]
    for step, anchor in ALWAYS_STEPS:
        steps.insert(_insert_at(steps, anchor), step)
    return steps


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
    stop_check_budget_s: float = DEFAULT_STOP_BUDGET_S

    @property
    def pipeline(self) -> list[str]:
        """The run's steps: the configured ones plus the built-in steps."""
        return pipeline_steps(self.steps)


@dataclass
class Environment:
    """One acceptance environment: how the customer proxy tries the product.

    The kind is one of ``sandbox.ENVIRONMENT_KINDS``.

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
    story_prefix: str = "team/story-"


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
    max_open_stories: int = 5
    step_reserve_usd: float = 1.0


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
    label: str = ""

    def chart_label(self) -> str:
        """The label the Flow chart shows: the row's ``label``, else its name (s127 LB3)."""
        return self.label.strip() or self.name


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
    environments: list[Environment] = field(default_factory=list)
    tools: list[Tool] = field(default_factory=list)
    roles: dict[str, dict[str, Any]] = field(default_factory=dict)
    providers: dict[str, Provider] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    run_home: Path | None = None

    @property
    def run_dir(self) -> Path:
        return (self.run_home or self.repo) / RUN_DIR

    def at_worktree(  # house-rules: allow verb-name -- name fixed by the tests
        self, path: Path
    ) -> Config:
        """This config seen from a story's worktree; ``run_dir`` stays the main checkout's."""
        return replace(self, repo=path, run_home=self.run_home or self.repo)

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

    def environment(self, name: str | None) -> Environment | None:
        """The named acceptance environment, or the first one when ``name`` is empty."""
        if not name:
            return self.environments[0] if self.environments else None
        return next((d for d in self.environments if d.name == name), None)


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
    sections = renamed(raw)
    return Config(
        repo=repo,
        team=_team(sections.get("team", {})),
        toolchain=_toolchain(sections.get("toolchain", {})),
        gates=_section(Gates, sections.get("gates", {})),
        upstream=_upstream(sections.get("upstream", {})),
        health=_section(HealthLimits, sections.get("health", {})),
        dashboard=_dashboard(sections.get("dashboard", {})),
        environments=[_environment(e) for e in sections.get(ENVIRONMENT_SECTION, [])],
        tools=_tools(sections.get("tool", [])),
        roles=_roles(sections.get("roles", {})),
        providers={n: _provider(n, p) for n, p in sections.get("providers", {}).items()},
        warnings=rename_warnings(raw),
    )


def renamed(raw: dict[str, Any]) -> dict[str, Any]:
    """``raw`` with old section names moved to their new names (E2); both set is an error (E3)."""
    for old, new in RENAMED_SECTIONS.items():
        if old in raw and new in raw:
            raise ConfigError(BOTH_SECTIONS.format(old=old, new=new))
    return {RENAMED_SECTIONS.get(key, key): value for key, value in raw.items()}


def rename_warnings(raw: dict[str, Any]) -> list[str]:
    """One ``RENAMED_WARNING`` per old section name in ``raw`` (E4)."""
    return [RENAMED_WARNING.format(old=o, new=n) for o, n in RENAMED_SECTIONS.items() if o in raw]


def load(repo: Path) -> Config:
    """Read and parse the config for ``repo``."""
    return from_raw(repo, read_raw(repo))


def _team(raw: dict[str, Any]) -> Team:
    return Team(**{k: v for k, v in raw.items() if k in Team.__dataclass_fields__})


def _files(raw: dict[str, Any]) -> FileCommands:
    """The per-file commands: the named preset's, then the config's own keys over them."""
    preset = load_presets().get(raw.get("preset", ""), {}).get("files", {})
    merged = {**preset, **raw.get("files", {})}
    merged["lintable"] = tuple(merged.get("lintable", ()))
    known = FileCommands.__dataclass_fields__
    return FileCommands(**{k: v for k, v in merged.items() if k in known})


def _report(raw: dict[str, Any]) -> ReportOptions:
    """The report options: the named preset's, then the config's own keys over them."""
    preset = load_presets().get(raw.get("preset", ""), {}).get("report", {})
    merged = {**preset, **raw.get("report", {})}
    return _section(ReportOptions, merged)


def _report_problem(name: str, command: str, report: ReportOptions) -> str | None:
    if not PLACEHOLDER.search(command):
        return None
    if name not in TEST_COMMANDS:
        return REPORT_ONLY_IN_TESTS.format(name=name)
    return None if report.on else REPORT_NEEDS_OPTION.format(name=name)


def _check_report(commands: dict[str, str], report: ReportOptions) -> None:
    for name, command in commands.items():
        if problem := _report_problem(name, command, report):
            raise ConfigError(problem)


def _toolchain(raw: dict[str, Any]) -> Toolchain:
    commands = {k: raw[k] for k in TOOLCHAIN_COMMANDS if k in raw}
    report = _report(raw)
    _check_report(commands, report)
    return Toolchain(
        report=report,
        preset=raw.get("preset", ""),
        commands=commands,
        pragma=raw.get("pragma", ""),
        globs={k: list(v) for k, v in raw.get("globs", {}).items()},
        targeted=[
            Targeted(str(r.get("root", "")), str(r.get("command", "")))
            for r in raw.get("targeted", [])
        ],
        files=_files(raw),
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


def _environment(raw: dict[str, Any]) -> Environment:
    return Environment(**{k: v for k, v in raw.items() if k in Environment.__dataclass_fields__})


def _provider(name: str, raw: dict[str, Any]) -> Provider:
    fields = {k: v for k, v in raw.items() if k in Provider.__dataclass_fields__}
    return Provider(**{**fields, "name": name})


@dataclass(frozen=True)
class Known:
    """Names the config may refer to: resolvable roles and environment kinds."""

    roles: set[str]
    environment_kinds: set[str]


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
    (
        lambda t: type(t.max_open_stories) is int and t.max_open_stories >= 1,
        "team.max_open_stories must be an integer of at least 1",
    ),
    (
        lambda t: 0 <= t.step_reserve_usd < t.budget_usd,
        "team.step_reserve_usd must be at least 0 and below team.budget_usd",
    ),
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
    (
        lambda t: all("{files}" in c for c in (t.files.fix, t.files.lint_files) if c),
        "toolchain.files.fix and toolchain.files.lint_files must hold {files}",
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
    (lambda g: g.stop_check_budget_s > 0, "gates.stop_check_budget_s must be positive"),
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


def _prefixes_apart(  # house-rules: allow verb-name -- name fixed by the design
    u: UpstreamSettings,
) -> bool:
    one, other = u.prefix, u.story_prefix
    return not (one.startswith(other) or other.startswith(one))


UPSTREAM_RULES: tuple[Rule, ...] = (
    (lambda u: not u.remote or bool(u.branch), "upstream.branch must be set"),
    (
        lambda u: bool(SAFE_BRANCH.fullmatch(u.prefix)),
        "upstream.prefix must be a branch name prefix",
    ),
    (
        lambda u: bool(SAFE_BRANCH.fullmatch(u.story_prefix)),
        "upstream.story_prefix must be a branch name prefix",
    ),
    (
        _prefixes_apart,
        "upstream.story_prefix must differ from upstream.prefix, "
        "and neither may start with the other",
    ),
)
ENVIRONMENT_RULES: tuple[Rule, ...] = (
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
REPEATED_ENVIRONMENT = "acceptance environment name {name!r} is repeated"
EMPTY_HARNESS_PREPARE = (
    "acceptance environment {name!r} (harness) has no prepare, so the Proxy's sandbox holds only "
    "the presentation and its commands have no product to run; set prepare to build a runnable "
    "copy there"
)
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
    (
        lambda t: len(t.label.strip()) <= stages.LABEL_MAX,
        f"label must be at most {stages.LABEL_MAX} characters",
    ),
)
REPEATED_TOOL = "[[tool]] name {name!r} is repeated"
REPEATED_LABEL = "[[tool]] label {label!r} is repeated"


def _tool(raw: dict[str, Any]) -> Tool:
    return Tool(*(str(raw.get(key, "")) for key in ("name", "description", "command", "label")))


def _label_problems(tools: list[Tool]) -> list[str]:
    """A message for each chart label used twice, or used by a built-in stage (s127 LB3)."""
    labels = [t.chart_label() for t in tools]
    taken = sorted({x for x in labels if labels.count(x) > 1 or x in stages.LABELS})
    return [REPEATED_LABEL.format(label=x) for x in taken]


def tool_problems(tools: list[Tool]) -> list[str]:
    """Every way the ``[[tool]]`` rows break the rules, in message order."""
    names = [t.name for t in tools]
    repeated = sorted({n for n in names if names.count(n) > 1})
    problems = [f"[[tool]] {t.name!r} {m}" for t in tools for m in broken(TOOL_RULES, t)]
    named = [REPEATED_TOOL.format(name=n) for n in repeated]
    return problems + named + _label_problems(tools)


def _roles(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The ``[roles.*]`` sections, refusing a retired role (SC6)."""
    if problems := retired_sections(raw):
        raise ConfigError("; ".join(problems))
    return dict(raw)


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
        *_validate_environments(config.environments, known.environment_kinds),
        *_validate_roles(config.roles, known.roles),
        *_validate_providers(config.providers),
    ]


def environment_warnings(environments: list[Environment]) -> list[str]:
    """Valid settings that leave the Proxy nothing to run (#56)."""
    empty = [d for d in environments if d.kind == "harness" and not d.prepare.strip()]
    return [EMPTY_HARNESS_PREPARE.format(name=d.name) for d in empty]


def _validate_providers(providers: dict[str, Provider]) -> list[str]:
    problems = {p.name: broken(PROVIDER_RULES, p) for p in providers.values()}
    return [f"providers.{name} {m}" for name, messages in problems.items() for m in messages]


def _validate_environments(environments: list[Environment], kinds: set[str]) -> list[str]:
    names = [d.name for d in environments]
    repeated = sorted({n for n in names if names.count(n) > 1})
    problems = [p for d in environments for p in _environment_problems(d, kinds)]
    return problems + [REPEATED_ENVIRONMENT.format(name=n) for n in repeated]


def _environment_problems(environment: Environment, kinds: set[str]) -> list[str]:
    messages = broken(ENVIRONMENT_RULES, environment)
    if environment.kind not in kinds:
        messages.append(f"has unknown kind {environment.kind!r}")
    return [f"acceptance environment {environment.name!r} {m}" for m in messages]


def _validate_roles(roles: dict[str, dict[str, Any]], known: set[str]) -> list[str]:
    """A config-only role is allowed when it ``extends`` a known role."""
    bases = {n: o.get("extends") for n, o in roles.items() if n not in known}
    missing = [MISSING_ROLE.format(name=n) for n, b in bases.items() if not b]
    dangling = {n: b for n, b in bases.items() if b and b not in known}
    return missing + [DANGLING_ROLE.format(name=n, base=b) for n, b in dangling.items()]
