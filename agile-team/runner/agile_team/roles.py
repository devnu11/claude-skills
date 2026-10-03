"""Role definitions: parsing, ``extends`` resolution, overrides and prompt assembly.

A role is a Markdown file whose YAML frontmatter is data (model, effort, tools,
read/write globs) and whose body is the system prompt. Sources, lowest
precedence first:

1. built-in ``agile_team/roles/<name>.md``;
2. a complete repo file ``.team/roles/<name>.md`` (one with frontmatter), which
   replaces the built-in;
3. a config-only role ``[roles.<name>]`` with ``extends``;
4. ``[roles.<name>]`` field overrides in ``.agile-team.toml``;
5. run-time model overrides set by the Product Owner.

A repo file *without* frontmatter is an addendum appended to the body.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

import yaml

BUILTIN_DIR = Path(__file__).parent / "roles"
SHARED = "_shared"
REPO_ROLES = ".team/roles"
CHARTER = ".team/CLAUDE.md"
BRIEFS = ".team/briefs"
OVERRIDABLE = ("model", "effort", "tools", "write", "read", "enabled", "description")
HANDOFF_STATUSES = ("done", "changes_requested", "blocked", "failed")
RULINGS = ("rescope", "upgrade_model", "revise_design", "escalate")

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
_HANDOFF = re.compile(r"```handoff\s*\n(.*?)\n```", re.DOTALL)
_PLACEHOLDER = re.compile(r"\A(!?)\{(\w+)\}\Z")


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
    tools: list[str] = field(default_factory=list)
    write: list[str] = field(default_factory=list)
    read: list[str] = field(default_factory=list)
    enabled: bool = True
    description: str = ""


@dataclass
class Handoff:
    """The fixed summary every role ends with; the runner parses it for gates."""

    status: str
    summary: str = ""
    changed_files: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    next_role: str | None = None
    ruling: str | None = None


def parse_role(name: str, text: str) -> RoleSpec:
    """Parse a role file. Without frontmatter the whole text is the body."""
    match = _FRONTMATTER.match(text)
    if not match:
        return RoleSpec(name=name, body=text.strip())
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        raise RoleError(f"{name}: frontmatter must be a mapping")
    known = {f.name for f in fields(RoleSpec)} - {"name", "body"}
    unknown = set(meta) - known - {"name"}
    if unknown:
        raise RoleError(f"{name}: unknown frontmatter keys {sorted(unknown)}")
    values = {k: meta[k] for k in known if k in meta}
    return RoleSpec(name=meta.get("name", name), body=match.group(2).strip(), **values)


def has_frontmatter(text: str) -> bool:
    return bool(_FRONTMATTER.match(text))


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

    @classmethod
    def for_repo(cls, repo: Path, config_roles: dict[str, dict[str, Any]]) -> RoleBook:
        return cls(load_dir(BUILTIN_DIR), load_dir(repo / REPO_ROLES), config_roles)

    def names(self) -> set[str]:
        """Every role that can be resolved (built-in, repo files, config-only)."""
        complete = {n for n, t in self.repo_files.items() if has_frontmatter(t)}
        return (set(self.builtin) | complete | set(self.config_roles)) - {SHARED}

    def enabled_names(self) -> list[str]:
        return sorted(n for n in self.names() if self.resolve(n).enabled)

    def spec(self, name: str) -> RoleSpec:
        """The base spec for ``name`` before ``extends`` and overrides."""
        repo_text = self.repo_files.get(name)
        if repo_text is not None and has_frontmatter(repo_text):
            return parse_role(name, repo_text)
        if name in self.builtin:
            return parse_role(name, self.builtin[name])
        base = self.config_roles.get(name, {}).get("extends")
        if base:
            return RoleSpec(name=name, extends=base)
        raise RoleError(f"unknown role {name!r}")

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
        text = self.repo_files.get(name)
        return "" if text is None or has_frontmatter(text) else text.strip()

    def resolve(self, name: str, runtime: dict[str, Any] | None = None) -> ResolvedRole:
        """Merge the chain, config overrides and run-time overrides."""
        merged = _merge_chain(self.chain(name))
        merged = _apply(merged, self.config_roles.get(name, {}))
        merged = _apply(merged, runtime or {})
        bodies = [s.body for s in self.chain(name) if s.body] + [self.addendum(name)]
        return _concrete(name, merged, "\n\n".join(b for b in bodies if b))

    def shared_body(self) -> str:
        return parse_role(SHARED, self.builtin.get(SHARED, "")).body


def _merge_chain(chain: list[RoleSpec]) -> RoleSpec:
    merged = RoleSpec(name=chain[-1].name)
    for spec in chain:
        for key in OVERRIDABLE:
            value = getattr(spec, key)
            if value is not None:
                merged = replace(merged, **{key: value})
    return merged


def _apply(spec: RoleSpec, overrides: dict[str, Any]) -> RoleSpec:
    return replace(spec, **{k: v for k, v in overrides.items() if k in OVERRIDABLE})


def _concrete(name: str, spec: RoleSpec, body: str) -> ResolvedRole:
    if not spec.model or not spec.effort:
        raise RoleError(f"{name}: model and effort must be set somewhere in its chain")
    return ResolvedRole(
        name=name,
        body=body,
        model=spec.model,
        effort=spec.effort,
        tools=list(spec.tools or []),
        write=list(spec.write or []),
        read=list(spec.read or ["**"]),
        enabled=True if spec.enabled is None else bool(spec.enabled),
        description=spec.description or "",
    )


def expand_globs(globs: list[str], values: dict[str, list[str]]) -> list[str]:
    """Replace ``{name}`` / ``!{name}`` entries with the configured glob lists."""
    out: list[str] = []
    for glob in globs:
        match = _PLACEHOLDER.match(glob)
        if not match:
            out.append(glob)
            continue
        neg, key = match.groups()
        if key not in values:
            raise RoleError(f"unknown glob placeholder {{{key}}}")
        # Negating a list drops its own exclusions: "!{tests}" excludes only what tests include.
        out += [neg + g for g in values[key] if not (neg and g.startswith("!"))]
    return out


def system_prompt(book: RoleBook, role: ResolvedRole, repo: Path, scope: str) -> str:
    """``_shared`` + role chain + addendum + charter + Scribe brief + scope note."""
    parts = [
        book.shared_body(),
        role.body,
        _section("Repo charter", _read_optional(repo / CHARTER)),
        _section("Brief from the Scribe", _read_optional(repo / BRIEFS / f"{role.name}.md")),
        _section("Your file scope", scope),
    ]
    return "\n\n".join(p for p in parts if p)


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


def _handoff_from(data: Any) -> Handoff:
    if not isinstance(data, dict):
        raise HandoffError("handoff must be a JSON object")
    if data.get("status") not in HANDOFF_STATUSES:
        raise HandoffError(f"handoff status must be one of {HANDOFF_STATUSES}")
    for key in ("changed_files", "open_questions"):
        if not isinstance(data.get(key, []), list):
            raise HandoffError(f"handoff {key} must be a list")
    if data.get("ruling") not in (None, *RULINGS):
        raise HandoffError(f"handoff ruling must be one of {RULINGS}")
    return Handoff(
        status=data["status"],
        summary=str(data.get("summary", "")),
        changed_files=[str(p) for p in data.get("changed_files", [])],
        open_questions=[str(q) for q in data.get("open_questions", [])],
        next_role=data.get("next_role"),
        ruling=data.get("ruling"),
    )
