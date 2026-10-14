"""Files the liaison shares with the team, checked by hash (s120).

A share is copied under ``<docs>/design/`` and recorded, with its SHA-256, in the story
file's ``shared:`` list. The gates read that list: the design must name each file, and
acceptance fails when one changed.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import yaml

from . import roles, story_spec, system
from .config import Config

MAX_BYTES = 5 * 1024 * 1024
FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
KEY = "shared"
SHORT = 12
SUBJECT = "chore({story}): share {name} ({id})"
QUEUED = "queued {id}: {path} (sha256 {short}); the runner commits it between steps"
TOLD = (
    "Runner note: the liaison shared {path} for {story} (sha256 {short}, commit {commit}). "
    "Every role can read it; acceptance checks its hash."
)
CHANGED = (
    "shared files changed since the liaison shared them:\n{lines}\n"
    "Restore each to its shared version (the `chore({story}): share …` commit), "
    "or ask the PO to have the liaison share the new version"
)
CHANGED_LINE = "- {path}: sha256 {found} (shared {recorded})"
MISSING_LINE = "- {path}: missing (shared {recorded})"
UNNAMED = "{file} does not name the shared file {path}; list it under ## Shared files"
BRIEF_HEAD = (
    "## Shared files\n\nThe liaison shared these files for {story}. "
    "Read them; never edit them: acceptance checks each one's SHA-256.\n{note}\n\n"
)
BRIEF_LINE = "- `{path}` (sha256 {short})"
BRIEF_NOTES: dict[str, str] = {
    "architect": (
        "Name each path in your design file under ## Shared files; the design gate checks it."
    ),
    "customer-proxy": "Where an AC refers to one, judge the product against it.",
}
UNPARSED = "the frontmatter does not parse, or its shared list is malformed"


class Refused(StrEnum):
    """Why a share is refused."""

    BAD_ID = "bad_id"
    NO_STORY = "no_story"
    BAD_NAME = "bad_name"
    UNREADABLE = "unreadable"
    EMPTY = "empty"
    TOO_BIG = "too_big"
    STORY_FILE = "story_file"


REFUSALS: dict[Refused, str] = {
    Refused.BAD_ID: "no story '{story}'",
    Refused.NO_STORY: "no story '{story}': {file} does not exist",
    Refused.BAD_NAME: (
        "file name '{name}' must be letters, digits, '.', '_' or '-', at most 100, "
        "starting with a letter or digit; rename it"
    ),
    Refused.UNREADABLE: "cannot read {source}: {error}",
    Refused.EMPTY: "the file is empty",
    Refused.TOO_BIG: "the file is {size} bytes; the limit is {limit}",
    Refused.STORY_FILE: "{file}: cannot record the share; fix its frontmatter ({problem})",
}


@dataclass(frozen=True)
class SharedFile:
    """One entry of a story's ``shared:`` list."""

    path: str
    sha256: str


@dataclass(frozen=True)
class Listed:
    """A story's shared files and the problems found reading the list."""

    files: tuple[SharedFile, ...] = ()
    problems: tuple[str, ...] = ()

    def paths(self) -> tuple[str, ...]:
        """The shared paths."""
        return tuple(f.path for f in self.files)

    def unnamed(self, text: str) -> list[str]:
        """The shared paths that ``text`` does not contain (S10)."""
        return [p for p in self.paths() if p not in text]

    def changed(self, found: Mapping[str, str | None]) -> list[str]:
        """One line per file whose hash differs or that is missing (S12)."""
        return [line for f in self.files if (line := _changed_line(f, found.get(f.path)))]


def _changed_line(entry: SharedFile, found: str | None) -> str | None:
    recorded = entry.sha256[:SHORT]
    if found is None:
        return MISSING_LINE.format(path=entry.path, recorded=recorded)
    if found != entry.sha256:
        return CHANGED_LINE.format(path=entry.path, found=found[:SHORT], recorded=recorded)
    return None


@dataclass(frozen=True)
class Check:
    """The shared files of a story and the lines for those that changed."""

    listed: Listed
    changed: tuple[str, ...] = ()


def digest(data: bytes) -> str:
    """The SHA-256 of raw bytes, in lowercase hex."""
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Share:
    """A file the liaison asks to share; ``id`` is empty until queued."""

    id: str
    story: str
    name: str
    data: bytes
    at: float = 0.0

    def sha256(self) -> str:
        """The SHA-256 of the bytes."""
        return digest(self.data)

    def to_json(self) -> str:
        """The queued request file's text."""
        return json.dumps(
            {
                "story": self.story,
                "name": self.name,
                "sha256": self.sha256(),
                "data": base64.b64encode(self.data).decode("ascii"),
                "at": self.at,
            }
        )

    @classmethod
    def from_json(cls, rid: str, text: str) -> Share | None:
        """Read a request file, or None for bad JSON, shape, base64 or hash."""
        try:
            raw = json.loads(text)
            data = base64.b64decode(raw["data"], validate=True)
            share = cls(rid, raw["story"], raw["name"], data, float(raw["at"]))
            return share if share.sha256() == raw["sha256"] else None
        except (ValueError, TypeError, KeyError, binascii.Error):
            return None


def _docs(docs_dir: str) -> str:
    return docs_dir.rstrip("/")


def target_of(docs_dir: str, share: Share) -> str:
    """Where a share lands: ``<docs>/design/<story>-<name>`` (S3)."""
    return f"{_docs(docs_dir)}/design/{share.story}-{share.name}"


