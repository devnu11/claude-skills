"""Role definitions: parsing, ``extends`` resolution, overrides and prompt assembly.

A role is a Markdown file whose YAML frontmatter is data (model, effort, tools,
read/write globs) and whose body is the system prompt. Sources, lowest
precedence first:

1. built-in ``agile_team/roles/<name>.md``;
2. a complete global file ``~/.config/agile-team/roles/<name>.md`` (one with
   frontmatter; ``$AGILE_TEAM_HOME/roles`` when set), which replaces the
   built-in;
3. a complete repo file ``.team/roles/<name>.md``, which replaces both;
4. a config-only role ``[roles.<name>]`` with ``extends``;
5. ``[roles.<name>]`` field overrides in ``.agile-team.toml``;
6. run-time model overrides set by the Product Owner.

A global or repo file *without* frontmatter is an addendum appended to the
body, global first. HTML comments in an addendum are dropped, so a scaffolded
stub adds nothing until the human writes in it. ``_shared.md`` addenda apply
to every role.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from .providers import DEFAULT as DEFAULT_PROVIDER

BUILTIN_DIR = Path(__file__).parent / "roles"
SHARED = "_shared"
REPO_ROLES = ".team/roles"
USER_ROLES = ".config/agile-team/roles"
HOME_ENV = "AGILE_TEAM_HOME"
CHARTER = ".team/CLAUDE.md"
BRIEFS = ".team/briefs"
OVERRIDABLE = (
    "model",
    "effort",
    "provider",
    "tools",
    "write",
    "read",
    "enabled",
    "description",
)
FRONTMATTER_KEYS = frozenset({*OVERRIDABLE, "extends"})
HANDOFF_STATUSES = ("done", "changes_requested", "blocked", "failed")
RULINGS = ("rescope", "upgrade_model", "revise_design", "escalate")

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
_HANDOFF = re.compile(r"```handoff\s*\n(.*?)\n```", re.DOTALL)
_PLACEHOLDER = re.compile(r"\A(!?)\{(\w+)\}\Z")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

STUB = """<!--
{name}: your instructions for this role ({layer} layer).

Write plain Markdown below this comment; it is appended to the role's
built-in prompt. Layers apply in order: built-in, then global
(~/.config/agile-team/roles/, or $AGILE_TEAM_HOME/roles/), then this repo
(.team/roles/). To replace the role entirely, start the file with YAML
frontmatter (---) instead. _shared.md applies to every role.
This comment is ignored.

Role: {description}
-->
"""


class Layer(StrEnum):
    """Where a human's role file lives."""

    GLOBAL = "global"
    REPO = "repo"


def user_roles_dir(home: Path, env: Mapping[str, str]) -> Path:
    """The global role layer: ``$AGILE_TEAM_HOME/roles`` or ``~/.config/agile-team/roles``."""
    custom = env.get(HOME_ENV)
    return Path(custom).expanduser() / "roles" if custom else home / USER_ROLES


class RoleError(Exception):
    """A role file or reference is malformed."""


class HandoffError(Exception):
    """A role's final message has no valid handoff block."""


@dataclass
class RoleSpec:
    """One role after parsing. ``None`` fields inherit from ``extends``."""

    name: str
    body: str = ""
    model: str | None = None
    effort: str | None = None
    provider: str | None = None
    tools: list[str] | None = None
    write: list[str] | None = None
    read: list[str] | None = None
    extends: str | None = None
    enabled: bool | None = None
    description: str | None = None


@dataclass
class ResolvedRole:
    """A role ready to dispatch: every field concrete, prompt body assembled."""

    name: str
    body: str
    model: str
    effort: str
    provider: str = DEFAULT_PROVIDER
    tools: list[str] = field(default_factory=list)
    write: list[str] = field(default_factory=list)
    read: list[str] = field(default_factory=list)
    enabled: bool = True
    description: str = ""


@dataclass(frozen=True)
class Dispute:
    """A developer's claim that ``test`` contradicts design rule ``rule``."""

    test: str
    rule: str
    reason: str = ""


