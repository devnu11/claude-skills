"""Story-file frontmatter helpers shared by shares and story drafts (s135)."""

from __future__ import annotations

from typing import Any

import yaml

from . import roles

BLOCK_STARTS = (" ", "\t", "-")


def parse(text: str) -> tuple[dict[str, Any], str] | None:
    """The frontmatter mapping and body of ``text``, or None when it has no readable one."""
    try:
        meta, body = roles.split_frontmatter("story", text)
    except (roles.RoleError, yaml.YAMLError):
        return None
    return None if meta is None else (meta, body)


def without_key(head: str, key: str) -> str:
    """``head`` without the top-level ``key:`` line and the block under it."""
    kept: list[str] = []
    inside = False
    for line in head.split("\n"):
        inside = (inside and line[:1] in BLOCK_STARTS) or line.startswith(f"{key}:")
        if not inside:
            kept.append(line)
    return "\n".join(kept)