def story_refusal(config: Config, share: Share) -> str | None:
    """S2 items 1 to 3: the story id, the story file, the file name."""
    from .backlog import STORY_ID  # backlog imports gates, which imports this module

    file = story_spec.file_of(config, share.story)
    fields = {"story": share.story, "file": file, "name": share.name}
    if not STORY_ID.match(share.story):
        return REFUSALS[Refused.BAD_ID].format(**fields)
    if not system.is_file(config.repo / file):
        return REFUSALS[Refused.NO_STORY].format(**fields)
    if not FILE_NAME.match(share.name):
        return REFUSALS[Refused.BAD_NAME].format(**fields)
    return None


def data_refusal(data: bytes) -> str | None:
    """S2 items 5 and 6: an empty file, a file over the limit."""
    if not data:
        return REFUSALS[Refused.EMPTY]
    if len(data) > MAX_BYTES:
        return REFUSALS[Refused.TOO_BIG].format(size=len(data), limit=MAX_BYTES)
    return None


@dataclass(frozen=True)
class Where:
    """Where a list was read: the story file, and the folder its paths must be under."""

    file: str
    design_dir: str  # "" accepts any path


def _item_problem(item: Any, where: Where, seen: set[str]) -> str | None:
    if not isinstance(item, dict):
        return "not a mapping"
    path, sha = item.get("path"), item.get("sha256")
    if not (isinstance(path, str) and path.startswith(where.design_dir)):
        return f"path must be a string under {where.design_dir or 'the repo'}"
    if not (isinstance(sha, str) and SHA256.match(sha)):
        return "sha256 must be 64 lowercase hex digits"
    return f"path {path} is listed twice" if path in seen else None


def listed(where: Where, meta: dict[str, Any]) -> Listed:
    """Read a story's ``shared:`` list (S6); a missing key is an empty list."""
    if KEY not in meta:
        return Listed()
    items = meta[KEY]
    if not isinstance(items, list):
        return Listed(problems=(f"{where.file}: {KEY}: not a list",))
    files: list[SharedFile] = []
    problems: list[str] = []
    for n, item in enumerate(items, 1):
        problem = _item_problem(item, where, {f.path for f in files})
        if problem:
            problems.append(f"{where.file}: {KEY} item {n}: {problem}")
        else:
            files.append(SharedFile(item["path"], item["sha256"]))
    return Listed(tuple(files), tuple(problems))


def render(files: tuple[SharedFile, ...]) -> str:
    """The ``shared:`` block, ending with a newline (S5)."""
    rows = "".join(
        f"  - path: {json.dumps(f.path)}\n    sha256: {json.dumps(f.sha256)}\n" for f in files
    )
    return f"{KEY}:\n{rows}"


def _without_block(head: str) -> str:
    kept: list[str] = []
    inside = False
    for line in head.split("\n"):
        inside = (inside and line[:1] in (" ", "\t")) or line.startswith(f"{KEY}:")
        if not inside:
            kept.append(line)
    return "\n".join(kept)


def _merged(files: tuple[SharedFile, ...], entry: SharedFile) -> tuple[SharedFile, ...]:
    if any(f.path == entry.path for f in files):
        return tuple(entry if f.path == entry.path else f for f in files)
    return (*files, entry)


def _parse(text: str) -> tuple[dict[str, Any], str] | None:
    try:
        meta, body = roles.split_frontmatter("story", text)
    except (roles.RoleError, yaml.YAMLError):
        return None
    return None if meta is None else (meta, body)


def with_entry(text: str, entry: SharedFile) -> str | None:
    """``text`` with ``entry`` in its ``shared:`` list (S5), or None when that is unsafe."""
    parsed, match = _parse(text), roles.FRONTMATTER.match(text)
    anywhere = Where("", "")
    if parsed is None or match is None or (old := listed(anywhere, parsed[0])).problems:
        return None
    files = _merged(old.files, entry)
    head = _without_block(match.group(1)).rstrip("\n")
    made = f"---\n{head}\n{render(files)}".removesuffix("\n") + text[match.end(1) :]
    return made if _safe(made, parsed, files) else None


def _safe(made: str, parsed: tuple[dict[str, Any], str], files: tuple[SharedFile, ...]) -> bool:
    again = _parse(made)
    if again is None or again[1] != parsed[1]:
        return False
    rest = {k: v for k, v in again[0].items() if k != KEY}
    before = {k: v for k, v in parsed[0].items() if k != KEY}
    return rest == before and listed(Where("", ""), again[0]) == Listed(files)


def _story_of(path: str) -> str:
    return path.rsplit("/", 1)[-1].split("-", 1)[0]


def brief_section(found: Listed, role: str) -> str:
    """The ``## Shared files`` section of a role's brief (S9); empty when none applies."""
    if not found.files or role not in BRIEF_NOTES:
        return ""
    head = BRIEF_HEAD.format(story=_story_of(found.files[0].path), note=BRIEF_NOTES[role])
    lines = (BRIEF_LINE.format(path=f.path, short=f.sha256[:SHORT]) for f in found.files)
    return head + "\n".join(lines)


def listed_of(config: Config, story: str) -> Listed:
    """The shared files in a story's file; empty when it is missing or unparseable."""
    file = story_spec.file_of(config, story)
    try:
        parsed = _parse(system.read_text(config.repo / file))
    except OSError:
        return Listed()
    if parsed is None:
        return Listed()
    return listed(Where(file, f"{_docs(config.team.docs_dir)}/design/"), parsed[0])


def _found(config: Config, path: str) -> str | None:
    try:
        return digest(system.read_bytes(config.repo / path))
    except OSError:
        return None


def check(config: Config, story: str) -> Check:
    """The story's shared files and those that changed since they were shared (S12)."""
    found = listed_of(config, story)
    hashes = {p: _found(config, p) for p in found.paths()}
    return Check(found, tuple(found.changed(hashes)))