@dataclass
class Handoff:
    """The fixed summary every role ends with; the runner parses it for gates."""

    status: str
    summary: str = ""
    changed_files: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    next_role: str | None = None
    ruling: str | None = None
    friction: str = ""
    followups: dict[str, str] = field(default_factory=dict)
    developer: str | None = None
    dispute: Dispute | None = None


def split_frontmatter(name: str, text: str) -> tuple[dict[str, Any] | None, str]:
    """YAML frontmatter as a mapping (``None`` when absent) and the body after it."""
    match = _FRONTMATTER.match(text)
    if not match:
        return None, text
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        raise RoleError(f"{name}: frontmatter must be a mapping")
    return meta, match.group(2)


def parse_role(name: str, text: str) -> RoleSpec:
    """Parse a role file. Without frontmatter the whole text is the body."""
    meta, body = split_frontmatter(name, text)
    if meta is None:
        return RoleSpec(name=name, body=text.strip())
    _check_keys(name, meta)
    values = {k: meta[k] for k in FRONTMATTER_KEYS if k in meta}
    return RoleSpec(name=meta.get("name", name), body=body.strip(), **values)


def _check_keys(name: str, meta: dict[str, Any]) -> None:
    unknown = set(meta) - FRONTMATTER_KEYS - {"name"}
    if unknown:
        raise RoleError(f"{name}: unknown frontmatter keys {sorted(unknown)}")


def has_frontmatter(text: str) -> bool:
    return bool(_FRONTMATTER.match(text))


def addendum_text(text: str) -> str:
    """The part of a frontmatter-less file that is appended to a prompt."""
    return "" if has_frontmatter(text) else _COMMENT.sub("", text).strip()


def contribution(text: str | None) -> str | None:
    """How one layer's file affects a role: ``replace``, ``addendum``, ``stub`` or nothing."""
    if text is None:
        return None
    if has_frontmatter(text):
        return "replace"
    return "addendum" if addendum_text(text) else "stub"


def load_dir(directory: Path) -> dict[str, str]:
    """Raw text of every ``*.md`` in ``directory``, keyed by stem."""
    if not directory.is_dir():
        return {}
    return {p.stem: p.read_text() for p in sorted(directory.glob("*.md"))}


@dataclass
class RoleBook:
    """All role sources for one repo, with resolution and prompt assembly."""

    builtin: dict[str, str]
    repo_files: dict[str, str]
    config_roles: dict[str, dict[str, Any]]
    repo: Path = field(default_factory=Path)
    user_files: dict[str, str] = field(default_factory=dict)

    @classmethod
    def for_repo(
        cls, repo: Path, config_roles: dict[str, dict[str, Any]], user_dir: Path | None = None
    ) -> RoleBook:
        """Built-in, global (``user_dir``) and repo role files for ``repo``."""
        user = load_dir(user_dir) if user_dir else {}
        return cls(load_dir(BUILTIN_DIR), load_dir(repo / REPO_ROLES), config_roles, repo, user)

    def _human_layers(self) -> tuple[dict[str, str], dict[str, str]]:
        """Human-written files, highest precedence first."""
        return self.repo_files, self.user_files

    def names(self) -> set[str]:
        """Every role that can be resolved (built-in, global or repo files, config-only)."""
        complete = {
            n for files in self._human_layers() for n, t in files.items() if has_frontmatter(t)
        }
        return (set(self.builtin) | complete | set(self.config_roles)) - {SHARED}

    def enabled_names(self) -> list[str]:
        return sorted(n for n in self.names() if self.resolve(n).enabled)

    def spec(self, name: str) -> RoleSpec:
        """The base spec for ``name`` before ``extends`` and overrides."""
        texts = (files.get(name, "") for files in self._human_layers())
        complete = next((t for t in texts if has_frontmatter(t)), None)
        if complete:
            return parse_role(name, complete)
        if name in self.builtin:
            return parse_role(name, self.builtin[name])
        return self._config_only(name)

    def _config_only(self, name: str) -> RoleSpec:
        base = self.config_roles.get(name, {}).get("extends")
        if not base:
            raise RoleError(f"unknown role {name!r}")
        return RoleSpec(name=name, extends=base)

    def chain(self, name: str) -> list[RoleSpec]:
        """``name`` and its ancestors, root first, excluding ``_shared``."""
        specs: list[RoleSpec] = []
        current: str | None = name
        while current and current != SHARED:
            if any(s.name == current for s in specs):
                raise RoleError(f"extends cycle at {current!r}")
            specs.append(self.spec(current))
            current = specs[-1].extends
        return list(reversed(specs))

    def addendum(self, name: str) -> str:
        """Global then repo addenda for ``name``, comments removed."""
        texts = (files.get(name, "") for files in reversed(self._human_layers()))
        return "\n\n".join(t for t in map(addendum_text, texts) if t)

    def layers(self, name: str) -> dict[str, str | None]:
        """What each layer contributes to ``name``."""
        return {
            "builtin": "base" if name in self.builtin else None,
            Layer.GLOBAL: contribution(self.user_files.get(name)),
            Layer.REPO: contribution(self.repo_files.get(name)),
        }

    def scaffold(self, directory: Path, layer: Layer) -> list[Path]:
        """Write a stub for ``_shared`` and each enabled role lacking a file in ``directory``."""
        missing = [
            n for n in (SHARED, *self.enabled_names()) if not (directory / f"{n}.md").exists()
        ]
        directory.mkdir(parents=True, exist_ok=True)
        for name in missing:
            (directory / f"{name}.md").write_text(self._stub(name, layer))
        return [directory / f"{n}.md" for n in missing]

    def _stub(self, name: str, layer: Layer) -> str:
        what = "rules every role follows" if name == SHARED else self.resolve(name).description
        return STUB.format(name=name, layer=layer, description=what)

    def resolve(self, name: str, runtime: dict[str, Any] | None = None) -> ResolvedRole:
        """Merge the chain, config overrides and run-time overrides."""
        chain = self.chain(name)
        merged = _merge(chain, [self.config_roles.get(name, {}), runtime or {}])
        bodies = [s.body for s in chain] + [self.addendum(name)]
        merged.body = "\n\n".join(b for b in bodies if b)
        return _concrete(merged)

    def shared_body(self) -> str:
        """The built-in ``_shared`` body plus any human ``_shared`` addenda."""
        base = parse_role(SHARED, self.builtin.get(SHARED, "")).body
        return "\n\n".join(p for p in (base, self.addendum(SHARED)) if p)

    def system_prompt(self, role: ResolvedRole, scope: str) -> str:
        """``_shared`` + role chain + addendum + charter + Scribe brief + scope note."""
        brief = self.repo / BRIEFS / f"{role.name}.md"
        parts = [
            self.shared_body(),
            role.body,
            _section("Repo charter", _read_optional(self.repo / CHARTER)),
            _section("Brief from the Scribe", _read_optional(brief)),
            _section("Your file scope", scope),
        ]
        return "\n\n".join(p for p in parts if p)


def _merge(chain: list[RoleSpec], overrides: list[dict[str, Any]]) -> RoleSpec:
    """Root-first fields from the chain, then each override dict on top."""
    layers = [{k: getattr(s, k) for k in OVERRIDABLE} for s in chain] + overrides
    merged: dict[str, Any] = {}
    for layer in layers:
        merged.update({k: v for k, v in layer.items() if k in OVERRIDABLE and v is not None})
    return RoleSpec(name=chain[-1].name, **merged)


def _concrete(spec: RoleSpec) -> ResolvedRole:
    if not spec.model or not spec.effort:
        raise RoleError(f"{spec.name}: model and effort must be set somewhere in its chain")
    return ResolvedRole(
        name=spec.name,
        body=spec.body,
        model=spec.model,
        effort=spec.effort,
        provider=spec.provider or DEFAULT_PROVIDER,
        tools=list(spec.tools or []),
        write=list(spec.write or []),
        read=list(spec.read or ["**"]),
        enabled=spec.enabled is not False,
        description=spec.description or "",
    )


def expand_globs(globs: list[str], values: dict[str, list[str]]) -> list[str]:
    """Replace ``{name}`` / ``!{name}`` entries with the configured glob lists."""
    return [out for glob in globs for out in _expand_one(glob, values)]


def _expand_one(glob: str, values: dict[str, list[str]]) -> list[str]:
    match = _PLACEHOLDER.match(glob)
    if not match:
        return [glob]
    neg, key = match.groups()
    if key not in values:
        raise RoleError(f"unknown glob placeholder {{{key}}}")
    # Negating a list drops its own exclusions: "!{tests}" excludes only what tests include.
    return [neg + g for g in values[key] if not (neg and g.startswith("!"))]


def scope_note(write: list[str], read: list[str]) -> str:
    """Plain description of the globs a role may write and read."""
    writes = ", ".join(write) if write else "nothing (report through your handoff)"
    return f"You may write: {writes}\nYou may read: {', '.join(read)}"


def _section(title: str, text: str) -> str:
    return f"## {title}\n\n{text.strip()}" if text.strip() else ""


def _read_optional(path: Path) -> str:
    return path.read_text() if path.is_file() else ""


def parse_handoff(text: str) -> Handoff:
    """Parse the last ```handoff``` JSON block in a role's final message."""
    blocks = _HANDOFF.findall(text or "")
    if not blocks:
        raise HandoffError("no ```handoff``` block in the role's final message")
    try:
        data = json.loads(blocks[-1])
    except json.JSONDecodeError as exc:
        raise HandoffError(f"handoff block is not valid JSON: {exc}") from exc
    return _handoff_from(data)


HANDOFF_RULES: tuple[tuple[Callable[[dict[str, Any]], bool], str], ...] = (
    (lambda d: d.get("status") in HANDOFF_STATUSES, f"status must be one of {HANDOFF_STATUSES}"),
    (lambda d: isinstance(d.get("changed_files", []), list), "changed_files must be a list"),
    (lambda d: isinstance(d.get("open_questions", []), list), "open_questions must be a list"),
    (lambda d: d.get("ruling") in (None, *RULINGS), f"ruling must be one of {RULINGS}"),
    (lambda d: isinstance(d.get("friction", ""), str), "friction must be a string"),
    (lambda d: _str_map(d.get("followups", {})), "followups must map role names to questions"),
    (
        lambda d: d.get("developer") is None or isinstance(d.get("developer"), str),
        "developer must be a role name",
    ),
    (
        lambda d: _dispute_form(d.get("dispute")),
        "dispute needs a test id and a design rule",
    ),
    (
        lambda d: d.get("dispute") is None or d.get("status") == "changes_requested",
        "dispute needs status changes_requested",
    ),
)


def _dispute_form(value: Any) -> bool:
    if value is None:
        return True
    named = isinstance(value, dict) and all(_text(value.get(k)) for k in ("test", "rule"))
    return named and isinstance(value.get("reason", ""), str)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _dispute_from(data: dict[str, Any], summary: str) -> Dispute | None:
    d = data.get("dispute")
    return Dispute(d["test"], d["rule"], d.get("reason") or summary) if d else None


def _str_map(value: Any) -> bool:
    return isinstance(value, dict) and all(isinstance(v, str) for v in value.values())


def _handoff_from(data: Any) -> Handoff:
    if not isinstance(data, dict):
        raise HandoffError("handoff must be a JSON object")
    broken = next((msg for ok, msg in HANDOFF_RULES if not ok(data)), None)
    if broken:
        raise HandoffError(f"handoff {broken}")
    return Handoff(
        status=data["status"],
        summary=str(data.get("summary", "")),
        changed_files=[str(p) for p in data.get("changed_files", [])],
        open_questions=[str(q) for q in data.get("open_questions", [])],
        next_role=data.get("next_role"),
        ruling=data.get("ruling"),
        friction=data.get("friction", ""),
        followups=dict(data.get("followups", {})),
        developer=data.get("developer") or None,
        dispute=_dispute_from(data, str(data.get("summary", ""))),
    )


def handoff_report(handoff: Handoff) -> dict[str, Any]:
    return {
        "status": handoff.status,
        "summary": handoff.summary,
        "open_questions": handoff.open_questions,
        "next_role": handoff.next_role,
        "friction": handoff.friction,
    }
